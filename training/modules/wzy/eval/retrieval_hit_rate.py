"""
Retrieval hit-rate evaluator for Wzy.

Metrics:
- hit@k: whether at least one relevant question is returned in top-k.
 - precision@k / recall@k: classic IR "准/召" metrics.
 - mrr@k: reciprocal rank of first relevant hit.
 - ndcg@k: ranking quality (binary relevance).
 - map@k: mean average precision.

Two modes:
1) Manual labels (preferred):
   --labels data/training/wzy/eval/retrieval_labels.jsonl
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
import os
import random
import math
import re
import sys
from dataclasses import dataclass
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple, Protocol, runtime_checkable
import importlib.util

# Allow running as a file script from repo root (or any cwd) without installing the package.
# Example: python training/modules/wzy/eval/retrieval_hit_rate.py --k 5
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "../../../../"))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

_HAVE_SQLALCHEMY = False
_SQLALCHEMY_IMPORT_ERROR: Optional[str] = None
try:
    from sqlalchemy import select  # type: ignore
    from backend.core.db.models import Question  # type: ignore
    from backend.core.db.session import async_session_maker  # type: ignore

    _HAVE_SQLALCHEMY = True
except Exception as e:  # pragma: no cover
    _SQLALCHEMY_IMPORT_ERROR = str(e)
    _HAVE_SQLALCHEMY = False


@runtime_checkable
class _QuestionLike(Protocol):
    id: int
    user_id: int
    content: str
    knowledge_points: Any
    subject: Any
    created_at: Any


@dataclass
class _QRow:
    id: int
    user_id: int
    content: str
    knowledge_points: List[str]
    subject: Optional[str]
    created_at: Optional[datetime]


def _subject_value(q: _QuestionLike) -> Optional[str]:
    s = getattr(q, "subject", None)
    if s is None:
        return None
    v = getattr(s, "value", None)
    if isinstance(v, str) and v:
        return v
    if isinstance(s, str) and s:
        return s
    return str(s) if s is not None else None


def _kps_list(q: _QuestionLike) -> List[str]:
    v = getattr(q, "knowledge_points", None)
    if isinstance(v, list):
        return [str(x) for x in v if str(x)]
    return []


def _sqlite_path_from_database_url(database_url: str) -> str:
    s = (database_url or "").strip()
    if not s:
        return os.path.abspath(os.path.join(_REPO_ROOT, "data/sqlite/app.db"))
    if s.startswith("sqlite+aiosqlite:"):
        s = "sqlite:" + s[len("sqlite+aiosqlite:") :]
    if not s.startswith("sqlite:"):
        return os.path.abspath(os.path.join(_REPO_ROOT, s))
    if "///" in s:
        path = s.split("///", 1)[1]
    else:
        path = s.split("sqlite:", 1)[1]
    path = path.strip()
    if os.path.isabs(path):
        return path
    return os.path.abspath(os.path.join(_REPO_ROOT, path))


def _tokenize(text: str) -> List[str]:
    """
    Lightweight tokenizer (Chinese char + alnum word), matching the spirit of HybridSearchService.
    Pure-stdlib fallback for evaluation environments without faiss/rank_bm25.
    """
    if not isinstance(text, str):
        return []
    t = text.strip().lower()
    if not t:
        return []
    segments = re.findall(r"[\u4e00-\u9fff]+|[a-zA-Z0-9]+", t)
    tokens: List[str] = []
    for seg in segments:
        if re.match(r"[\u4e00-\u9fff]", seg):
            tokens.extend(list(seg))
        else:
            tokens.append(seg)
    return tokens


def _precision_at_k(got: List[int], rel: Set[int], k: int) -> Optional[float]:
    if k <= 0:
        return None
    hits = sum(1 for x in got[:k] if x in rel)
    return float(hits) / float(k)


def _recall_at_k(got: List[int], rel: Set[int], k: int) -> Optional[float]:
    if not rel:
        return None
    hits = sum(1 for x in got[:k] if x in rel)
    return float(hits) / float(len(rel))


def _mrr_at_k(got: List[int], rel: Set[int], k: int) -> float:
    for i, x in enumerate(got[:k], start=1):
        if x in rel:
            return 1.0 / float(i)
    return 0.0


def _ndcg_at_k(got: List[int], rel: Set[int], k: int) -> Optional[float]:
    if not rel:
        return None
    dcg = 0.0
    for i, x in enumerate(got[:k], start=1):
        if x in rel:
            dcg += 1.0 / math.log2(i + 1.0)
    ideal_hits = min(int(k), len(rel))
    idcg = sum(1.0 / math.log2(i + 1.0) for i in range(1, ideal_hits + 1))
    if idcg <= 0:
        return None
    return float(dcg) / float(idcg)


def _ap_at_k(got: List[int], rel: Set[int], k: int) -> Optional[float]:
    if not rel:
        return None
    hits = 0
    s = 0.0
    for i, x in enumerate(got[:k], start=1):
        if x in rel:
            hits += 1
            s += float(hits) / float(i)
    denom = min(len(rel), k)
    if denom <= 0:
        return None
    return float(s) / float(denom)


@dataclass
class _InMemoryTfidfIndex:
    """
    Tiny TF-IDF-style scorer (not true BM25) to provide a meaningful retrieval fallback.
    """

    qid_to_tokens: Dict[int, Set[str]]
    df: Dict[str, int]
    n_docs: int

    @classmethod
    def build(cls, questions: List[_QuestionLike]) -> "_InMemoryTfidfIndex":
        qid_to_tokens: Dict[int, Set[str]] = {}
        df: Dict[str, int] = {}
        for q in questions:
            try:
                qid = int(q.id)
            except Exception:
                continue
            # Include knowledge_points to better match the weak-supervision label definition.
            content = getattr(q, "content", "") or ""
            kps = " ".join(_kps_list(q))
            toks = set(_tokenize(f"{content}\n{kps}".strip()))
            if not toks:
                continue
            qid_to_tokens[qid] = toks
            for tok in toks:
                df[tok] = int(df.get(tok, 0)) + 1
        return cls(qid_to_tokens=qid_to_tokens, df=df, n_docs=len(qid_to_tokens))

    def score(self, query_text: str, doc_tokens: Set[str]) -> float:
        qtoks = set(_tokenize(query_text))
        if not qtoks or not doc_tokens or self.n_docs <= 0:
            return 0.0
        # sum of idf for overlapping tokens
        s = 0.0
        for tok in qtoks:
            if tok not in doc_tokens:
                continue
            dfi = int(self.df.get(tok, 0))
            # smooth idf
            idf = math.log((self.n_docs + 1.0) / (dfi + 1.0)) + 1.0
            s += idf
        return float(s)


async def _load_questions(*, max_n: int) -> List[_QuestionLike]:
    """
    Load questions from DB.
    - Preferred: SQLAlchemy async (same as backend runtime)
    - Fallback: sqlite3 direct reads (when sqlalchemy isn't installed in current env)
    """
    if _HAVE_SQLALCHEMY:
        async with async_session_maker() as session:
            rows = (
                await session.execute(select(Question).order_by(Question.created_at.desc()).limit(max_n))
            ).scalars().all()
            return list(rows)

    database_url = os.getenv("DATABASE_URL") or "sqlite+aiosqlite:///./data/sqlite/app.db"
    db_path = _sqlite_path_from_database_url(database_url)
    if not os.path.exists(db_path):
        raise SystemExit(
            f"[retrieval_hit_rate] SQLite DB not found: {db_path} (set DATABASE_URL). "
            f"sqlalchemy_error={_SQLALCHEMY_IMPORT_ERROR}"
        )

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    rows = cur.execute(
        "SELECT id, user_id, content, knowledge_points, subject, created_at FROM questions ORDER BY created_at DESC LIMIT ?",
        (int(max_n),),
    ).fetchall()
    out: List[_QRow] = []
    for r in rows:
        try:
            kps_raw = r["knowledge_points"]
            if isinstance(kps_raw, str):
                try:
                    kps = json.loads(kps_raw or "[]")
                except Exception:
                    kps = []
            elif isinstance(kps_raw, list):
                kps = kps_raw
            else:
                kps = []
            created_at = None
            ca = r["created_at"]
            if isinstance(ca, str) and ca:
                try:
                    created_at = datetime.fromisoformat(ca.replace("Z", ""))
                except Exception:
                    created_at = None
            out.append(
                _QRow(
                    id=int(r["id"]),
                    user_id=int(r["user_id"]),
                    content=str(r["content"] or ""),
                    knowledge_points=[str(x) for x in (kps or []) if str(x)],
                    subject=str(r["subject"] or "") or None,
                    created_at=created_at,
                )
            )
        except Exception:
            continue
    con.close()
    return out


def _weak_relevant_set(q: _QuestionLike, all_q: List[_QuestionLike]) -> Set[int]:
    """
    Weak supervision rules (in order):
    1) knowledge_points overlap (preferred)
    2) subject match (fallback)

    NOTE: Retrieval is user-scoped elsewhere; caller should pass all_q already filtered to the same user.
    """
    rel: Set[int] = set()

    kps = set(_kps_list(q))
    if kps:
        for other in all_q:
            if other.id == q.id:
                continue
            okps = set(_kps_list(other))
            if kps.intersection(okps):
                rel.add(int(other.id))
        if rel:
            return rel

    # Fallback: same subject
    subj = (_subject_value(q) or "").strip()
    if subj:
        for other in all_q:
            if other.id == q.id:
                continue
            if (_subject_value(other) or "").strip() == subj:
                rel.add(int(other.id))
    return rel


async def _retrieve_local(
    *,
    query_text: str,
    user_id: int,
    subject: Optional[str],
    k: int,
    exclude_ids: List[int],
    inmem_index_by_subject: Dict[str, _InMemoryTfidfIndex],
    allow_runtime_hybrid: bool,
) -> List[int]:
    filt: Dict[str, Any] = {"user_id": user_id}
    if subject:
        filt["subject"] = subject

    # Best-effort: try to use the runtime hybrid retriever if deps are available.
    # If not available (common in teaching envs), fall back to in-memory TF-IDF keyword retrieval.
    use_inmem = True
    try:
        if not allow_runtime_hybrid:
            raise RuntimeError("runtime_hybrid_disabled")

        from backend.core.base_config import get_base_settings
        from backend.core.services.embedding_service import get_embedding_service
        from backend.core.services.hybrid_search_service import get_hybrid_search_service
        from backend.modules.wzy.config import settings

        svc = get_hybrid_search_service()
        ok = await svc.initialize(vector_store_path=settings.module_vector_path, bm25_index_path=settings.module_bm25_path)
        has_docs = bool(getattr(svc, "_document_store", None))
        has_bm25 = getattr(svc, "_bm25_index", None) is not None
        use_inmem = not (ok and has_docs and has_bm25)

        emb = None
        s = get_base_settings()
        have_embedding = bool(getattr(s, "OPENAI_API_KEY", None)) or bool(getattr(s, "LOCAL_EMBEDDING_MODEL", None))
        if have_embedding:
            emb = await get_embedding_service().embed_text(query_text)

        if not use_inmem:
            if emb:
                res = await svc.hybrid_search(
                    query_text=query_text,
                    query_embedding=emb,
                    top_k=k + len(exclude_ids),
                    filter_metadata=filt,
                )
            else:
                res = await svc.search_bm25(
                    query_text=query_text,
                    top_k=k + len(exclude_ids),
                    filter_metadata=filt,
                )

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
    except Exception:
        use_inmem = True

    # In-memory TF-IDF keyword retrieval (pure stdlib).
    subj_key = str(subject or "").strip().lower() or "__all__"
    idx = inmem_index_by_subject.get(subj_key) or inmem_index_by_subject.get("__all__")
    if not idx or idx.n_docs <= 0:
        return []

    seen = set(exclude_ids or [])
    scored: List[Tuple[float, int]] = []
    for qid, toks in idx.qid_to_tokens.items():
        if qid in seen:
            continue
        scored.append((idx.score(query_text, toks), qid))
    scored.sort(key=lambda x: x[0], reverse=True)
    out = [qid for s, qid in scored if s > 0][:k]
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
        telemetry={"module": "wzy", "subject": subject, "user_id": user_id, "payload": {"eval": True}},
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


async def _amain(args: argparse.Namespace) -> Dict[str, Any]:
    # NOTE: This is a teaching repo; we assume DATABASE_URL points to the intended sqlite DB.
    all_q = await _load_questions(max_n=max(args.max_questions, 200))
    if not all_q:
        return {"error": "no questions found"}

    # Pick user_id from DB rows (weak evaluator needs user scope; fallback to 1).
    # In a multi-user DB, you can pass --user-id explicitly.
    user_id = int(args.user_id or (all_q[0].user_id if getattr(all_q[0], "user_id", None) else 1))

    # IMPORTANT: retrieval is user-scoped in runtime (filter_metadata={"user_id": ...}).
    # So weak-supervision labels must be computed within the same user scope, otherwise hit@k will be artificially ~0.
    all_q_user = [q for q in all_q if int(getattr(q, "user_id", 0) or 0) == user_id]

    # Capabilities (decided once, to avoid repeated noisy logs per-case).
    has_faiss = bool(importlib.util.find_spec("faiss"))
    has_rank_bm25 = bool(importlib.util.find_spec("rank_bm25"))
    allow_runtime_hybrid = bool(has_faiss and has_rank_bm25)

    # Build a tiny in-memory index for fallback retrieval (per-user, per-subject).
    # This ensures evaluation can run even when faiss/rank_bm25/embedding models are not installed/configured.
    inmem_index_by_subject: Dict[str, _InMemoryTfidfIndex] = {"__all__": _InMemoryTfidfIndex.build(all_q_user)}
    for subj in ("math", "physics"):
        q_sub = [q for q in all_q_user if (_subject_value(q) or "") == subj]
        if q_sub:
            inmem_index_by_subject[subj] = _InMemoryTfidfIndex.build(q_sub)

    cases: List[Tuple[int, Set[int], str, Optional[str]]] = []
    if args.labels:
        labels = _load_labels(args.labels)
        # Build a lookup for question content
        q_by_id = {int(q.id): q for q in all_q_user}
        for row in labels:
            qid = int(row["query_question_id"])
            rel = set(int(x) for x in (row.get("relevant_question_ids") or []))
            q = q_by_id.get(qid)
            if not q:
                continue
            cases.append((qid, rel, q.content, _subject_value(q)))
    else:
        # weak supervision
        sampled = all_q_user[:]
        random.shuffle(sampled)
        sampled = sampled[: int(args.max_questions)]
        for q in sampled:
            rel = _weak_relevant_set(q, all_q_user)
            if not rel:
                continue
            # Add knowledge points into query text for a more faithful retrieval evaluation.
            kps = "；".join(_kps_list(q))
            query_text = f"{q.content}\n知识点：{kps}" if kps else q.content
            cases.append((int(q.id), rel, query_text, _subject_value(q)))

    if not cases:
        return {"error": "no evaluation cases built"}

    k = int(args.k)
    hits = 0
    total = 0
    p_sum = 0.0
    r_sum = 0.0
    p_n = 0
    r_n = 0
    mrr_sum = 0.0
    ndcg_sum = 0.0
    ndcg_n = 0
    ap_sum = 0.0
    ap_n = 0

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
                inmem_index_by_subject=inmem_index_by_subject,
                allow_runtime_hybrid=allow_runtime_hybrid,
            )
        total += 1
        if any((gid in rel) for gid in got):
            hits += 1
        p = _precision_at_k(got, rel, k)
        if p is not None:
            p_sum += float(p)
            p_n += 1
        r = _recall_at_k(got, rel, k)
        if r is not None:
            r_sum += float(r)
            r_n += 1
        mrr_sum += _mrr_at_k(got, rel, k)
        ndcg = _ndcg_at_k(got, rel, k)
        if ndcg is not None:
            ndcg_sum += float(ndcg)
            ndcg_n += 1
        ap = _ap_at_k(got, rel, k)
        if ap is not None:
            ap_sum += float(ap)
            ap_n += 1

    out = {
        "module": "wzy",
        "mode": "manual_labels" if args.labels else "weak_supervision",
        "user_id": user_id,
        "k": k,
        "cases": total,
        "hit_at_k": (hits / total) if total else None,
        "precision_at_k": (p_sum / p_n) if p_n else None,
        "recall_at_k": (r_sum / r_n) if r_n else None,
        "mrr_at_k": (mrr_sum / total) if total else None,
        "ndcg_at_k": (ndcg_sum / ndcg_n) if ndcg_n else None,
        "map_at_k": (ap_sum / ap_n) if ap_n else None,
        "notes": {
            "personal_model_endpoint": "Your vLLM /v1/chat/completions is for generation; retrieval evaluation needs embeddings+index. "
            "This script will fall back to a lightweight keyword retriever when embeddings/index deps are missing.",
            "runtime_hybrid_enabled": bool(allow_runtime_hybrid),
            "weak_supervision_definition": "Prefer knowledge_points overlap; fallback to same-subject within the same user scope.",
        },
    }
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--k", type=int, default=5)
    p.add_argument("--max-questions", type=int, default=200)
    p.add_argument("--labels", type=str, default=None)
    p.add_argument("--mcp-url", type=str, default=None)
    p.add_argument("--user-id", type=int, default=None)
    p.add_argument("--out", type=str, default="", help="Optional output JSON path")
    args = p.parse_args()

    import asyncio

    out = asyncio.run(_amain(args))
    print(json.dumps(out, ensure_ascii=False, indent=2))
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass

    if args.out:
        try:
            from pathlib import Path

            path = Path(args.out)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except Exception:
            pass

    # Best-effort: dispose engine if SQLAlchemy path is in use.
    if _HAVE_SQLALCHEMY:
        try:
            from backend.core.db.session import engine  # type: ignore

            asyncio.run(engine.dispose())
        except Exception:
            pass
    raise SystemExit(0)


if __name__ == "__main__":
    main()

