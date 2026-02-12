

"""
RPJ (Research Project Journey) specific implementation:
- Provide chat mode for user to talk to RPJ personal model (vLLM OpenAI-compatible)
- Inject research profile context and retrieval context (hybrid search + GraphRAG)
- Persist conversation history in DB for research continuity
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.db.models import CompanionConversation, CompanionMessage, Question, User
from backend.core.db.session import async_session_maker
from backend.core.services.graphrag_service import get_graphrag_service
from backend.core.services.learning_advisor_service import get_learning_advisor_service
from backend.core.services.personal_model_service import get_personal_model_service
from backend.core.services.embedding_service import get_embedding_service
from backend.core.services.hybrid_search_service import get_hybrid_search_service
from backend.modules.rpj.api.deps import get_current_user, get_db
from backend.modules.rpj.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

def _truncate(s: str, n: int = 240) -> str:
    s = (s or "").replace("\n", " ").strip()
    if len(s) <= n:
        return s
    return s[:n] + "...(truncated)"


class CompanionChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000, description="用户输入")
    conversation_id: Optional[int] = Field(None, description="会话ID（不传则新建）")
    mode: str = Field("chat", description="chat|research_advice|project_review")


class RetrievedItem(BaseModel):
    id: Optional[int] = None
    source: str
    score: Optional[float] = None
    title: Optional[str] = None
    content: str
    meta: Dict[str, Any] = {}


class CompanionChatResponse(BaseModel):
    conversation_id: int
    assistant_message: str
    retrieved: List[RetrievedItem] = []


def _sse(obj: Dict[str, Any]) -> bytes:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode("utf-8")


def _truthy(v: str | None) -> bool:
    return str(v or "").strip().lower() in {"1", "true", "yes", "y", "on"}


async def _personal_model_should_run(svc, trace_id: str) -> bool:
    """
    For RPJ module, auto-enable personal model if reachable
    """
    if svc.enabled:
        return True
    auto = os.environ.get("PERSONAL_MODEL_AUTO_ENABLE")
    if auto is None:
        auto = "true"
    if not _truthy(auto):
        return False
    try:
        # Health check (fast). If reachable, allow running even if ENABLED flag is false.
        await svc.list_models()
        logger.warning("[%s] RPJ personal model auto-enabled (env flag missing): set PERSONAL_MODEL_ENABLED_RPJ=true to suppress", trace_id)
        return True
    except Exception as e:
        logger.warning("[%s] RPJ personal model disabled and /v1/models unreachable: %r", trace_id, e)
        return False


async def _get_or_create_conversation(db: AsyncSession, user_id: int, conversation_id: Optional[int]) -> CompanionConversation:
    if conversation_id:
        res = await db.execute(
            select(CompanionConversation).where(
                CompanionConversation.id == int(conversation_id),
                CompanionConversation.user_id == int(user_id),
                CompanionConversation.module == settings.MODULE_NAME,
            )
        )
        conv = res.scalar_one_or_none()
        if conv:
            return conv
        raise HTTPException(status_code=404, detail="Conversation not found")

    conv = CompanionConversation(user_id=int(user_id), module=settings.MODULE_NAME, title="RPJ研究对话")
    db.add(conv)
    await db.flush()  # assign id
    return conv


async def _load_recent_messages(db: AsyncSession, conversation_id: int, limit: int = 12) -> List[CompanionMessage]:
    res = await db.execute(
        select(CompanionMessage)
        .where(CompanionMessage.conversation_id == int(conversation_id))
        .order_by(CompanionMessage.created_at.desc())
        .limit(int(limit))
    )
    msgs = list(res.scalars().all())
    return list(reversed(msgs))


def _system_prompt_for_mode(*, mode: str, profile: Dict[str, Any]) -> str:
    """
    RPJ-specific system prompt focused on research and project guidance
    """
    grade = profile.get("grade") or "未知"
    research_areas = profile.get("research_areas") or []
    weak_methods = profile.get("weak_research_methods") or []

    base = (
        "你是用户专属的研究项目小书童（数字孪生式研究伙伴）。\n"
        "你的目标：在保证研究方法科学的前提下，给出针对性研究指导，并提供创新思路和批判性思维。\n"
        "回答风格：先明确研究问题，再分点提出研究思路、方法和资源建议，最后给可执行的下一步计划。\n"
        "如果你不确定，请明确说明不确定并给出验证或探索的方法。\n"
        "\n"
        f"研究者画像：年级={grade}；研究方向={', '.join(research_areas) if research_areas else '待确定'}；"
        f"需强化的研究方法={', '.join(weak_methods) if weak_methods else '暂无'}。\n"
    )

    mode = (mode or "chat").strip().lower()
    if mode == "research_advice":
        return base + "\n当前任务：生成个性化研究建议/项目计划（要具体、可执行、可评估）。\n"
    if mode == "project_review":
        return base + "\n当前任务：进行项目进展回顾（问题反思、方法优化、数据解读、下一步方向）。\n"
    return base + "\n当前任务：与研究学生对话，指导研究思路和方法论，启发深度思考。\n"


def _format_retrieval_block(items: List[RetrievedItem]) -> str:
    if not items:
        return ""
    lines = ["以下是与研究问题相关的文献/项目记录（可能不完全准确，请你批判性思考）："]
    for i, it in enumerate(items[:8], start=1):
        snippet = (it.content or "").strip().replace("\n", " ")
        if len(snippet) > 500:
            snippet = snippet[:500] + "..."
        lines.append(f"[{i}] ({it.source}) {snippet}")
    return "\n".join(lines).strip()


async def _retrieve_context(
    *,
    db: AsyncSession,
    user_id: int,
    query: str,
    profile: Dict[str, Any],
    top_k: int = 5,
) -> List[RetrievedItem]:
    """
    Retrieval strategy for RPJ module:
    1) Hybrid search (FAISS+BM25) over research corpus for rpj module
    2) Optional GraphRAG expansion by research areas and methods
    """
    out: List[RetrievedItem] = []

    # Ensure hybrid index is initialized
    try:
        hs = get_hybrid_search_service()
        await hs.initialize(
            vector_store_path=settings.module_vector_path,
            bm25_index_path=settings.module_bm25_path,
        )
    except Exception as e:
        logger.debug(f"RPJ hybrid search init skipped: {e}")

    # Try embedding->vector hybrid search; fallback to BM25
    try:
        emb = await get_embedding_service().embed_text(query)
    except Exception:
        emb = None

    try:
        hs = get_hybrid_search_service()
        if emb:
            results = await hs.hybrid_search(
                query_text=query,
                query_embedding=emb,
                top_k=int(top_k),
                filter_metadata=None,
            )
        else:
            results = await hs.search_bm25(query_text=query, top_k=int(top_k), filter_metadata=None)
        for r in (results or []):
            out.append(
                RetrievedItem(
                    id=int(r.doc_id) if str(r.doc_id).isdigit() else None,
                    source=r.source or "hybrid",
                    score=float(r.score) if r.score is not None else None,
                    title=(r.metadata or {}).get("title") if isinstance(r.metadata, dict) else None,
                    content=r.document or "",
                    meta=r.metadata or {},
                )
            )
    except Exception as e:
        logger.debug(f"RPJ hybrid search failed: {e}")

    # GraphRAG expansion: add a few research contents by research areas
    try:
        if getattr(settings, "GRAPHRAG_ENABLED", False):
            graphrag = get_graphrag_service()
            await graphrag.initialize(graph_path=settings.module_graphrag_graph_path)
            research_areas = profile.get("research_areas", []) or []
            # For RPJ, default subject is "research"
            subject = "research"
            qids = graphrag.find_questions_by_knowledge_points(
                subject=subject,
                knowledge_points=research_areas,
                top_k=10,
                exclude_question_ids=set([it.id for it in out if it.id]),
            )
            if qids:
                rows = await db.execute(select(Question).where(Question.id.in_(qids), Question.user_id == int(user_id)))
                for q in rows.scalars().all():
                    out.append(
                        RetrievedItem(
                            id=int(q.id),
                            source="graphrag",
                            score=None,
                            title=q.title,
                            content=q.content,
                            meta={"research_areas": q.knowledge_points or [], "project_type": getattr(q, "project_type", None)},
                        )
                    )
    except Exception as e:
        logger.debug(f"RPJ graphrag expansion skipped: {e}")

    return out[: max(8, int(top_k))]


@router.post("/chat", response_model=CompanionChatResponse)
async def chat(
    body: CompanionChatRequest,
    project_type: Optional[str] = Query(None, description="项目类型（用于选择 <module>-sft-<project_type>）"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Chat with the user's RPJ "小书童".

    Backend will:
    - build student research profile (research areas, methods)
    - retrieve context (hybrid search + optional GraphRAG)
    - call the personal model (OpenAI-compatible vLLM)
    - store conversation history
    """
    msg = (body.message or "").strip()
    if not msg:
        raise HTTPException(status_code=400, detail="message is required")

    t0 = time.monotonic()
    svc = get_personal_model_service(settings.MODULE_NAME)

    # Research profile (used for personalization)
    advisor = get_learning_advisor_service()
    await advisor.initialize()
    profile_obj = await advisor.analyze_user_profile(current_user.id)
    
    # RPJ-specific profile
    profile = {
        "grade": getattr(current_user, "grade", None),
        "research_areas": [getattr(wp, "research_area", None) for wp in (profile_obj.weak_points or [])[:3] 
                          if getattr(wp, "research_area", None)],
        "weak_research_methods": [getattr(wp, "research_method", None) for wp in (profile_obj.weak_points or [])[:5] 
                                 if getattr(wp, "research_method", None)],
        "project_experience": getattr(profile_obj, "project_experience", 0),
        "research_skills": getattr(profile_obj, "research_skills", []),
    }

    conv = await _get_or_create_conversation(db, current_user.id, body.conversation_id)
    trace_id = f"companion:{settings.MODULE_NAME}:{int(current_user.id)}:{int(conv.id)}"

    strict_project = str(os.environ.get("RPJ_REQUIRE_PROJECT_MODEL") or "").strip().lower() in {"1", "true", "yes", "y", "on"}
    resolved = await svc.resolve_model_for_subject(subject=project_type, strict=strict_project)
    model_to_use = resolved["model"]
    warn = resolved.get("warning")
    logger.info(
        "[%s] RPJ chat request project_type=%s mode=%s msg_len=%s msg_preview=%r personal_model_enabled=%s model=%s project_model=%s used_project_model=%s",
        trace_id,
        (project_type or None),
        (body.mode or "chat"),
        len(msg),
        _truncate(msg, 160),
        bool(svc.enabled),
        model_to_use,
        resolved.get("subject_model"),
        bool(resolved.get("used_subject_model")),
    )
    if warn:
        logger.warning("[%s] %s", trace_id, warn)

    if not await _personal_model_should_run(svc, trace_id):
        raise HTTPException(
            status_code=503,
            detail=(
                "Personal model is disabled (or unreachable). Enable it via env (before starting backend):\n"
                "  PERSONAL_MODEL_ENABLED_RPJ=true\n"
                "  PERSONAL_MODEL_API_BASE_RPJ=http://127.0.0.1:8002/v1\n"  # 修改端口为8002
                "  PERSONAL_MODEL_MODEL_RPJ=rpj-dpo\n"
                "Then (re)start vLLM by: ./deploy/scripts/pipeline.sh serve-model --module rpj up\n"
                "Tip: You can also keep PERSONAL_MODEL_AUTO_ENABLE=true (default) to auto-detect /v1/models."
            ),
        )

    # Persist user message
    db.add(
        CompanionMessage(
            conversation_id=int(conv.id),
            role="user",
            content=msg,
            meta={"mode": body.mode, "project_type": project_type},
        )
    )
    await db.flush()

    # Retrieve context (RPJ-only)
    retrieved = await _retrieve_context(db=db, user_id=current_user.id, query=msg, profile=profile, top_k=5)
    retrieval_block = _format_retrieval_block(retrieved)
    try:
        src_counts: Dict[str, int] = {}
        for it in retrieved:
            src_counts[it.source] = src_counts.get(it.source, 0) + 1
        logger.info("[%s] RPJ retrieval done items=%s sources=%s", trace_id, len(retrieved), src_counts)
    except Exception:
        pass

    # Build messages for the model: system + short history + current user
    recent = await _load_recent_messages(db, conv.id, limit=12)
    model_messages: List[Dict[str, str]] = [{"role": "system", "content": _system_prompt_for_mode(mode=body.mode, profile=profile)}]
    if retrieval_block:
        model_messages.append({"role": "system", "content": retrieval_block})
    for m in recent:
        if m.role not in {"user", "assistant"}:
            continue
        model_messages.append({"role": m.role, "content": m.content})

    # Call personal model
    try:
        # Print key runtime config (no secrets).
        logger.info(
            "[%s] RPJ personal model call base=%s model=%s msgs=%s retrieval_items=%s",
            trace_id,
            os.environ.get("PERSONAL_MODEL_API_BASE_RPJ") or "http://127.0.0.1:8002/v1",  # 修改端口为8002
            svc.default_model,
            len(model_messages),
            len(retrieved),
        )
        assistant = await svc.chat(
            messages=model_messages,
            model=model_to_use,
            temperature=0.7,
            max_tokens=1000,  # More tokens for research discussions
            trace_id=trace_id,
            trace={
                "mode": body.mode,
                "conversation_id": int(conv.id),
                "user_id": int(current_user.id),
                "profile": profile,
                "retrieval": [it.model_dump() for it in (retrieved or [])],
                "project_type": (project_type or None),
                "resolved_model": resolved,
            },
        )
    except Exception as e:
        logger.exception("[%s] RPJ personal model chat failed err=%s", trace_id, repr(e))
        raise HTTPException(
            status_code=502,
            detail=(
                "Failed to call personal model (vLLM). "
                "Ensure vLLM is running and reachable at PERSONAL_MODEL_API_BASE_RPJ (port 8002).\n"  # 修改端口为8002
                "Try: curl http://127.0.0.1:8002/v1/models"
            ),
        )

    if not assistant:
        assistant = "我这边暂时没有生成到有效回复。你可以换一种问法，或提供更多研究背景。"

    db.add(
        CompanionMessage(
            conversation_id=int(conv.id),
            role="assistant",
            content=assistant,
            meta={"retrieved_count": len(retrieved), "trace_id": trace_id, "project_type": project_type},
        )
    )

    # Minimal auto-title on first assistant response
    if not conv.title or conv.title == "RPJ研究对话":
        conv.title = (msg[:30] + ("..." if len(msg) > 30 else ""))

    dt_ms = int((time.monotonic() - t0) * 1000)
    logger.info("[%s] RPJ chat ok dt_ms=%s assistant_len=%s", trace_id, dt_ms, len(assistant))
    return CompanionChatResponse(
        conversation_id=int(conv.id),
        assistant_message=assistant,
        retrieved=retrieved,
    )


@router.post("/chat/stream")
async def chat_stream(
    body: CompanionChatRequest,
    project_type: Optional[str] = Query(None, description="项目类型（用于选择 <module>-sft-<project_type>）"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Stream chat response (SSE) for RPJ module.

    Endpoint shape:
    - `POST /api/v1/companion/chat/stream`
    - Response is `text/event-stream` where each message is:
        data: {"type":"delta","content":"..."}
    """
    msg = (body.message or "").strip()
    if not msg:
        raise HTTPException(status_code=400, detail="message is required")

    t0 = time.monotonic()
    svc = get_personal_model_service(settings.MODULE_NAME)

    # Research profile (used for personalization)
    advisor = get_learning_advisor_service()
    await advisor.initialize()
    profile_obj = await advisor.analyze_user_profile(current_user.id)
    
    # RPJ-specific profile
    profile = {
        "grade": getattr(current_user, "grade", None),
        "research_areas": [getattr(wp, "research_area", None) for wp in (profile_obj.weak_points or [])[:3] 
                          if getattr(wp, "research_area", None)],
        "weak_research_methods": [getattr(wp, "research_method", None) for wp in (profile_obj.weak_points or [])[:5] 
                                 if getattr(wp, "research_method", None)],
        "project_experience": getattr(profile_obj, "project_experience", 0),
        "research_skills": getattr(profile_obj, "research_skills", []),
    }

    conv = await _get_or_create_conversation(db, current_user.id, body.conversation_id)
    trace_id = f"companion:{settings.MODULE_NAME}:{int(current_user.id)}:{int(conv.id)}"

    strict_project = str(os.environ.get("RPJ_REQUIRE_PROJECT_MODEL") or "").strip().lower() in {"1", "true", "yes", "y", "on"}
    resolved = await svc.resolve_model_for_subject(subject=project_type, strict=strict_project)
    model_to_use = resolved["model"]
    warn = resolved.get("warning")
    logger.info(
        "[%s] RPJ chat_stream request project_type=%s mode=%s msg_len=%s msg_preview=%r personal_model_enabled=%s model=%s project_model=%s used_project_model=%s",
        trace_id,
        (project_type or None),
        (body.mode or "chat"),
        len(msg),
        _truncate(msg, 160),
        bool(svc.enabled),
        model_to_use,
        resolved.get("subject_model"),
        bool(resolved.get("used_subject_model")),
    )
    if warn:
        logger.warning("[%s] %s", trace_id, warn)

    if not await _personal_model_should_run(svc, trace_id):
        raise HTTPException(
            status_code=503,
            detail=(
                "Personal model is disabled (or unreachable). Enable it via env (before starting backend):\n"
                "  PERSONAL_MODEL_ENABLED_RPJ=true\n"
                "  PERSONAL_MODEL_API_BASE_RPJ=http://127.0.0.1:8002/v1\n"  # 修改端口为8002
                "  PERSONAL_MODEL_MODEL_RPJ=rpj-dpo\n"
                "Then (re)start vLLM by: ./deploy/scripts/pipeline.sh serve-model --module rpj up\n"
                "Tip: You can also keep PERSONAL_MODEL_AUTO_ENABLE=true (default) to auto-detect /v1/models."
            ),
        )

    # Persist user message (committed when FastAPI dependency finalizes)
    db.add(
        CompanionMessage(
            conversation_id=int(conv.id),
            role="user",
            content=msg,
            meta={"mode": body.mode, "project_type": project_type, "stream": True},
        )
    )
    await db.flush()

    # Retrieve context (RPJ-only) — do it before streaming starts.
    retrieved = await _retrieve_context(db=db, user_id=current_user.id, query=msg, profile=profile, top_k=5)
    retrieval_block = _format_retrieval_block(retrieved)
    try:
        src_counts: Dict[str, int] = {}
        for it in retrieved:
            src_counts[it.source] = src_counts.get(it.source, 0) + 1
        logger.info("[%s] RPJ retrieval done items=%s sources=%s", trace_id, len(retrieved), src_counts)
    except Exception:
        pass

    recent = await _load_recent_messages(db, conv.id, limit=12)
    model_messages: List[Dict[str, str]] = [{"role": "system", "content": _system_prompt_for_mode(mode=body.mode, profile=profile)}]
    if retrieval_block:
        model_messages.append({"role": "system", "content": retrieval_block})
    for m in recent:
        if m.role not in {"user", "assistant"}:
            continue
        model_messages.append({"role": m.role, "content": m.content})

    async def _persist_assistant(final_text: str) -> None:
        # Streaming response outlives `get_db()` dependency lifecycle; use a new session.
        async with async_session_maker() as session:
            try:
                res = await session.execute(
                    select(CompanionConversation).where(
                        CompanionConversation.id == int(conv.id),
                        CompanionConversation.user_id == int(current_user.id),
                        CompanionConversation.module == settings.MODULE_NAME,
                    )
                )
                conv2 = res.scalar_one_or_none()
                if not conv2:
                    return
                session.add(
                    CompanionMessage(
                        conversation_id=int(conv2.id),
                        role="assistant",
                        content=final_text,
                        meta={"retrieved_count": len(retrieved), "trace_id": trace_id, "stream": True, "project_type": project_type},
                    )
                )
                if not conv2.title or conv2.title == "RPJ研究对话":
                    conv2.title = (msg[:30] + ("..." if len(msg) > 30 else ""))
                await session.commit()
            except Exception:
                await session.rollback()
                logger.exception("[%s] RPJ failed to persist assistant message (stream)", trace_id)

    async def event_gen():
        yield _sse(
            {
                "type": "meta",
                "conversation_id": int(conv.id),
                "trace_id": trace_id,
                "model": model_to_use,
                "project_type": (project_type or None),
                "project_model": resolved.get("subject_model"),
                "used_project_model": bool(resolved.get("used_subject_model")),
                "warning": warn,
            }
        )

        parts: List[str] = []
        try:
            logger.info(
                "[%s] RPJ personal model stream start base=%s model=%s msgs=%s retrieval_items=%s",
                trace_id,
                os.environ.get("PERSONAL_MODEL_API_BASE_RPJ") or "http://127.0.0.1:8002/v1",  # 修改端口为8002
                model_to_use,
                len(model_messages),
                len(retrieved),
            )
            async for delta in svc.chat_stream(
                messages=model_messages,
                model=model_to_use,
                temperature=0.7,
                max_tokens=1000,
                trace_id=trace_id,
                trace={
                    "mode": body.mode,
                    "conversation_id": int(conv.id),
                    "user_id": int(current_user.id),
                    "profile": profile,
                    "retrieval": [it.model_dump() for it in (retrieved or [])],
                    "project_type": (project_type or None),
                    "resolved_model": resolved,
                },
            ):
                parts.append(delta)
                yield _sse({"type": "delta", "content": delta})
        except Exception as e:
            logger.exception("[%s] RPJ personal model stream failed err=%s", trace_id, repr(e))
            yield _sse(
                {
                    "type": "error",
                    "message": (
                        "Failed to call personal model (vLLM). "
                        "Ensure vLLM is running and reachable at PERSONAL_MODEL_API_BASE_RPJ (port 8002).\n"
                        "Try: curl http://127.0.0.1:8002/v1/models"
                    ),
                }
            )
            return

        assistant = ("".join(parts) or "").strip() or "我这边暂时没有生成到有效回复。你可以换一种问法，或提供更多研究背景。"
        await _persist_assistant(assistant)

        dt_ms = int((time.monotonic() - t0) * 1000)
        logger.info("[%s] RPJ chat_stream done dt_ms=%s assistant_len=%s", trace_id, dt_ms, len(assistant))
        yield _sse({"type": "done", "assistant_message": assistant, "retrieved": [it.model_dump() for it in (retrieved or [])]})

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@router.get("/conversations")
async def list_conversations(
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(CompanionConversation)
        .where(CompanionConversation.user_id == int(current_user.id), CompanionConversation.module == settings.MODULE_NAME)
        .order_by(CompanionConversation.updated_at.desc())
        .limit(int(limit))
    )
    items = []
    for c in res.scalars().all():
        items.append(
            {
                "id": int(c.id),
                "title": c.title,
                "module": c.module,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            }
        )
    return {"items": items}


@router.get("/conversations/{conversation_id}")
async def get_conversation_messages(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    res = await db.execute(
        select(CompanionConversation).where(
            CompanionConversation.id == int(conversation_id),
            CompanionConversation.user_id == int(current_user.id),
            CompanionConversation.module == settings.MODULE_NAME,
        )
    )
    conv = res.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    msgs = await _load_recent_messages(db, conv.id, limit=200)
    return {
        "conversation": {
            "id": int(conv.id),
            "title": conv.title,
            "module": conv.module,
        },
        "messages": [
            {
                "id": int(m.id),
                "role": m.role,
                "content": m.content,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in msgs
        ],
    }


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Delete one RPJ conversation (and its messages) for the current user.
    """
    res = await db.execute(
        select(CompanionConversation).where(
            CompanionConversation.id == int(conversation_id),
            CompanionConversation.user_id == int(current_user.id),
            CompanionConversation.module == settings.MODULE_NAME,
        )
    )
    conv = res.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Delete messages first (safe across SQLite FK settings; avoids loading ORM graph).
    await db.execute(delete(CompanionMessage).where(CompanionMessage.conversation_id == int(conv.id)))
    await db.delete(conv)
    logger.info(
        "[RPJ companion] deleted conversation id=%s user_id=%s module=%s",
        int(conv.id),
        int(current_user.id),
        settings.MODULE_NAME,
    )
    return {"ok": True, "conversation_id": int(conversation_id)}
