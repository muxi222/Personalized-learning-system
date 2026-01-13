#!/usr/bin/env python3
"""
QLoRA微调脚本
使用HuggingFace TRL库进行QLoRA微调
"""

import os
import json
import argparse
import inspect
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
from trl import SFTTrainer, DataCollatorForCompletionOnlyLM


# Default configuration
DEFAULT_CONFIG = {
    "model_name": "Qwen/Qwen2-7B-Instruct",  # Base model
    "dataset_path": "./data/train.jsonl",
    "output_dir": "./output",
    # LoRA config
    "lora_r": 64,
    "lora_alpha": 16,
    "lora_dropout": 0.1,
    "lora_target_modules": ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    # Training config
    "num_epochs": 3,
    "batch_size": 4,
    "gradient_accumulation_steps": 4,
    "learning_rate": 2e-4,
    "max_seq_length": 2048,
    "warmup_ratio": 0.03,
    "weight_decay": 0.001,
    # Quantization
    "use_4bit": True,
    "bnb_4bit_compute_dtype": "bfloat16",
    "bnb_4bit_quant_type": "nf4",
    "use_nested_quant": False,
}


def load_config(config_path: Optional[str] = None) -> dict:
    """Load configuration from file or use defaults"""
    config = DEFAULT_CONFIG.copy()

    if config_path and Path(config_path).exists():
        with open(config_path, "r") as f:
            custom_config = json.load(f)
            config.update(custom_config)

    return config


def setup_model_and_tokenizer(config: dict):
    """Setup model with QLoRA configuration"""
    print(f"Loading model: {config['model_name']}")

    # Quantization config
    compute_dtype = getattr(torch, config["bnb_4bit_compute_dtype"])

    bnb_config = BitsAndBytesConfig(
        load_in_4bit=config["use_4bit"],
        bnb_4bit_quant_type=config["bnb_4bit_quant_type"],
        bnb_4bit_compute_dtype=compute_dtype,
        bnb_4bit_use_double_quant=config["use_nested_quant"],
    )

    # Load model
    model = AutoModelForCausalLM.from_pretrained(
        config["model_name"],
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True,
    )
    model.config.use_cache = False
    model.config.pretraining_tp = 1

    # Load tokenizer
    tokenizer = AutoTokenizer.from_pretrained(
        config["model_name"],
        trust_remote_code=True,
    )
    tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    # Prepare model for k-bit training
    model = prepare_model_for_kbit_training(model)

    # LoRA config
    peft_config = LoraConfig(
        r=config["lora_r"],
        lora_alpha=config["lora_alpha"],
        lora_dropout=config["lora_dropout"],
        target_modules=config["lora_target_modules"],
        bias="none",
        task_type="CAUSAL_LM",
    )

    # Apply LoRA
    model = get_peft_model(model, peft_config)

    # Print trainable parameters
    trainable, total = model.get_nb_trainable_parameters()
    print(f"Trainable parameters: {trainable:,} / {total:,} ({100 * trainable / total:.2f}%)")

    return model, tokenizer, peft_config


def format_alpaca_prompt(example: dict, tokenizer) -> str:
    """Format example as Alpaca-style prompt"""
    prompt = f"""### 指令:
{example['instruction']}

### 输入:
{example['input']}

### 回答:
{example['output']}"""
    return prompt


def format_sharegpt_prompt(example: dict, tokenizer) -> str:
    """Format example as chat template"""
    messages = []
    for conv in example.get("conversations", []):
        role = "user" if conv["from"] == "human" else "assistant"
        messages.append({"role": role, "content": conv["value"]})

    return tokenizer.apply_chat_template(messages, tokenize=False)


def train(config: dict):
    """Run training"""
    # Setup
    model, tokenizer, peft_config = setup_model_and_tokenizer(config)

    # Load dataset
    print(f"Loading dataset from: {config['dataset_path']}")
    dataset = load_dataset("json", data_files={
        "train": config["dataset_path"],
    })["train"]

    # Determine format and create formatting function
    sample = dataset[0]
    if "conversations" in sample:
        format_func = lambda x: format_sharegpt_prompt(x, tokenizer)
    else:
        format_func = lambda x: format_alpaca_prompt(x, tokenizer)

    # Training arguments
    ta_sig = inspect.signature(TrainingArguments.__init__)
    training_args_kwargs = dict(
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
        bf16=True,
        tf32=True,
        max_grad_norm=0.3,
        group_by_length=True,
        report_to="tensorboard",
        optim="paged_adamw_32bit",
    )
    if "eval_strategy" in ta_sig.parameters:
        training_args_kwargs["eval_strategy"] = "no"
    else:
        training_args_kwargs["evaluation_strategy"] = "no"
    training_args = TrainingArguments(**training_args_kwargs)

    # Create trainer
    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=dataset,
        tokenizer=tokenizer,
        formatting_func=format_func,
        max_seq_length=config["max_seq_length"],
        packing=False,
    )

    # Train
    print("Starting training...")
    trainer.train()

    # Save
    print(f"Saving model to {config['output_dir']}")
    trainer.save_model()
    tokenizer.save_pretrained(config["output_dir"])

    print("Training completed!")


def merge_and_save(config: dict, merge_output_dir: str):
    """Merge LoRA weights and save full model"""
    from peft import PeftModel

    print("Loading base model...")
    base_model = AutoModelForCausalLM.from_pretrained(
        config["model_name"],
        torch_dtype=torch.bfloat16,
        device_map="auto",
        trust_remote_code=True,
    )

    print(f"Loading LoRA weights from {config['output_dir']}...")
    model = PeftModel.from_pretrained(base_model, config["output_dir"])

    print("Merging weights...")
    merged_model = model.merge_and_unload()

    print(f"Saving merged model to {merge_output_dir}...")
    merged_model.save_pretrained(merge_output_dir)

    # Save tokenizer
    tokenizer = AutoTokenizer.from_pretrained(config["model_name"])
    tokenizer.save_pretrained(merge_output_dir)

    print("Merge completed!")


def main():
    parser = argparse.ArgumentParser(description="QLoRA Fine-tuning Script")
    parser.add_argument("--config", "-c", help="Path to config file")
    parser.add_argument("--model", "-m", help="Model name or path")
    parser.add_argument("--dataset", "-d", help="Training dataset path")
    parser.add_argument("--output", "-o", help="Output directory")
    parser.add_argument("--epochs", type=int, help="Number of epochs")
    parser.add_argument("--batch-size", type=int, help="Batch size")
    parser.add_argument("--lr", type=float, help="Learning rate")
    parser.add_argument(
        "--merge",
        action="store_true",
        help="Merge LoRA weights after training",
    )
    parser.add_argument(
        "--merge-output",
        help="Output directory for merged model",
    )

    args = parser.parse_args()

    # Load config
    config = load_config(args.config)

    # Override with command line arguments
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

    print("Configuration:")
    for key, value in config.items():
        print(f"  {key}: {value}")

    # Run training
    train(config)

    # Optionally merge weights
    if args.merge:
        merge_output = args.merge_output or f"{config['output_dir']}_merged"
        merge_and_save(config, merge_output)


if __name__ == "__main__":
    main()

