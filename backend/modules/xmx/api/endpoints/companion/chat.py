"""
Tony "小书童" / Companion Chat API

Goals (Tony-first, other modules will stub):
- Provide a chat mode for the user to talk to their personal model (vLLM OpenAI-compatible).
- Inject personalization context (student profile / weak points) and retrieval context
  (hybrid search + GraphRAG expansion) into the prompt.
- Persist conversation history in DB for continuity ("digital twin" memory foundation).

This is a minimal, production-style skeleton inspired by "personal agent" open source projects
(e.g. SecondMe): separate memory (DB), retrieval, and model invocation layers.
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
from backend.modules.tony.api.deps import get_current_user, get_db
from backend.modules.tony.config import settings

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
    # 预留：让前端把“学习建议/复习”等入口意图传入，帮助书童调整输出结构
    mode: str = Field("chat", description="chat|learning_advice|review")


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
    In classroom deployments, students often forget to export PERSONAL_MODEL_ENABLED_TONY
    before starting the backend. To keep the demo working, we try a best-effort auto-enable:
    - if env PERSONAL_MODEL_AUTO_ENABLE is truthy (default true)
    - and /v1/models is reachable
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
        logger.warning("[%s] personal model auto-enabled (env flag missing): set PERSONAL_MODEL_ENABLED_TONY=true to suppress", trace_id)
        return True
    except Exception as e:
        logger.warning("[%s] personal model disabled and /v1/models unreachable: %r", trace_id, e)
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

    conv = CompanionConversation(user_id=int(user_id), module=settings.MODULE_NAME, title="小书童对话")
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
    A warm, structured system prompt. Keep it short so the model has room for context.
    """
    grade = profile.get("grade") or "未知"
    weak_kps = profile.get("weak_knowledge_points") or []
    weak_subj = profile.get("weak_subjects") or []

    base = (
        "你是用户专属的学习小书童（数字孪生式学习伙伴）。\n"
        "你的目标：在保证知识正确的前提下，给出针对性学习指导，并提供情绪价值（温暖、耐心、鼓励）。\n"
        "回答风格：先结论，再分点解释，最后给可执行的练习/复盘建议。\n"
        "如果你不确定，请明确说明不确定并给出验证思路。\n"
        "\n"
        f"学生画像：年级={grade}；薄弱学科={', '.join(weak_subj) if weak_subj else '暂无'}；"
        f"薄弱知识点={', '.join(weak_kps) if weak_kps else '暂无'}。\n"
    )

    mode = (mode or "chat").strip().lower()
    if mode == "learning_advice":
        return base + "\n当前任务：生成个性化学习建议/学习计划（要具体、可执行、可衡量）。\n"
    if mode == "review":
        return base + "\n当前任务：进行错题/知识点复习辅导（提炼要点→小测→纠错→间隔复习安排）。\n"
    return base + "\n当前任务：与学生对话，回答问题并引导学习。\n"


def _format_retrieval_block(items: List[RetrievedItem]) -> str:
    if not items:
        return ""
    lines = ["以下是与问题相关的学习材料/错题记录（可能不完全准确，请你综合判断）："]
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
    Retrieval strategy (runtime):
    1) Hybrid search (FAISS+BM25) over question corpus for tony module
    2) Optional GraphRAG expansion by weak knowledge points (if enabled)
    """
    out: List[RetrievedItem] = []

    # Ensure hybrid index is initialized (best-effort; it may already be done at app startup).
    try:
        hs = get_hybrid_search_service()
        await hs.initialize(
            vector_store_path=settings.module_vector_path,
            bm25_index_path=settings.module_bm25_path,
        )
    except Exception as e:
        logger.debug(f"hybrid search init skipped: {e}")

    # Try embedding->vector hybrid search; fallback to BM25 if embedding is unavailable.
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
        logger.debug(f"hybrid search failed: {e}")

    # GraphRAG expansion: add a few question contents by weak knowledge points.
    try:
        if getattr(settings, "GRAPHRAG_ENABLED", False):
            graphrag = get_graphrag_service()
            await graphrag.initialize(graph_path=settings.module_graphrag_graph_path)
            weak_kps = profile.get("weak_knowledge_points", []) or []
            subject = (profile.get("weak_subjects") or ["other"])[0]
            qids = graphrag.find_questions_by_knowledge_points(
                subject=subject,
                knowledge_points=weak_kps,
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
                            meta={"knowledge_points": q.knowledge_points or [], "subject": getattr(q.subject, "value", None)},
                        )
                    )
    except Exception as e:
        logger.debug(f"graphrag expansion skipped: {e}")

    return out[: max(8, int(top_k))]


@router.post("/chat", response_model=CompanionChatResponse)
async def chat(
    body: CompanionChatRequest,
    subject: Optional[str] = Query(None, description="学科（用于选择 <module>-sft-<subject>）"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Chat with the user's "小书童".

    Backend will:
    - build student profile (weak points, mastery)
    - retrieve context (hybrid search + optional GraphRAG)
    - call the personal model (OpenAI-compatible vLLM)
    - store conversation history
    """
    msg = (body.message or "").strip()
    if not msg:
        raise HTTPException(status_code=400, detail="message is required")

    t0 = time.monotonic()
    svc = get_personal_model_service(settings.MODULE_NAME)

    # Student profile (used for personalization)
    advisor = get_learning_advisor_service()
    await advisor.initialize()
    profile_obj = await advisor.analyze_user_profile(current_user.id)
    profile = {
        "grade": getattr(current_user, "grade", None),
        "weak_subjects": [wp.subject for wp in (profile_obj.weak_points or [])[:3] if getattr(wp, "subject", None)],
        "weak_knowledge_points": [wp.knowledge_point for wp in (profile_obj.weak_points or [])[:5] if getattr(wp, "knowledge_point", None)],
        "overall_accuracy": profile_obj.overall_accuracy,
        "total_questions": profile_obj.total_questions,
    }

    conv = await _get_or_create_conversation(db, current_user.id, body.conversation_id)
    trace_id = f"companion:{settings.MODULE_NAME}:{int(current_user.id)}:{int(conv.id)}"

    strict_subject = str(os.environ.get("COMPANION_REQUIRE_SUBJECT_MODEL") or "").strip().lower() in {"1", "true", "yes", "y", "on"}
    resolved = await svc.resolve_model_for_subject(subject=subject, strict=strict_subject)
    model_to_use = resolved["model"]
    warn = resolved.get("warning")
    logger.info(
        "[%s] chat request subject=%s mode=%s msg_len=%s msg_preview=%r personal_model_enabled=%s model=%s subject_model=%s used_subject_model=%s",
        trace_id,
        (subject or None),
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
                "  PERSONAL_MODEL_ENABLED_XMX=true\n"
                "  PERSONAL_MODEL_API_BASE_XMX=http://127.0.0.1:8003/v1\n"
                "  PERSONAL_MODEL_MODEL_XMX=xmx-dpo\n"
                "Then (re)start vLLM by: ./deploy/scripts/pipeline.sh serve-model --module xmx up\n"
                "Tip: You can also keep PERSONAL_MODEL_AUTO_ENABLE=true (default) to auto-detect /v1/models."
            ),
        )

    # Persist user message
    db.add(
        CompanionMessage(
            conversation_id=int(conv.id),
            role="user",
            content=msg,
            meta={"mode": body.mode},
        )
    )
    await db.flush()

    # Retrieve context (Tony-only)
    retrieved = await _retrieve_context(db=db, user_id=current_user.id, query=msg, profile=profile, top_k=5)
    retrieval_block = _format_retrieval_block(retrieved)
    try:
        src_counts: Dict[str, int] = {}
        for it in retrieved:
            src_counts[it.source] = src_counts.get(it.source, 0) + 1
        logger.info("[%s] retrieval done items=%s sources=%s", trace_id, len(retrieved), src_counts)
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
            "[%s] personal model call base=%s model=%s msgs=%s retrieval_items=%s",
            trace_id,
            os.environ.get("PERSONAL_MODEL_API_BASE_TONY") or "http://127.0.0.1:8001/v1",
            svc.default_model,
            len(model_messages),
            len(retrieved),
        )
        assistant = await svc.chat(
            messages=model_messages,
            model=model_to_use,
            temperature=0.7,
            max_tokens=800,
            trace_id=trace_id,
            trace={
                "mode": body.mode,
                "conversation_id": int(conv.id),
                "user_id": int(current_user.id),
                "profile": profile,
                "retrieval": [it.model_dump() for it in (retrieved or [])],
                "subject": (subject or None),
                "resolved_model": resolved,
            },
        )
    except Exception as e:
        logger.exception("[%s] personal model chat failed err=%s", trace_id, repr(e))
        raise HTTPException(
            status_code=502,
            detail=(
                "Failed to call personal model (vLLM). "
                "Ensure vLLM is running and reachable at PERSONAL_MODEL_API_BASE.\n"
                "Try: curl http://127.0.0.1:8001/v1/models"
            ),
        )

    if not assistant:
        assistant = "我这边暂时没有生成到有效回复。你可以换一种问法，或稍后再试。"

    db.add(
        CompanionMessage(
            conversation_id=int(conv.id),
            role="assistant",
            content=assistant,
            meta={"retrieved_count": len(retrieved), "trace_id": trace_id},
        )
    )

    # Minimal auto-title on first assistant response
    if not conv.title or conv.title == "小书童对话":
        conv.title = (msg[:24] + ("..." if len(msg) > 24 else ""))

    dt_ms = int((time.monotonic() - t0) * 1000)
    logger.info("[%s] chat ok dt_ms=%s assistant_len=%s", trace_id, dt_ms, len(assistant))
    return CompanionChatResponse(
        conversation_id=int(conv.id),
        assistant_message=assistant,
        retrieved=retrieved,
    )


@router.post("/chat/stream")
async def chat_stream(
    body: CompanionChatRequest,
    subject: Optional[str] = Query(None, description="学科（用于选择 <module>-sft-<subject>）"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Stream chat response (SSE).

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

    # Student profile (used for personalization)
    advisor = get_learning_advisor_service()
    await advisor.initialize()
    profile_obj = await advisor.analyze_user_profile(current_user.id)
    profile = {
        "grade": getattr(current_user, "grade", None),
        "weak_subjects": [wp.subject for wp in (profile_obj.weak_points or [])[:3] if getattr(wp, "subject", None)],
        "weak_knowledge_points": [wp.knowledge_point for wp in (profile_obj.weak_points or [])[:5] if getattr(wp, "knowledge_point", None)],
        "overall_accuracy": profile_obj.overall_accuracy,
        "total_questions": profile_obj.total_questions,
    }

    conv = await _get_or_create_conversation(db, current_user.id, body.conversation_id)
    trace_id = f"companion:{settings.MODULE_NAME}:{int(current_user.id)}:{int(conv.id)}"

    strict_subject = str(os.environ.get("COMPANION_REQUIRE_SUBJECT_MODEL") or "").strip().lower() in {"1", "true", "yes", "y", "on"}
    resolved = await svc.resolve_model_for_subject(subject=subject, strict=strict_subject)
    model_to_use = resolved["model"]
    warn = resolved.get("warning")
    logger.info(
        "[%s] chat_stream request subject=%s mode=%s msg_len=%s msg_preview=%r personal_model_enabled=%s model=%s subject_model=%s used_subject_model=%s",
        trace_id,
        (subject or None),
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
                "  PERSONAL_MODEL_ENABLED_TONY=true\n"
                "  PERSONAL_MODEL_API_BASE_TONY=http://127.0.0.1:8001/v1\n"
                "  PERSONAL_MODEL_MODEL_TONY=tony-dpo\n"
                "Then (re)start vLLM by: ./deploy/scripts/pipeline.sh serve-model --module tony up\n"
                "Tip: You can also keep PERSONAL_MODEL_AUTO_ENABLE=true (default) to auto-detect /v1/models."
            ),
        )

    # Persist user message (committed when FastAPI dependency finalizes)
    db.add(
        CompanionMessage(
            conversation_id=int(conv.id),
            role="user",
            content=msg,
            meta={"mode": body.mode, "stream": True},
        )
    )
    await db.flush()

    # Retrieve context (Tony-only) — do it before streaming starts.
    retrieved = await _retrieve_context(db=db, user_id=current_user.id, query=msg, profile=profile, top_k=5)
    retrieval_block = _format_retrieval_block(retrieved)
    try:
        src_counts: Dict[str, int] = {}
        for it in retrieved:
            src_counts[it.source] = src_counts.get(it.source, 0) + 1
        logger.info("[%s] retrieval done items=%s sources=%s", trace_id, len(retrieved), src_counts)
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
                        meta={"retrieved_count": len(retrieved), "trace_id": trace_id, "stream": True},
                    )
                )
                if not conv2.title or conv2.title == "小书童对话":
                    conv2.title = (msg[:24] + ("..." if len(msg) > 24 else ""))
                await session.commit()
            except Exception:
                await session.rollback()
                logger.exception("[%s] failed to persist assistant message (stream)", trace_id)

    async def event_gen():
        yield _sse(
            {
                "type": "meta",
                "conversation_id": int(conv.id),
                "trace_id": trace_id,
                "model": model_to_use,
                "subject": (subject or None),
                "subject_model": resolved.get("subject_model"),
                "used_subject_model": bool(resolved.get("used_subject_model")),
                "warning": warn,
            }
        )

        parts: List[str] = []
        try:
            logger.info(
                "[%s] personal model stream start base=%s model=%s msgs=%s retrieval_items=%s",
                trace_id,
                os.environ.get("PERSONAL_MODEL_API_BASE_TONY") or "http://127.0.0.1:8001/v1",
                model_to_use,
                len(model_messages),
                len(retrieved),
            )
            async for delta in svc.chat_stream(
                messages=model_messages,
                model=model_to_use,
                temperature=0.7,
                max_tokens=800,
                trace_id=trace_id,
                trace={
                    "mode": body.mode,
                    "conversation_id": int(conv.id),
                    "user_id": int(current_user.id),
                    "profile": profile,
                    "retrieval": [it.model_dump() for it in (retrieved or [])],
                    "subject": (subject or None),
                    "resolved_model": resolved,
                },
            ):
                parts.append(delta)
                yield _sse({"type": "delta", "content": delta})
        except Exception as e:
            logger.exception("[%s] personal model stream failed err=%s", trace_id, repr(e))
            yield _sse(
                {
                    "type": "error",
                    "message": (
                        "Failed to call personal model (vLLM). "
                        "Ensure vLLM is running and reachable at PERSONAL_MODEL_API_BASE.\n"
                        "Try: curl http://127.0.0.1:8001/v1/models"
                    ),
                }
            )
            return

        assistant = ("".join(parts) or "").strip() or "我这边暂时没有生成到有效回复。你可以换一种问法，或稍后再试。"
        await _persist_assistant(assistant)

        dt_ms = int((time.monotonic() - t0) * 1000)
        logger.info("[%s] chat_stream done dt_ms=%s assistant_len=%s", trace_id, dt_ms, len(assistant))
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
    Delete one conversation (and its messages) for the current user.
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
        "[companion] deleted conversation id=%s user_id=%s module=%s",
        int(conv.id),
        int(current_user.id),
        settings.MODULE_NAME,
    )
    return {"ok": True, "conversation_id": int(conversation_id)}

