#!/usr/bin/env python3
"""
LEGACY entry point (deprecated).

The real trainer now lives in:
  `training/core/fine_tuning/train_sft.py`

Module-specific configs/prompts should live under:
  `training/modules/<module>/fine_tuning/...`
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main():
    p = Path(__file__).resolve()
    while p.name != "training" and p.parent != p:
        p = p.parent
    repo_root = p.parent if p.name == "training" else Path.cwd()

    core_trainer = repo_root / "training" / "core" / "fine_tuning" / "train_sft.py"
    cmd = [sys.executable, str(core_trainer), *sys.argv[1:]]
    print(" ".join(cmd))
    raise SystemExit(subprocess.call(cmd))


if __name__ == "__main__":
    main()

