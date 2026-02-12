#!/usr/bin/env python3
"""
Build Wzy GraphRAG KB (graph + hybrid retriever index).

Outputs:
- Graph: `data/training/wzy/graphrag/graph.json`
- Hybrid index (runtime compatible):
  - FAISS: `data/faiss/wzy/`
  - BM25:  `data/bm25/wzy/`

Why split graph vs index?
- Graph artifacts are GraphRAG-specific and live under `data/training/...`
- The retriever index is shared runtime infra and already lives under `data/faiss|bm25/<module>`
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

_p = Path(__file__).resolve()
while _p.name != "training" and _p.parent != _p:
    _p = _p.parent
_repo_root = _p.parent if _p.name == "training" else Path.cwd()
sys.path.insert(0, str(_repo_root))

from training.core.graphrag.kb_builder import (
    build_kb_artifacts,
)


DEFAULT_SUBJECTS = ["math", "physics"]


def main():
    parser = argparse.ArgumentParser(description="Build Wzy GraphRAG KB")
    parser.add_argument(
        "--sqlite",
        default=str(_repo_root / "data" / "sqlite" / "app.db"),
        help="Path to app SQLite DB",
    )
    parser.add_argument(
        "--output-dir",
        default=str(_repo_root / "data" / "training" / "wzy" / "graphrag"),
        help="Output directory for GraphRAG artifacts (graph.json, reports, etc.)",
    )
    parser.add_argument(
        "--subjects",
        nargs="*",
        default=DEFAULT_SUBJECTS,
        help="Subjects to include (wzy: math physics)",
    )
    parser.add_argument("--limit", type=int, default=0, help="Optional limit for quick smoke builds")

    parser.add_argument(
        "--build-index",
        action="store_true",
        help="Also build the FAISS+BM25 hybrid index under data/faiss/wzy and data/bm25/wzy",
    )
    parser.add_argument(
        "--embedding-backend",
        choices=["sentence-transformers", "hash"],
        default="hash",
        help="Embedding backend for indexing. Use 'hash' for offline-safe builds; use sentence-transformers when HF access/caches are available.",
    )
    parser.add_argument(
        "--embedding-model",
        default="BAAI/bge-large-zh-v1.5",
        help="Sentence-transformers embedding model to use for indexing",
    )
    parser.add_argument(
        "--vector-dir",
        default=str(_repo_root / "data" / "faiss" / "wzy"),
        help="FAISS store dir (should match backend module_vector_path for wzy)",
    )
    parser.add_argument(
        "--bm25-dir",
        default=str(_repo_root / "data" / "bm25" / "wzy"),
        help="BM25 store dir (should match backend module_bm25_path for wzy)",
    )
    args = parser.parse_args()

    sqlite_path = Path(args.sqlite)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    limit = int(args.limit) if int(args.limit) > 0 else None

    # 1) Build graph artifacts
    report = build_kb_artifacts(
        module_name="wzy",
        sqlite_path=sqlite_path,
        subjects=args.subjects,
        output_dir=out_dir,
        limit=limit,
    )

    # 2) Optionally build retriever index
    if args.build_index:
        # Reuse the module-owned embedding/index builder so:
        # - `kb --build-index` and `pipeline.sh embed-index` share the same code path
        # - indexing parameters/config live under training/modules/wzy/embedding/...
        index_builder = _repo_root / "training" / "modules" / "wzy" / "embedding" / "scripts" / "build_index.py"
        if not index_builder.exists():
            raise FileNotFoundError(f"Index builder not found: {index_builder}")

        cmd = [
            sys.executable,
            str(index_builder),
            "--sqlite-path",
            str(sqlite_path),
            "--vector-store-dir",
            str(args.vector_dir),
            "--bm25-dir",
            str(args.bm25_dir),
            "--embedding-backend",
            str(args.embedding_backend),
            "--embedding-model",
            str(args.embedding_model),
        ]
        if limit is not None:
            cmd += ["--limit", str(limit)]
        if args.subjects:
            cmd += ["--subjects", ",".join([str(s) for s in args.subjects if str(s).strip()])]
        if args.embedding_backend == "hash":
            cmd += ["--hash-dim", "1536"]

        # The index builder prints a JSON object report to stdout. Capture it for the KB build report.
        out = subprocess.check_output(cmd, cwd=str(_repo_root), text=True)
        try:
            index_report = json.loads(out.strip() or "{}")
        except Exception:
            index_report = {"_raw_stdout": out}

        report["index"] = index_report

    # Save build report
    with open(out_dir / "build_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

