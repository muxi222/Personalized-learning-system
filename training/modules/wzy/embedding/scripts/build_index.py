#!/usr/bin/env python3
"""
Build Wzy retriever index (FAISS + BM25) from SQLite questions.

Why this exists:
- Embedding/index parameters are module-owned (under training/modules/<module>/...)
- Core provides only the shared builders/backends

Outputs (defaults):
- data/faiss/wzy/*
- data/bm25/wzy/*
"""

from __future__ import annotations

import argparse
import json
import asyncio
from pathlib import Path
from typing import Optional, Sequence

from training.core.graphrag.kb_builder import load_questions_from_sqlite
from training.core.graphrag.hybrid_index_builder import build_hybrid_index
from training.core.graphrag.embeddings import load_hashing_backend, load_sentence_transformer_backend


def _load_defaults(cfg_path: Path) -> dict:
    with open(cfg_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _parse_subjects(subjects: Optional[str], default_subjects: Sequence[str]) -> list[str]:
    if not subjects:
        return [str(s) for s in default_subjects]
    parts = [x.strip() for x in subjects.split(",")]
    return [x for x in parts if x]


def main():
    repo_root = Path(__file__).resolve()
    while repo_root.name != "training" and repo_root.parent != repo_root:
        repo_root = repo_root.parent
    repo_root = repo_root.parent if repo_root.name == "training" else Path.cwd()

    default_cfg = repo_root / "training" / "modules" / "wzy" / "embedding" / "configs" / "index.json"
    defaults = _load_defaults(default_cfg)

    parser = argparse.ArgumentParser(description="wzy embedding/index builder (FAISS+BM25)")
    parser.add_argument("--config", "-c", default=str(default_cfg), help="Config JSON path")
    parser.add_argument("--sqlite-path", default=defaults.get("sqlite_path", "data/sqlite/app.db"))
    parser.add_argument("--subjects", help="Comma-separated subjects (default from config)")
    parser.add_argument("--limit", type=int, default=defaults.get("limit"))

    parser.add_argument("--vector-store-dir", default=defaults.get("vector_store_dir", "data/faiss/wzy"))
    parser.add_argument("--bm25-dir", default=defaults.get("bm25_dir", "data/bm25/wzy"))
    parser.add_argument(
        "--append",
        action="store_true",
        help="Append to existing indices instead of recreating (advanced; usually keep default rebuild).",
    )

    parser.add_argument("--embedding-backend", choices=["hash", "sentence-transformers"], default=defaults.get("embedding_backend", "hash"))
    parser.add_argument("--embedding-model", default=defaults.get("embedding_model", "BAAI/bge-large-zh-v1.5"))
    parser.add_argument("--hash-dim", type=int, default=int(defaults.get("hash_dim", 1536)))

    args = parser.parse_args()

    subjects = _parse_subjects(args.subjects, defaults.get("subjects", ["math", "physics"]))

    if args.embedding_backend == "hash":
        backend = load_hashing_backend(dimension=int(args.hash_dim))
    else:
        backend = load_sentence_transformer_backend(str(args.embedding_model))

    questions = load_questions_from_sqlite(
        sqlite_path=Path(args.sqlite_path),
        subjects=subjects,
        limit=args.limit,
    )

    async def _run():
        return await build_hybrid_index(
            module_name="wzy",
            questions=questions,
            embed_text=backend.embed_text,
            vector_store_dir=Path(args.vector_store_dir),
            bm25_dir=Path(args.bm25_dir),
            force_recreate=(not args.append),
        )

    result = asyncio.run(_run())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

