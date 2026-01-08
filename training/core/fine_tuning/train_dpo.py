#!/usr/bin/env python3
"""
DPO/ORPO training script (preference optimization).

This is the "best-practice" next step after SFT:
- Use human preference data when available (feedbacks.preferred_response)
- Or generate AI preference pairs (RLAIF) using a rubric + model sampling (see TODOs)

Input JSONL format (TRL-compatible):
{"prompt": "...", "chosen": "...", "rejected": "..."}
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional

import torch
from datasets import load_dataset
from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments, BitsAndBytesConfig
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training


DEFAULT_CONFIG = {
    "method": "dpo",  # "dpo" or "orpo" (trl supports ORPOTrainer in newer versions)
    "model_name": "Qwen/Qwen2-7B-Instruct",
    "dataset_path": "./data/preference.jsonl",
    "output_dir": "./output/dpo_lora",

    "lora_r": 64,
    "lora_alpha": 16,
    "lora_dropout": 0.05,
    "lora_target_modules": ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],

    "num_epochs": 1,
    "batch_size": 1,
    "gradient_accumulation_steps": 16,
    "learning_rate": 1e-5,
    "max_seq_length": 2048,

    # QLoRA
    "use_4bit": True,
    "bnb_4bit_compute_dtype": "bfloat16",
    "bnb_4bit_quant_type": "nf4",
    "use_nested_quant": False,

    # DPO specifics
    "beta": 0.1,
}


def load_config(config_path: Optional[str]) -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if config_path and Path(config_path).exists():
        with open(config_path, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    return cfg


def setup_model_and_tokenizer(cfg: dict):
    compute_dtype = getattr(torch, cfg["bnb_4bit_compute_dtype"])
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=cfg["use_4bit"],
        bnb_4bit_quant_type=cfg["bnb_4bit_quant_type"],
        bnb_4bit_compute_dtype=compute_dtype,
        bnb_4bit_use_double_quant=cfg["use_nested_quant"],
    )

    model = AutoModelForCausalLM.from_pretrained(
        cfg["model_name"],
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True,
    )
    model.config.use_cache = False

    tokenizer = AutoTokenizer.from_pretrained(cfg["model_name"], trust_remote_code=True)
    tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    model = prepare_model_for_kbit_training(model)
    peft_config = LoraConfig(
        r=cfg["lora_r"],
        lora_alpha=cfg["lora_alpha"],
        lora_dropout=cfg["lora_dropout"],
        target_modules=cfg["lora_target_modules"],
        bias="none",
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, peft_config)
    return model, tokenizer


def train(cfg: dict):
    method = (cfg.get("method") or "dpo").lower()
    if method not in {"dpo", "orpo"}:
        raise ValueError("method must be 'dpo' or 'orpo'")

    model, tokenizer = setup_model_and_tokenizer(cfg)

    dataset = load_dataset("json", data_files={"train": cfg["dataset_path"]})["train"]
    print(f"📊 preference dataset size: {len(dataset)}")

    training_args = TrainingArguments(
        output_dir=cfg["output_dir"],
        num_train_epochs=cfg["num_epochs"],
        per_device_train_batch_size=cfg["batch_size"],
        gradient_accumulation_steps=cfg["gradient_accumulation_steps"],
        learning_rate=cfg["learning_rate"],
        logging_steps=10,
        save_strategy="epoch",
        evaluation_strategy="no",
        bf16=True,
        tf32=True,
        report_to="tensorboard",
        optim="paged_adamw_32bit",
    )

    if method == "dpo":
        from trl import DPOTrainer

        trainer = DPOTrainer(
            model=model,
            args=training_args,
            train_dataset=dataset,
            tokenizer=tokenizer,
            beta=float(cfg.get("beta", 0.1)),
            max_length=int(cfg["max_seq_length"]),
            max_prompt_length=min(1024, int(cfg["max_seq_length"] // 2)),
        )
    else:
        # TRL ORPOTrainer version compatibility varies. Keep as a guided TODO.
        # TODO: if your trl version supports ORPOTrainer, switch to it here.
        raise NotImplementedError(
            "ORPOTrainer is not wired by default. Use DPO first, or upgrade trl and implement ORPOTrainer here."
        )

    print("🚀 starting preference optimization...")
    trainer.train()
    trainer.save_model()
    tokenizer.save_pretrained(cfg["output_dir"])
    print("✅ done")


def main():
    parser = argparse.ArgumentParser(description="DPO/ORPO trainer (preference optimization)")
    parser.add_argument("--config", "-c", help="Config JSON path")
    args = parser.parse_args()

    cfg = load_config(args.config)
    train(cfg)


if __name__ == "__main__":
    main()

