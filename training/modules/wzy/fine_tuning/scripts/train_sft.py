#!/usr/bin/env python3
"""
Wzy SFT runner wrapper.

This wrapper calls the repo's generic SFT trainer:
`training/core/fine_tuning/train_sft.py`

Why wrapper?
- Keeps module-specific configs and dataset paths in `training/modules/wzy/...`
- Avoids breaking the existing generic script
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description="Wzy SFT runner (wrapper)")
    parser.add_argument(
        "--subject",
        default="",
        help="Optional subject to train on (e.g. math/physics). "
        "If set, dataset defaults to data/training/wzy/datasets/sft/<subject>/train.jsonl and "
        "output defaults to data/training/wzy/checkpoints/sft_lora/<subject>.",
    )
    args, passthru = parser.parse_known_args()

    p = Path(__file__).resolve()
    while p.name != "training" and p.parent != p:
        p = p.parent
    repo_root = p.parent if p.name == "training" else Path.cwd()

    trainer = repo_root / "training" / "core" / "fine_tuning" / "train_sft.py"
    cfg = repo_root / "training" / "modules" / "wzy" / "fine_tuning" / "configs" / "sft_qwen3_14b_lora.json"

    cmd = [sys.executable, str(trainer), "--config", str(cfg)]

    subject = (args.subject or "").strip().lower()
    if subject:
        dataset = repo_root / "data" / "training" / "wzy" / "datasets" / "sft" / subject / "train.jsonl"
        out_dir = repo_root / "data" / "training" / "wzy" / "checkpoints" / "sft_lora" / subject
        cmd += ["--dataset", str(dataset), "--output", str(out_dir)]

    if passthru:
        cmd += passthru
    print(" ".join(cmd))
    raise SystemExit(subprocess.call(cmd))


if __name__ == "__main__":
    main()

