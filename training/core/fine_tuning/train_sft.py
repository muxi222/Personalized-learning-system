#!/usr/bin/env python3
"""
Core SFT trainer (module-agnostic).

This script intentionally lives under `training/core/`:
- Training mechanics are shared (QLoRA/SFTTrainer/merge weights)
- Business/persona/system prompts must be provided by module configs

Expected dataset JSONL format (one JSON object per line):
  {"instruction": "...", "input": "...", "output": "..."}
"""

from __future__ import annotations

import argparse
import json
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


DEFAULT_CONFIG = {
    # Base model
    "model_name": "Qwen/Qwen2-7B-Instruct",
    # Data
    "dataset_path": "./data/train.jsonl",
    "output_dir": "./output",
    # Module-specific prompt/persona (keep empty by default; modules should set it)
    "system_prompt": "",
    # LoRA
    "lora_r": 64,
    "lora_alpha": 16,
    "lora_dropout": 0.1,
    "lora_target_modules": [
        "q_proj",
        "k_proj",
        "v_proj",
        "o_proj",
        "gate_proj",
        "up_proj",
        "down_proj",
    ],
    # Training
    "num_epochs": 3,
    "batch_size": 4,
    "gradient_accumulation_steps": 4,
    "learning_rate": 2e-4,
    "max_seq_length": 2048,
    "warmup_ratio": 0.03,
    "weight_decay": 0.001,
    # QLoRA quantization
    "use_4bit": True,
    "bnb_4bit_compute_dtype": "bfloat16",
    "bnb_4bit_quant_type": "nf4",
    "use_nested_quant": False,
}


def load_config(config_path: Optional[str] = None) -> dict:
    config = DEFAULT_CONFIG.copy()
    if config_path and Path(config_path).exists():
        with open(config_path, "r", encoding="utf-8") as f:
            custom_config = json.load(f)
            config.update(custom_config)
    return config


def setup_model_and_tokenizer(config: dict):
    print(f"📦 Loading base model: {config['model_name']}")

    compute_dtype = getattr(torch, str(config["bnb_4bit_compute_dtype"]))
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=bool(config["use_4bit"]),
        bnb_4bit_quant_type=str(config["bnb_4bit_quant_type"]),
        bnb_4bit_compute_dtype=compute_dtype,
        bnb_4bit_use_double_quant=bool(config["use_nested_quant"]),
    )

    model = AutoModelForCausalLM.from_pretrained(
        config["model_name"],
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True,
    )
    model.config.use_cache = False
    model.config.pretraining_tp = 1

    tokenizer = AutoTokenizer.from_pretrained(
        config["model_name"],
        trust_remote_code=True,
    )
    tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    model = prepare_model_for_kbit_training(model)

    peft_config = LoraConfig(
        r=int(config["lora_r"]),
        lora_alpha=int(config["lora_alpha"]),
        lora_dropout=float(config["lora_dropout"]),
        target_modules=list(config["lora_target_modules"]),
        bias="none",
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, peft_config)

    trainable, total = model.get_nb_trainable_parameters()
    pct = (100.0 * float(trainable) / float(total)) if total else 0.0
    print(f"📊 Trainable params: {trainable:,} / {total:,} ({pct:.2f}%)")

    return model, tokenizer, peft_config


def format_sft_example(example: dict, config: dict) -> str:
    """
    Convert one record to a single training text.

    Modules should tune `system_prompt` in config for their subject/persona.
    """
    system_prompt = str(config.get("system_prompt") or "").strip()
    instruction = str(example.get("instruction", "") or "").strip()
    input_text = str(example.get("input", "") or "").strip()
    output_text = str(example.get("output", "") or "").strip()

    if input_text:
        return (
            "### 系统:\n"
            f"{system_prompt}\n\n"
            "### 指令:\n"
            f"{instruction}\n\n"
            "### 输入:\n"
            f"{input_text}\n\n"
            "### 回答:\n"
            f"{output_text}"
        )

    return (
        "### 系统:\n"
        f"{system_prompt}\n\n"
        "### 指令:\n"
        f"{instruction}\n\n"
        "### 回答:\n"
        f"{output_text}"
    )


def train(config: dict):
    model, tokenizer, _peft_config = setup_model_and_tokenizer(config)

    print(f"📂 Loading dataset: {config['dataset_path']}")
    dataset = load_dataset("json", data_files={"train": config["dataset_path"]})["train"]
    print(f"📊 Dataset size: {len(dataset)}")

    training_args = TrainingArguments(
        output_dir=config["output_dir"],
        num_train_epochs=int(config["num_epochs"]),
        per_device_train_batch_size=int(config["batch_size"]),
        gradient_accumulation_steps=int(config["gradient_accumulation_steps"]),
        learning_rate=float(config["learning_rate"]),
        weight_decay=float(config["weight_decay"]),
        warmup_ratio=float(config["warmup_ratio"]),
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

    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=dataset,
        tokenizer=tokenizer,
        formatting_func=lambda x: format_sft_example(x, config),
        max_seq_length=int(config["max_seq_length"]),
        packing=False,
    )

    print("🚀 Starting SFT training ...")
    trainer.train()

    out_dir = str(config["output_dir"])
    print(f"💾 Saving adapters to: {out_dir}")
    trainer.save_model()
    tokenizer.save_pretrained(out_dir)
    print("✅ SFT training completed.")


def merge_weights(config: dict, merge_output_dir: str):
    """
    Merge LoRA adapter into base model weights (optional).
    """
    from peft import PeftModel

    print("📦 Loading base model for merge ...")
    base_model = AutoModelForCausalLM.from_pretrained(
        config["model_name"],
        torch_dtype=torch.bfloat16,
        device_map="auto",
        trust_remote_code=True,
    )

    print(f"📦 Loading LoRA adapters from: {config['output_dir']}")
    model = PeftModel.from_pretrained(base_model, config["output_dir"])

    print("🔗 Merging weights ...")
    merged_model = model.merge_and_unload()

    print(f"💾 Saving merged model to: {merge_output_dir}")
    merged_model.save_pretrained(merge_output_dir)

    tokenizer = AutoTokenizer.from_pretrained(config["model_name"], trust_remote_code=True)
    tokenizer.save_pretrained(merge_output_dir)
    print("✅ Merge completed.")


def main():
    parser = argparse.ArgumentParser(
        description="Core SFT trainer (module-agnostic)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--config", "-c", help="Config JSON path")
    parser.add_argument("--model", "-m", help="Base model name (override)")
    parser.add_argument("--dataset", "-d", help="Training dataset JSONL path (override)")
    parser.add_argument("--output", "-o", help="Output directory (override)")
    parser.add_argument("--epochs", type=int, help="Epochs (override)")
    parser.add_argument("--batch-size", type=int, help="Batch size (override)")
    parser.add_argument("--lr", type=float, help="Learning rate (override)")
    parser.add_argument("--merge", action="store_true", help="Merge LoRA weights after training")
    parser.add_argument("--merge-output", help="Merged model output directory")

    args = parser.parse_args()
    config = load_config(args.config)

    if args.model:
        config["model_name"] = args.model
    if args.dataset:
        config["dataset_path"] = args.dataset
    if args.output:
        config["output_dir"] = args.output
    if args.epochs is not None:
        config["num_epochs"] = args.epochs
    if args.batch_size is not None:
        config["batch_size"] = args.batch_size
    if args.lr is not None:
        config["learning_rate"] = args.lr

    print("=" * 60)
    print("🎓 SFT Fine-tuning (core)")
    print("=" * 60)
    for k, v in config.items():
        if k == "system_prompt" and isinstance(v, str) and len(v) > 160:
            print(f"  {k}: {v[:160]}...(+{len(v)-160} chars)")
        else:
            print(f"  {k}: {v}")
    print()

    train(config)

    if args.merge:
        merge_output = args.merge_output or f"{config['output_dir']}_merged"
        merge_weights(config, merge_output)


if __name__ == "__main__":
    main()

