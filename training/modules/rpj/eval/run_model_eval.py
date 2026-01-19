#!/usr/bin/env python3
"""
RPJ model eval runner (OpenAI-compatible endpoint).

Student module: provides a minimal eval set + runnable wrapper.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path
import sys
import subprocess


def main() -> int:
    parser = argparse.ArgumentParser(description="RPJ model eval runner (vLLM)")
    parser.add_argument("--module", default="rpj")  # passed from pipeline.sh
    parser.add_argument("--api-base", default="http://127.0.0.1:8002/v1")
    parser.add_argument("--model", default="rpj-dpo")
    parser.add_argument("--judge-api-base", default="")
    parser.add_argument("--judge-model", default="")
    args, passthru = parser.parse_known_args()

    repo = Path(__file__).resolve()
    while repo.name != "training" and repo.parent != repo:
        repo = repo.parent
    repo_root = repo.parent if repo.name == "training" else Path.cwd()

    data_eval = repo_root / "data" / "training" / "rpj" / "eval"
    data_eval.mkdir(parents=True, exist_ok=True)
    eval_set = data_eval / "model_eval.jsonl"
    if not eval_set.exists():
        src = repo_root / "training" / "modules" / "rpj" / "eval" / "assets" / "model_eval_min.jsonl"
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
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())

