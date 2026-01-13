"""
Retrieval hit-rate evaluator for Tony.

Metrics:
- hit@k: whether at least one relevant question is returned in top-k.

Two modes:
1) Manual labels (preferred):
   --labels data/training/tony/eval/retrieval_labels.jsonl
   Each JSONL row: {"query_question_id": 123, "relevant_question_ids": [45,67]}

2) Weak supervision fallback (no labels):
   For each sampled question, define relevant set as other questions sharing >=1 knowledge_point.

Retrieval backend:
- Default: local hybrid search (same as runtime) to avoid requiring MCP server.
- Optional: --mcp-url http://127.0.0.1:7010/mcp to call MCP tool (measures tool path).
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import select

from backend.core.db.models import Question
from backend.core.db.session import async_session_maker


async def _load_questions(*, max_n: int) -> List[Question]:
    async with async_session_maker() as session:
        rows = (
            await session.execute(
                select(Question).order_by(Question.created_at.desc()).limit(max_n)
            )
        ).scalars().all()
        return list(rows)


def _weak_relevant_set(q: Question, all_q: List[Question]) -> Set[int]:
    kps = set((q.knowledge_points or []) or [])
    if not kps:
        return set()
    rel: Set[int] = set()
    for other in all_q:
        if other.id == q.id:
            continue
        okps = set((other.knowledge_points or []) or [])
        if kps.intersection(okps):
            rel.add(int(other.id))
    return rel


async def _retrieve_local(
    *,
    query_text: str,
    user_id: int,
    subject: Optional[str],
    k: int,
    exclude_ids: List[int],
) -> List[int]:
    from backend.core.services.embedding_service import get_embedding_service
    from backend.core.services.hybrid_search_service import get_hybrid_search_service
    from backend.modules.tony.config import settings

    svc = get_hybrid_search_service()
    await svc.initialize(vector_store_path=settings.module_vector_path, bm25_index_path=settings.module_bm25_path)

    emb = await get_embedding_service().embed_text(query_text)
    filt: Dict[str, Any] = {"user_id": user_id}
    if subject:
        filt["subject"] = subject

    if emb:
        res = await svc.hybrid_search(query_text=query_text, query_embedding=emb, top_k=k + len(exclude_ids), filter_metadata=filt)
    else:
        res = await svc.search_bm25(query_text=query_text, top_k=k + len(exclude_ids), filter_metadata=filt)

    out: List[int] = []
    seen = set(exclude_ids or [])
    for r in res:
        try:
            qid = int(r.doc_id)
        except Exception:
            continue
        if qid in seen:
            continue
        out.append(qid)
        seen.add(qid)
        if len(out) >= k:
            break
    return out


async def _retrieve_mcp(
    *,
    mcp_url: str,
    query_text: str,
    user_id: int,
    subject: Optional[str],
    k: int,
    exclude_ids: List[int],
) -> List[int]:
    from backend.core.mcp.retrieval_client import RetrievalMcpClient

    client = RetrievalMcpClient(url=mcp_url)
    data = await client.search_questions(
        query_text=query_text,
        user_id=user_id,
        subject=subject,
        top_k=k,
        exclude_question_ids=exclude_ids,
        telemetry={"module": "tony", "subject": subject, "user_id": user_id, "payload": {"eval": True}},
    )
    results = data.get("results") if isinstance(data, dict) else []
    out: List[int] = []
    for r in (results or []):
        if "question_id" in r:
            out.append(int(r["question_id"]))
    return out[:k]


def _load_labels(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


async def _amain(args: argparse.Namespace) -> None:
    # NOTE: This is a teaching repo; we assume DATABASE_URL points to the intended sqlite DB.
    all_q = await _load_questions(max_n=max(args.max_questions, 200))
    if not all_q:
        print(json.dumps({"error": "no questions found"}, ensure_ascii=False))
        return

    # Pick user_id from DB rows (weak evaluator needs user scope; fallback to 1).
    # In a multi-user DB, you can pass --user-id explicitly.
    user_id = int(args.user_id or (all_q[0].user_id if getattr(all_q[0], "user_id", None) else 1))

    cases: List[Tuple[int, Set[int], str, Optional[str]]] = []
    if args.labels:
        labels = _load_labels(args.labels)
        # Build a lookup for question content
        q_by_id = {int(q.id): q for q in all_q}
        for row in labels:
            qid = int(row["query_question_id"])
            rel = set(int(x) for x in (row.get("relevant_question_ids") or []))
            q = q_by_id.get(qid)
            if not q:
                continue
            cases.append((qid, rel, q.content, q.subject.value if q.subject else None))
    else:
        # weak supervision
        sampled = all_q[:]
        random.shuffle(sampled)
        sampled = sampled[: int(args.max_questions)]
        for q in sampled:
            rel = _weak_relevant_set(q, all_q)
            if not rel:
                continue
            cases.append((int(q.id), rel, q.content, q.subject.value if q.subject else None))

    if not cases:
        print(json.dumps({"error": "no evaluation cases built"}, ensure_ascii=False))
        return

    k = int(args.k)
    hits = 0
    total = 0

    for qid, rel, text, subj in cases:
        exclude = [qid]
        if args.mcp_url:
            got = await _retrieve_mcp(
                mcp_url=args.mcp_url,
                query_text=text,
                user_id=user_id,
                subject=subj,
                k=k,
                exclude_ids=exclude,
            )
        else:
            got = await _retrieve_local(
                query_text=text,
                user_id=user_id,
                subject=subj,
                k=k,
                exclude_ids=exclude,
            )
        total += 1
        if any((gid in rel) for gid in got):
            hits += 1

    out = {
        "module": "tony",
        "mode": "manual_labels" if args.labels else "weak_supervision",
        "k": k,
        "cases": total,
        "hit_at_k": (hits / total) if total else None,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--k", type=int, default=5)
    p.add_argument("--max-questions", type=int, default=200)
    p.add_argument("--labels", type=str, default=None)
    p.add_argument("--mcp-url", type=str, default=None)
    p.add_argument("--user-id", type=int, default=None)
    args = p.parse_args()

    import anyio

    anyio.run(lambda: _amain(args))


if __name__ == "__main__":
    main()

