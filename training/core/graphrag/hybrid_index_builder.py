"""
Hybrid (FAISS + BM25) index builder for GraphRAG.

We intentionally reuse the backend implementation (`HybridSearchService`) so:
- on-disk formats match runtime search
- Tony agents can immediately query the built index by pointing settings to the same paths
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence
from pathlib import Path

import numpy as np

from .kb_builder import QuestionRecord


def _normalize_embedding(vec: List[float]) -> List[float]:
    v = np.array(vec, dtype=np.float32)
    n = np.linalg.norm(v)
    if n == 0:
        return v.tolist()
    return (v / n).tolist()


async def build_hybrid_index(
    *,
    module_name: str,
    questions: Sequence[QuestionRecord],
    embed_text: Callable[[str], List[float]],
    vector_store_dir: str | Path,
    bm25_dir: str | Path,
    force_recreate: bool = True,
) -> Dict[str, Any]:
    """
    Build and persist the hybrid index.

    Args:
        embed_text: synchronous embedding function returning List[float]
    """
    from backend.core.services.hybrid_search_service import HybridSearchService

    vector_store_dir = Path(vector_store_dir)
    bm25_dir = Path(bm25_dir)
    vector_store_dir.mkdir(parents=True, exist_ok=True)
    bm25_dir.mkdir(parents=True, exist_ok=True)

    # Determine embedding dimension from the embedding function.
    probe = embed_text("probe")
    if not probe:
        raise RuntimeError("embed_text returned empty embedding for probe text")
    dim = len(probe)

    hs = HybridSearchService()
    await hs.initialize(
        vector_store_path=str(vector_store_dir),
        bm25_index_path=str(bm25_dir),
        force_recreate=force_recreate,
        embedding_dimension=dim,
    )

    added = 0
    skipped = 0

    for q in questions:
        content = (q.content or "").strip()
        if not content:
            skipped += 1
            continue

        # Build a retrieval-friendly doc text (keeps it simple and stable).
        kp = [x for x in (q.knowledge_points or []) if str(x).strip()]
        if kp:
            content_for_embed = f"{content}\n知识点: {', '.join(kp)}"
        else:
            content_for_embed = content

        emb = embed_text(content_for_embed)
        if not emb:
            skipped += 1
            continue

        await hs.add_document(
            doc_id=str(q.id),
            content=content,
            embedding=emb,
            metadata={
                "module": module_name,
                "user_id": q.user_id,
                "subject": q.subject,
                "difficulty": q.difficulty,
                "chapter": q.chapter,
                "knowledge_points": q.knowledge_points or [],
                "tags": q.tags or [],
                "upload_group_id": q.upload_group_id,
                "upload_index": q.upload_index,
            },
        )
        added += 1

    await hs.save_indices()

    return {
        "module": module_name,
        "vector_store_dir": str(vector_store_dir),
        "bm25_dir": str(bm25_dir),
        "embedding_dimension": dim,
        "added": added,
        "skipped": skipped,
    }

