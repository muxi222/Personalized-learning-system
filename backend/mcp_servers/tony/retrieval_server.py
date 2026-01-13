"""
TONY Retrieval MCP Server

Phase 1 (roadmap): retrieval-mcp

Goal:
- Provide a **stable tool API** for retrieval that LLM/agents can call via MCP.
- Hide internal implementation details (FAISS/BM25/GraphRAG/DB) behind tools.

How it maps to existing code:
- Hybrid retrieval: backend.core.services.hybrid_search_service.HybridSearchService
- Embeddings: backend.core.services.embedding_service.get_embedding_service
- Graph expansion (optional): backend.core.services.graphrag_service.GraphRAGService
- Ground-truth objects: backend.core.db.models.Question (SQL)

Run:
  python -m backend.mcp_servers.tony.retrieval_server

Client transport:
  Streamable HTTP on http://127.0.0.1:7010/mcp (default)
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from mcp.server.fastmcp import FastMCP

from backend.modules.tony.config import settings


mcp = FastMCP(
    name="learning-assistant-tony-retrieval",
    instructions=(
        "Retrieval tools for the TONY module. "
        "Use these tools to search similar questions and fetch question details."
    ),
    host="127.0.0.1",
    port=7010,
    streamable_http_path="/mcp",
    json_response=True,
    log_level="INFO",
)


async def _ensure_indexes_initialized() -> None:
    # TONY uses module-specific paths under ./data/faiss/tony and ./data/bm25/tony
    from backend.core.services.hybrid_search_service import get_hybrid_search_service

    svc = get_hybrid_search_service()
    await svc.initialize(
        vector_store_path=settings.module_vector_path,
        bm25_index_path=settings.module_bm25_path,
    )


async def _search_hybrid(
    *,
    query_text: str,
    user_id: int,
    subject: Optional[str],
    top_k: int,
    vector_weight: Optional[float],
    bm25_weight: Optional[float],
    similarity_threshold: Optional[float],
) -> List[Dict[str, Any]]:
    from backend.core.services.embedding_service import get_embedding_service
    from backend.core.services.hybrid_search_service import get_hybrid_search_service

    await _ensure_indexes_initialized()

    embedding_svc = get_embedding_service()
    query_embedding = await embedding_svc.embed_text(query_text)

    # Fallback to BM25-only if embeddings are unavailable (offline / misconfig).
    search_svc = get_hybrid_search_service()
    filter_metadata: Dict[str, Any] = {"user_id": user_id}
    if subject:
        filter_metadata["subject"] = subject

    if query_embedding:
        results = await search_svc.hybrid_search(
            query_text=query_text,
            query_embedding=query_embedding,
            top_k=top_k,
            vector_weight=vector_weight,
            bm25_weight=bm25_weight,
            similarity_threshold=similarity_threshold,
            filter_metadata=filter_metadata,
        )
    else:
        results = await search_svc.search_bm25(
            query_text=query_text,
            top_k=top_k,
            filter_metadata=filter_metadata,
        )

    out: List[Dict[str, Any]] = []
    for r in results:
        # doc_id is stored as str, but our Question PK is int
        try:
            qid = int(r.doc_id)
        except Exception:
            # Keep doc_id for debugging; skip invalid ids
            continue
        out.append(
            {
                "question_id": qid,
                "score": float(r.score),
                "source": r.source,
                "metadata": r.metadata or {},
                "document": r.document or "",
            }
        )
    return out


async def _expand_with_graphrag(
    *,
    subject: str,
    knowledge_points: List[str],
    exclude_question_ids: List[int],
    top_k: int,
) -> List[int]:
    # Feature-gated by settings.GRAPHRAG_ENABLED.
    if not getattr(settings, "GRAPHRAG_ENABLED", False):
        return []

    from backend.core.services.graphrag_service import get_graphrag_service

    graphrag = get_graphrag_service()
    ok = await graphrag.initialize(graph_path=settings.module_graphrag_graph_path)
    if not ok:
        return []

    return graphrag.find_questions_by_knowledge_points(
        subject=subject or "other",
        knowledge_points=list(knowledge_points or []),
        top_k=top_k,
        exclude_question_ids=set(exclude_question_ids or []),
    )


async def _expand_with_graphrag_tags(
    *,
    tags: List[str],
    exclude_question_ids: List[int],
    top_k: int,
) -> List[int]:
    if not getattr(settings, "GRAPHRAG_ENABLED", False):
        return []
    from backend.core.services.graphrag_service import get_graphrag_service

    graphrag = get_graphrag_service()
    ok = await graphrag.initialize(graph_path=settings.module_graphrag_graph_path)
    if not ok:
        return []
    return graphrag.find_questions_by_tags(
        tags=list(tags or []),
        top_k=top_k,
        exclude_question_ids=set(exclude_question_ids or []),
    )


@mcp.tool()
async def search_questions(
    query_text: str,
    user_id: int,
    subject: Optional[str] = None,
    knowledge_points: Optional[List[str]] = None,
    tags: Optional[List[str]] = None,
    top_k: int = 5,
    exclude_question_ids: Optional[List[int]] = None,
    include_graphrag: bool = False,
    graphrag_k: int = 20,
    vector_weight: Optional[float] = None,
    bm25_weight: Optional[float] = None,
    similarity_threshold: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Search similar questions for a user (TONY module).

    Returns:
    - results: list of {question_id, score, source, metadata, document}
    - debug: timings and flags (useful for evaluation)
    """
    t0 = time.perf_counter()
    exclude = exclude_question_ids or []
    try:
        base = await _search_hybrid(
            query_text=query_text,
            user_id=user_id,
            subject=subject,
            top_k=max(top_k, 1),
            vector_weight=vector_weight,
            bm25_weight=bm25_weight,
            similarity_threshold=similarity_threshold,
        )
        base_ids = [r["question_id"] for r in base]
        extra_ids: List[int] = []
        if include_graphrag:
            exclude_all = list(set(base_ids + exclude))

            # Graph expansion by knowledge points (explicit schema param).
            kp_ids: List[int] = []
            if knowledge_points:
                kp_ids = await _expand_with_graphrag(
                    subject=subject or "other",
                    knowledge_points=list(knowledge_points or []),
                    exclude_question_ids=exclude_all,
                    top_k=max(graphrag_k, top_k),
                )

            # Graph expansion by tags (explicit schema param).
            tag_ids: List[int] = []
            if tags:
                tag_ids = await _expand_with_graphrag_tags(
                    tags=list(tags or []),
                    exclude_question_ids=exclude_all + kp_ids,
                    top_k=max(graphrag_k, top_k),
                )

            extra_ids = list(kp_ids) + [x for x in tag_ids if x not in set(kp_ids)]
        # Merge: keep hybrid results first, then graph-expanded ids (score unknown)
        merged = base[:]
        seen = set(exclude + base_ids)
        for qid in extra_ids:
            if qid in seen:
                continue
            merged.append(
                {
                    "question_id": int(qid),
                    "score": 0.0,
                    "source": "graphrag",
                    "metadata": {},
                    "document": "",
                }
            )
            seen.add(qid)
        merged = [r for r in merged if r["question_id"] not in set(exclude)]
        merged = merged[:top_k]

        return {
            "results": merged,
            "debug": {
                "module": "tony",
                "graphrag_enabled": bool(getattr(settings, "GRAPHRAG_ENABLED", False)),
                "include_graphrag": bool(include_graphrag),
                "knowledge_points_n": len(list(knowledge_points or [])),
                "tags_n": len(list(tags or [])),
                "t_total_ms": round((time.perf_counter() - t0) * 1000.0, 3),
            },
        }
    except Exception as e:
        return {
            "results": [],
            "error": str(e),
            "debug": {
                "module": "tony",
                "t_total_ms": round((time.perf_counter() - t0) * 1000.0, 3),
            },
        }


@mcp.tool()
async def get_questions(
    question_ids: List[int],
    user_id: int,
) -> List[Dict[str, Any]]:
    """
    Fetch question details from SQL for the given IDs (scoped by user_id).

    This maps to: backend.core.db.models.Question + backend.core.crud.crud_question.get_question
    """
    from backend.core.db.session import async_session_maker
    from backend.core.crud.crud_question import get_question

    ids = [int(x) for x in (question_ids or []) if isinstance(x, (int, str))]
    if not ids:
        return []

    out: List[Dict[str, Any]] = []
    async with async_session_maker() as session:
        for qid in ids:
            q = await get_question(session, qid, user_id)
            if not q:
                continue
            out.append(
                {
                    "id": q.id,
                    "content": q.content,
                    "subject": q.subject.value if q.subject else "other",
                    "difficulty": q.difficulty.value if q.difficulty else "medium",
                    "correct_answer": q.correct_answer,
                    "knowledge_points": q.knowledge_points or [],
                    "chapter": q.chapter,
                }
            )
    return out


@mcp.tool()
async def get_task(task_id: str) -> Dict[str, Any]:
    """
    Phase 2 (ops-mcp) starter: query task status by task_id.

    Maps to:
    - backend.core.db.models.AgentTask
    - backend.core.crud.crud_task.get_task_by_task_id
    """
    from backend.core.db.session import async_session_maker
    from backend.core.crud.crud_task import get_task_by_task_id

    async with async_session_maker() as session:
        task = await get_task_by_task_id(session, task_id)
        if not task:
            return {"error": "Task not found", "task_id": task_id}
        result = task.result if isinstance(task.result, dict) else task.result
        return {
            "task_id": task.task_id,
            "status": task.status.value if getattr(task, "status", None) else None,
            "progress": float(task.progress or 0.0),
            "current_step": task.current_step,
            "error_message": task.error_message,
            "result": result,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        }


@mcp.tool()
async def health() -> Dict[str, Any]:
    """Basic health + index stats for debugging/deployment checks."""
    from backend.core.services.hybrid_search_service import get_hybrid_search_service

    await _ensure_indexes_initialized()
    svc = get_hybrid_search_service()
    return {
        "module": "tony",
        "vector_store_path": settings.module_vector_path,
        "bm25_index_path": settings.module_bm25_path,
        "doc_count": int(svc.count),
        "graphrag_enabled": bool(getattr(settings, "GRAPHRAG_ENABLED", False)),
        "graphrag_graph_path": settings.module_graphrag_graph_path,
    }


def main() -> None:
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()

