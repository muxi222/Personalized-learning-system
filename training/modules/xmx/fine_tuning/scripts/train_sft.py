#!/usr/bin/env python3
"""
XMX SFT 训练启动器 (经济学模型监督微调).

该脚本封装了 XMX 模块特有的数据路径和配置逻辑：
1. 默认调用针对经济学优化的 Qwen 系列模型配置。
2. 支持按“学科/子领域” (如 macro/micro) 切换数据集。
3. 调用 core 核心训练引擎执行 LoRA 或全量微调。
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description="XMX Economics SFT Runner (wrapper)")
    parser.add_argument(
        "--subject",
        default="economics",
        help="经济学子领域 (例如: macro/micro/finance/economics). "
             "设置后，数据集将指向 data/training/xmx/datasets/sft/<subject>/train.jsonl",
    )
    # 解析已知参数，透传未知参数
    args, passthru = parser.parse_known_args()

    # 1. 定位仓库根目录
    p = Path(__file__).resolve()
    while p.name != "training" and p.parent != p:
        p = p.parent
    repo_root = p.parent if p.name == "training" else Path.cwd()

    # 2. 定义路径
    trainer = repo_root / "training" / "core" / "fine_tuning" / "train_sft.py"
    # XMX 默认使用针对经济学优化的 14B 模型 LoRA 配置
    cfg = repo_root / "training" / "modules" / "xmx" / "fine_tuning" / "configs" / "sft_economics_14b_lora.json"

    # 3. 基础命令构建
    cmd = [sys.executable, str(trainer), "--config", str(cfg)]

    # 4. 动态数据与输出路径逻辑
    # 针对 XMX 的路径规范：data/training/xmx/...
    subject = (args.subject or "economics").strip().lower()
    
    dataset = repo_root / "data" / "training" / "xmx" / "datasets" / "sft" / subject / "train.jsonl"
    out_dir = repo_root / "data" / "training" / "xmx" / "checkpoints" / "sft_lora" / subject
    
    # 将自动生成的路径注入命令（除非用户在 passthru 中手动覆盖）
    cmd += ["--dataset", str(dataset), "--output", str(out_dir)]

    # 5. 透传额外参数 (如 --epochs, --learning_rate)
    if passthru:
        cmd += passthru

    print("=" * 60)
    print(f"📈 启动 XMX 经济学模型 SFT 训练")
    print(f"当前领域: {subject}")
    print(f"执行命令: {' '.join(cmd)}")
    print("=" * 60)

    # 6. 执行训练
    raise SystemExit(subprocess.call(cmd))


if __name__ == "__main__":
    main()