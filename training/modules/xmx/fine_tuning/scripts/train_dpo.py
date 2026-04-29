#!/usr/bin/env python3
"""
XMX DPO 训练启动器 (经济学模型偏好对齐).

该脚本是训练核心逻辑的封装，主要任务：
1. 定位 XMX 专属的 DPO 训练配置文件。
2. 调用 core 文件夹下的通用 DPO 训练引擎。
3. 允许通过命令行透传参数（如 --epochs, --batch_size）。
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description="XMX Economics DPO Runner (wrapper)")
    # 解析已知参数，将未知参数 passthru 透传给底层的训练脚本
    _args, passthru = parser.parse_known_args()

    # 1. 动态定位仓库根目录
    p = Path(__file__).resolve()
    while p.name != "training" and p.parent != p:
        p = p.parent
    repo_root = p.parent if p.name == "training" else Path.cwd()

    # 2. 定义核心训练脚本路径
    trainer = repo_root / "training" / "core" / "fine_tuning" / "train_dpo.py"
    
    # 3. 定义 XMX 专属配置文件
    # 假设 XMX 模块使用的是针对经济学优化的 Qwen 架构配置
    cfg = repo_root / "training" / "modules" / "xmx" / "fine_tuning" / "configs" / "dpo_economics_lora.json"

    # 检查配置文件是否存在
    if not cfg.exists():
        print(f"[错误] 找不到 XMX DPO 配置文件: {cfg}")
        return 1

    # 4. 构建执行命令
    cmd = [sys.executable, str(trainer), "--config", str(cfg)]
    
    # 如果用户在命令行输入了额外参数（如 --learning_rate 1e-5），会追加到命令末尾
    if passthru:
        cmd += passthru
    
    print("=" * 60)
    print(f"🚀 启动 XMX 经济学模型 DPO 训练")
    print(f"配置文件: {cfg.name}")
    print(f"执行命令: {' '.join(cmd)}")
    print("=" * 60)

    # 5. 执行并返回状态码
    raise SystemExit(subprocess.call(cmd))


if __name__ == "__main__":
    main()