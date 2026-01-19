#!/usr/bin/env python3
"""
Tony model eval runner (OpenAI-compatible endpoint, e.g. local vLLM).

This wrapper:
- ensures a minimal eval set exists under data/ (student-friendly)
- calls the core evaluator with Tony defaults
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path
import sys
import subprocess
import json


def main() -> int:
    parser = argparse.ArgumentParser(description="Tony model eval runner (vLLM)")
    parser.add_argument("--module", default="tony")  # passed from pipeline.sh
    parser.add_argument("--api-base", default="http://127.0.0.1:8001/v1")
    parser.add_argument("--model", default="tony-dpo")
    parser.add_argument("--judge-api-base", default="")
    parser.add_argument("--judge-model", default="")
    args, passthru = parser.parse_known_args()

    repo = Path(__file__).resolve()
    while repo.name != "training" and repo.parent != repo:
        repo = repo.parent
    repo_root = repo.parent if repo.name == "training" else Path.cwd()

    # Ensure eval set exists under data/
    data_eval = repo_root / "data" / "training" / "tony" / "eval"
    data_eval.mkdir(parents=True, exist_ok=True)
    eval_set = data_eval / "model_eval.jsonl"
    if not eval_set.exists():
        src = repo_root / "training" / "modules" / "tony" / "eval" / "assets" / "model_eval_min.jsonl"
        shutil.copyfile(src, eval_set)

    out = data_eval / "model_eval_report.json"
    core = repo_root / "training" / "core" / "eval" / "model_eval_openai_compatible.py"
    cmd = [
        sys.executable,
        str(core),
        "--eval-set",
        str(eval_set),
        "--api-base",
        str(args.api_base),
        "--model",
        str(args.model),
        "--out",
        str(out),
    ]
    if args.judge_api_base and args.judge_model:
        cmd += ["--judge-api-base", args.judge_api_base, "--judge-model", args.judge_model]
    if passthru:
        cmd += passthru
    print(" ".join(cmd))
    rc = subprocess.call(cmd)
    if rc != 0:
        return int(rc)

    # Retrieval evaluation (precision/recall/hit@k) for Tony (准召率).
    # This is user-scoped and depends on local indices/embeddings; the script will fall back to a lightweight keyword
    # retriever when deps are missing, so students can still get a report.
    retrieval_out = data_eval / "retrieval_eval_report.json"
    try:
        cmd2 = [
            sys.executable,
            "-m",
            "training.modules.tony.eval.retrieval_hit_rate",
            "--k",
            "5",
            "--max-questions",
            "200",
            "--out",
            str(retrieval_out),
        ]
        print(" ".join(cmd2))
        rc2 = subprocess.call(cmd2)
        if rc2 == 0 and retrieval_out.exists() and out.exists():
            rep = json.loads(out.read_text(encoding="utf-8"))
            rrep = json.loads(retrieval_out.read_text(encoding="utf-8"))
            rep["retrieval_eval"] = rrep
            # Attach a short retrieval summary into conclusion if present
            try:
                c = rep.get("conclusion") if isinstance(rep, dict) else None
                if isinstance(c, dict):
                    summ = (
                        f"retrieval: hit@k={rrep.get('hit_at_k')} "
                        f"precision@k={rrep.get('precision_at_k')} recall@k={rrep.get('recall_at_k')}"
                    )
                    prev = str(c.get("summary") or "").strip()
                    c["summary"] = (prev + " | " + summ).strip(" |")
            except Exception:
                pass
            out.write_text(json.dumps(rep, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

