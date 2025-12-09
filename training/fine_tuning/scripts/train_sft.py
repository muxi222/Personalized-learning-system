#!/usr/bin/env python3
"""
SFT训练脚本 - Supervised Fine-Tuning
根据设计文档5.3节实现

使用QLoRA方法进行高效微调，将通用大模型转变为"学习小书童"专属模型。
"""

import os
import json
import argparse
from pathlib import Path
from typing import Optional

import torch
from datasets import load_dataset
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    TrainingArguments,
)
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
from trl import SFTTrainer


# 默认配置 (根据设计文档5.1节推荐)
DEFAULT_CONFIG = {
    # 基础模型选择 (设计文档5.1节)
    "model_name": "Qwen/Qwen2-7B-Instruct",  # 推荐: Qwen或Llama 3
    
    # 数据配置
    "dataset_path": "./data/train.jsonl",
    "output_dir": "./output",
    
    # LoRA配置 (设计文档5.3节)
    "lora_r": 64,
    "lora_alpha": 16,
    "lora_dropout": 0.1,
    "lora_target_modules": [
        "q_proj", "k_proj", "v_proj", "o_proj",  # Attention层
        "gate_proj", "up_proj", "down_proj"       # FFN层
    ],
    
    # 训练配置
    "num_epochs": 3,
    "batch_size": 4,
    "gradient_accumulation_steps": 4,
    "learning_rate": 2e-4,
    "max_seq_length": 2048,
    "warmup_ratio": 0.03,
    "weight_decay": 0.001,
    
    # 量化配置 (QLoRA)
    "use_4bit": True,
    "bnb_4bit_compute_dtype": "bfloat16",
    "bnb_4bit_quant_type": "nf4",
    "use_nested_quant": False,
}


def load_config(config_path: Optional[str] = None) -> dict:
    """加载配置"""
    config = DEFAULT_CONFIG.copy()
    
    if config_path and Path(config_path).exists():
        with open(config_path, "r", encoding="utf-8") as f:
            custom_config = json.load(f)
            config.update(custom_config)
    
    return config


def setup_model_and_tokenizer(config: dict):
    """
    配置模型和Tokenizer
    根据设计文档5.3节步骤2-3
    """
    print(f"📦 加载模型: {config['model_name']}")
    
    # 量化配置 (4-bit QLoRA)
    compute_dtype = getattr(torch, config["bnb_4bit_compute_dtype"])
    
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=config["use_4bit"],
        bnb_4bit_quant_type=config["bnb_4bit_quant_type"],
        bnb_4bit_compute_dtype=compute_dtype,
        bnb_4bit_use_double_quant=config["use_nested_quant"],
    )
    
    # 加载模型
    model = AutoModelForCausalLM.from_pretrained(
        config["model_name"],
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True,
    )
    model.config.use_cache = False
    model.config.pretraining_tp = 1
    
    # 加载Tokenizer
    tokenizer = AutoTokenizer.from_pretrained(
        config["model_name"],
        trust_remote_code=True,
    )
    tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"
    
    # 准备模型进行k-bit训练
    model = prepare_model_for_kbit_training(model)
    
    # LoRA配置 (设计文档5.3节步骤3)
    peft_config = LoraConfig(
        r=config["lora_r"],
        lora_alpha=config["lora_alpha"],
        lora_dropout=config["lora_dropout"],
        target_modules=config["lora_target_modules"],
        bias="none",
        task_type="CAUSAL_LM",
    )
    
    # 应用LoRA
    model = get_peft_model(model, peft_config)
    
    # 打印可训练参数
    trainable, total = model.get_nb_trainable_parameters()
    print(f"📊 可训练参数: {trainable:,} / {total:,} ({100 * trainable / total:.2f}%)")
    
    return model, tokenizer, peft_config


def format_instruction_prompt(example: dict, tokenizer) -> str:
    """
    格式化指令数据 (设计文档5.2节)
    
    数据格式: {"instruction": "...", "input": "...", "output": "..."}
    """
    # "学习小书童"人设的系统提示
    system_prompt = """你是"学习小书童"，一位温暖、有耐心、专业的学习助手。
你的职责是帮助学生分析错题、理解知识点、提供学习指导。
回答时要：
1. 用鼓励和引导的语气
2. 讲解清晰，由浅入深
3. 适当使用emoji增加亲和力
4. 关注学生的情绪，给予支持"""
    
    instruction = example.get("instruction", "")
    input_text = example.get("input", "")
    output_text = example.get("output", "")
    
    if input_text:
        prompt = f"""### 系统:
{system_prompt}

### 指令:
{instruction}

### 输入:
{input_text}

### 回答:
{output_text}"""
    else:
        prompt = f"""### 系统:
{system_prompt}

### 指令:
{instruction}

### 回答:
{output_text}"""
    
    return prompt


def train(config: dict):
    """
    执行训练
    根据设计文档5.3节步骤5-6
    """
    # 设置模型和Tokenizer
    model, tokenizer, peft_config = setup_model_and_tokenizer(config)
    
    # 加载数据集 (设计文档5.2节)
    print(f"📂 加载数据集: {config['dataset_path']}")
    dataset = load_dataset("json", data_files={
        "train": config["dataset_path"],
    })["train"]
    
    print(f"📊 数据集大小: {len(dataset)} 条")
    
    # 训练参数
    training_args = TrainingArguments(
        output_dir=config["output_dir"],
        num_train_epochs=config["num_epochs"],
        per_device_train_batch_size=config["batch_size"],
        gradient_accumulation_steps=config["gradient_accumulation_steps"],
        learning_rate=config["learning_rate"],
        weight_decay=config["weight_decay"],
        warmup_ratio=config["warmup_ratio"],
        lr_scheduler_type="cosine",
        logging_steps=10,
        save_strategy="epoch",
        evaluation_strategy="no",
        bf16=True,
        tf32=True,
        max_grad_norm=0.3,
        group_by_length=True,
        report_to="tensorboard",
        optim="paged_adamw_32bit",
    )
    
    # 创建Trainer
    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=dataset,
        tokenizer=tokenizer,
        formatting_func=lambda x: format_instruction_prompt(x, tokenizer),
        max_seq_length=config["max_seq_length"],
        packing=False,
    )
    
    # 开始训练 (设计文档5.3节步骤6)
    print("🚀 开始训练...")
    trainer.train()
    
    # 保存模型 (设计文档5.3节步骤7)
    print(f"💾 保存模型到 {config['output_dir']}")
    trainer.save_model()
    tokenizer.save_pretrained(config["output_dir"])
    
    print("✅ 训练完成!")


def merge_weights(config: dict, merge_output_dir: str):
    """
    合并LoRA权重
    设计文档5.3节步骤7: 合并Adapter权重以提高推理速度
    """
    from peft import PeftModel
    
    print("📦 加载基础模型...")
    base_model = AutoModelForCausalLM.from_pretrained(
        config["model_name"],
        torch_dtype=torch.bfloat16,
        device_map="auto",
        trust_remote_code=True,
    )
    
    print(f"📦 加载LoRA权重: {config['output_dir']}")
    model = PeftModel.from_pretrained(base_model, config["output_dir"])
    
    print("🔗 合并权重...")
    merged_model = model.merge_and_unload()
    
    print(f"💾 保存合并后的模型: {merge_output_dir}")
    merged_model.save_pretrained(merge_output_dir)
    
    tokenizer = AutoTokenizer.from_pretrained(config["model_name"])
    tokenizer.save_pretrained(merge_output_dir)
    
    print("✅ 合并完成!")


def main():
    parser = argparse.ArgumentParser(
        description="学习小书童 - SFT微调脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 使用默认配置训练
  python train_sft.py --dataset ./data/train.jsonl

  # 使用自定义配置文件
  python train_sft.py --config ./configs/qwen_7b.json

  # 训练后合并权重
  python train_sft.py --dataset ./data/train.jsonl --merge --merge-output ./models/merged
        """
    )
    
    parser.add_argument("--config", "-c", help="配置文件路径")
    parser.add_argument("--model", "-m", help="基础模型名称")
    parser.add_argument("--dataset", "-d", help="训练数据集路径")
    parser.add_argument("--output", "-o", help="输出目录")
    parser.add_argument("--epochs", type=int, help="训练轮数")
    parser.add_argument("--batch-size", type=int, help="批次大小")
    parser.add_argument("--lr", type=float, help="学习率")
    parser.add_argument("--merge", action="store_true", help="训练后合并权重")
    parser.add_argument("--merge-output", help="合并模型输出目录")
    
    args = parser.parse_args()
    
    # 加载配置
    config = load_config(args.config)
    
    # 命令行参数覆盖
    if args.model:
        config["model_name"] = args.model
    if args.dataset:
        config["dataset_path"] = args.dataset
    if args.output:
        config["output_dir"] = args.output
    if args.epochs:
        config["num_epochs"] = args.epochs
    if args.batch_size:
        config["batch_size"] = args.batch_size
    if args.lr:
        config["learning_rate"] = args.lr
    
    print("=" * 50)
    print("🎓 学习小书童 - SFT微调")
    print("=" * 50)
    print("\n📋 配置:")
    for key, value in config.items():
        print(f"  {key}: {value}")
    print()
    
    # 执行训练
    train(config)
    
    # 可选: 合并权重
    if args.merge:
        merge_output = args.merge_output or f"{config['output_dir']}_merged"
        merge_weights(config, merge_output)


if __name__ == "__main__":
    main()

