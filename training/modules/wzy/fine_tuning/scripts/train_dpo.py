#!/usr/bin/env python3
"""
Wzy DPO runner wrapper.

Calls `training/core/fine_tuning/train_dpo.py` with Wzy config.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description="Wzy DPO runner (wrapper)")
    _args, passthru = parser.parse_known_args()

    p = Path(__file__).resolve()
    while p.name != "training" and p.parent != p:
        p = p.parent
    repo_root = p.parent if p.name == "training" else Path.cwd()

    trainer = repo_root / "training" / "core" / "fine_tuning" / "train_dpo.py"
    cfg = repo_root / "training" / "modules" / "wzy" / "fine_tuning" / "configs" / "dpo_qwen3_14b_lora.json"

    cmd = [sys.executable, str(trainer), "--config", str(cfg)]
    if passthru:
        cmd += passthru
    print(" ".join(cmd))
    raise SystemExit(subprocess.call(cmd))


if __name__ == "__main__":
    main()

