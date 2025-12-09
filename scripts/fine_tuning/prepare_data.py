#!/usr/bin/env python3
"""
数据准备脚本
将原始数据转换为统一的微调数据集格式 (Alpaca/ShareGPT格式)
"""

import json
import argparse
from pathlib import Path
from typing import List, Dict, Any, Optional
import random


def load_raw_data(input_path: str) -> List[Dict[str, Any]]:
    """
    加载原始数据
    支持 JSON/JSONL 格式
    """
    data = []
    path = Path(input_path)

    if path.suffix == ".jsonl":
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    data.append(json.loads(line))
    else:
        with open(path, "r", encoding="utf-8") as f:
            content = json.load(f)
            if isinstance(content, list):
                data = content
            else:
                data = [content]

    print(f"Loaded {len(data)} samples from {input_path}")
    return data


def convert_to_alpaca_format(
    sample: Dict[str, Any],
    task_type: str = "error_analysis",
) -> Optional[Dict[str, str]]:
    """
    转换为Alpaca格式
    
    Alpaca format:
    {
        "instruction": "任务指令",
        "input": "输入内容",
        "output": "期望输出"
    }
    """
    if task_type == "error_analysis":
        # 错因分析任务
        if not sample.get("content") or not sample.get("error_analysis"):
            return None

        instruction = (
            "你是一位专业的教育专家，请分析以下学生的错题，"
            "找出错误原因并给出针对性的学习指导。"
        )

        input_text = f"""题目: {sample.get('content', '')}
学科: {sample.get('subject', '未知')}
学生答案: {sample.get('student_answer', '未提供')}
正确答案: {sample.get('correct_answer', '未提供')}
涉及知识点: {', '.join(sample.get('knowledge_points', []))}"""

        return {
            "instruction": instruction,
            "input": input_text,
            "output": sample["error_analysis"],
        }

    elif task_type == "generate_questions":
        # 举一反三任务
        if not sample.get("content") or not sample.get("suggested_questions"):
            return None

        instruction = (
            "你是一位经验丰富的出题专家，根据以下错题信息，"
            "生成3-5道相关的练习题帮助学生巩固知识。"
        )

        input_text = f"""原题: {sample.get('content', '')}
学科: {sample.get('subject', '未知')}
知识点: {', '.join(sample.get('knowledge_points', []))}
错因分析: {sample.get('error_analysis', '未提供')}"""

        output = json.dumps(sample["suggested_questions"], ensure_ascii=False, indent=2)

        return {
            "instruction": instruction,
            "input": input_text,
            "output": output,
        }

    return None


def convert_to_sharegpt_format(
    sample: Dict[str, Any],
    task_type: str = "error_analysis",
) -> Optional[Dict[str, Any]]:
    """
    转换为ShareGPT格式 (多轮对话)
    
    ShareGPT format:
    {
        "conversations": [
            {"from": "human", "value": "..."},
            {"from": "gpt", "value": "..."}
        ]
    }
    """
    if task_type == "error_analysis":
        if not sample.get("content") or not sample.get("error_analysis"):
            return None

        human_message = f"""请分析以下学生的错题:

题目: {sample.get('content', '')}
学科: {sample.get('subject', '未知')}
学生答案: {sample.get('student_answer', '未提供')}
正确答案: {sample.get('correct_answer', '未提供')}

请从以下角度进行分析:
1. 错误类型判定
2. 错误根因分析
3. 知识点讲解
4. 正确解题思路
5. 学习建议"""

        return {
            "conversations": [
                {"from": "human", "value": human_message},
                {"from": "gpt", "value": sample["error_analysis"]},
            ]
        }

    return None


def prepare_dataset(
    input_path: str,
    output_path: str,
    format_type: str = "alpaca",
    task_type: str = "error_analysis",
    train_ratio: float = 0.9,
    seed: int = 42,
):
    """
    准备微调数据集
    
    Args:
        input_path: 输入数据路径
        output_path: 输出数据路径
        format_type: 输出格式 (alpaca/sharegpt)
        task_type: 任务类型 (error_analysis/generate_questions)
        train_ratio: 训练集比例
        seed: 随机种子
    """
    random.seed(seed)

    # Load data
    raw_data = load_raw_data(input_path)

    # Convert format
    converted_data = []
    for sample in raw_data:
        if format_type == "alpaca":
            converted = convert_to_alpaca_format(sample, task_type)
        else:
            converted = convert_to_sharegpt_format(sample, task_type)

        if converted:
            converted_data.append(converted)

    print(f"Converted {len(converted_data)} samples")

    # Shuffle and split
    random.shuffle(converted_data)
    split_idx = int(len(converted_data) * train_ratio)
    train_data = converted_data[:split_idx]
    eval_data = converted_data[split_idx:]

    # Save
    output_dir = Path(output_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    train_path = output_dir / "train.jsonl"
    eval_path = output_dir / "eval.jsonl"

    with open(train_path, "w", encoding="utf-8") as f:
        for item in train_data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    with open(eval_path, "w", encoding="utf-8") as f:
        for item in eval_data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"Saved {len(train_data)} training samples to {train_path}")
    print(f"Saved {len(eval_data)} evaluation samples to {eval_path}")


def main():
    parser = argparse.ArgumentParser(description="Prepare fine-tuning dataset")
    parser.add_argument(
        "--input", "-i", required=True, help="Input data file (JSON/JSONL)"
    )
    parser.add_argument(
        "--output", "-o", required=True, help="Output directory"
    )
    parser.add_argument(
        "--format", "-f",
        choices=["alpaca", "sharegpt"],
        default="alpaca",
        help="Output format",
    )
    parser.add_argument(
        "--task", "-t",
        choices=["error_analysis", "generate_questions"],
        default="error_analysis",
        help="Task type",
    )
    parser.add_argument(
        "--train-ratio",
        type=float,
        default=0.9,
        help="Training set ratio",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed",
    )

    args = parser.parse_args()
    prepare_dataset(
        input_path=args.input,
        output_path=args.output,
        format_type=args.format,
        task_type=args.task,
        train_ratio=args.train_ratio,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()

