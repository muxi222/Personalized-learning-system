#!/usr/bin/env python3
"""
Tony DPO runner wrapper.

Calls `training/core/fine_tuning/train_dpo.py` with Tony config.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
import sys


def main():
    p = Path(__file__).resolve()
    while p.name != "training" and p.parent != p:
        p = p.parent
    repo_root = p.parent if p.name == "training" else Path.cwd()

    trainer = repo_root / "training" / "core" / "fine_tuning" / "train_dpo.py"
    cfg = repo_root / "training" / "modules" / "tony" / "fine_tuning" / "configs" / "dpo_qwen3_14b_lora.json"

    cmd = [sys.executable, str(trainer), "--config", str(cfg)]
    print(" ".join(cmd))
    raise SystemExit(subprocess.call(cmd))


if __name__ == "__main__":
    main()

