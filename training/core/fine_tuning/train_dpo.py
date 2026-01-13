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
import inspect
import json
import os
from pathlib import Path
from typing import Optional

import torch
from datasets import load_dataset
from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments, BitsAndBytesConfig
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training

from training.core.fine_tuning.hf_download import prefetch_model_snapshot, resolve_preferred_model_dir


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
    # HF download
    "hf_max_workers": 32,
    "hf_revision": "main",
}


def _validate_preference_dataset_or_raise(dataset_path: str) -> None:
    """
    DPO requires a non-empty preference dataset. If the JSONL is empty,
    `datasets.load_dataset(..., "json")` throws SchemaInferenceError, which is
    confusing for users. Provide a clear, actionable error instead.
    """
    p = Path(str(dataset_path))
    if not p.exists():
        raise FileNotFoundError(
            "Preference dataset not found.\n"
            f"- expected: {p}\n\n"
            "Suggestions:\n"
            "- Generate it from app feedbacks:\n"
            "  ./deploy/scripts/pipeline.sh datasets --module tony\n"
            "- Or run the generator directly:\n"
            "  python training/modules/tony/datasets/scripts/prepare_preferences.py --output "
            f"{p}\n"
        )

    # Find the first non-empty line (JSON object) to validate schema.
    first = None
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            s = (line or "").strip()
            if s:
                first = s
                break

    if not first:
        raise RuntimeError(
            "Preference dataset is empty (0 examples), cannot run DPO.\n"
            f"- dataset_path: {p}\n\n"
            "Most common reason:\n"
            "- No usable preference feedbacks yet (feedbacks.preferred_response/original_response empty).\n\n"
            "Next steps:\n"
            "- Use the app to collect feedback pairs, then regenerate:\n"
            "  ./deploy/scripts/pipeline.sh datasets --module tony\n"
            "- Verify generator output is >0:\n"
            "  python training/modules/tony/datasets/scripts/prepare_preferences.py\n"
        )

    try:
        obj = json.loads(first)
    except Exception as e:
        raise RuntimeError(
            "Preference dataset JSONL first non-empty line is not valid JSON.\n"
            f"- dataset_path: {p}\n"
            f"- line: {first[:200]}{'...' if len(first) > 200 else ''}\n"
            f"- error: {e}\n"
        ) from e

    missing = [k for k in ("prompt", "chosen", "rejected") if not obj.get(k)]
    if missing:
        raise RuntimeError(
            "Preference dataset schema looks invalid for TRL DPOTrainer.\n"
            f"- dataset_path: {p}\n"
            f"- missing/empty fields in first example: {missing}\n\n"
            "Expected JSONL format:\n"
            '{"prompt": "...", "chosen": "...", "rejected": "..."}\n'
        )


def load_config(config_path: Optional[str]) -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if config_path and Path(config_path).exists():
        with open(config_path, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    return cfg


def setup_model_and_tokenizer(cfg: dict):
    # Best-effort: ensure model snapshot is fully cached before training starts.
    # This avoids training runs failing mid-way due to flaky model downloads.
    model_ref = str(cfg["model_name"])
    revision = str(cfg.get("hf_revision") or "main")
    preferred = resolve_preferred_model_dir(model_ref, revision=revision)
    if preferred is None and "/" in model_ref:
        prefetch_workers = int(cfg.get("hf_max_workers") or 8)
        etag_timeout = float(os.environ.get("HF_HUB_ETAG_TIMEOUT") or 60)
        prefetch_model_snapshot(
            model_ref, max_workers=prefetch_workers, etag_timeout=etag_timeout, revision=revision
        )
        preferred = resolve_preferred_model_dir(model_ref, revision=revision)
    if preferred is not None:
        model_ref = preferred

    compute_dtype = getattr(torch, cfg["bnb_4bit_compute_dtype"])
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=cfg["use_4bit"],
        bnb_4bit_quant_type=cfg["bnb_4bit_quant_type"],
        bnb_4bit_compute_dtype=compute_dtype,
        bnb_4bit_use_double_quant=cfg["use_nested_quant"],
    )

    model = AutoModelForCausalLM.from_pretrained(
        model_ref,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True,
        local_files_only=bool(preferred is not None),
    )
    model.config.use_cache = False

    tokenizer = AutoTokenizer.from_pretrained(
        model_ref, trust_remote_code=True, local_files_only=bool(preferred is not None)
    )
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

    _validate_preference_dataset_or_raise(cfg["dataset_path"])
    dataset = load_dataset("json", data_files={"train": cfg["dataset_path"]})["train"]
    print(f"📊 preference dataset size: {len(dataset)}")

    if method == "dpo":
        from trl import DPOTrainer
        dpo_sig = inspect.signature(DPOTrainer.__init__)

        # TRL version compatibility:
        # - Newer TRL (e.g. 0.26.x) uses DPOConfig and `processing_class`
        # - Older TRL used TrainingArguments + `tokenizer` and accepted beta/max_length kwargs
        if "processing_class" in dpo_sig.parameters:
            from trl.trainer.dpo_config import DPOConfig

            max_steps = int(cfg.get("max_steps") or -1)
            dpo_config = DPOConfig(
                output_dir=str(cfg["output_dir"]),
                num_train_epochs=float(cfg["num_epochs"]),
                per_device_train_batch_size=int(cfg["batch_size"]),
                gradient_accumulation_steps=int(cfg["gradient_accumulation_steps"]),
                learning_rate=float(cfg["learning_rate"]),
                logging_steps=10,
                save_strategy="epoch",
                eval_strategy="no",
                bf16=True,
                tf32=True,
                report_to="tensorboard",
                optim="paged_adamw_32bit",
                max_steps=int(max_steps),
                max_length=int(cfg["max_seq_length"]),
                max_prompt_length=min(1024, int(cfg["max_seq_length"] // 2)),
                beta=float(cfg.get("beta", 0.1)),
            )
            dpo_kwargs = dict(
                model=model,
                args=dpo_config,
                train_dataset=dataset,
                processing_class=tokenizer,
            )
            trainer = DPOTrainer(**dpo_kwargs)
        else:  # pragma: no cover
            # transformers compatibility: `evaluation_strategy` renamed to `eval_strategy` in newer versions.
            ta_sig = inspect.signature(TrainingArguments.__init__)
            training_args_kwargs = dict(
                output_dir=cfg["output_dir"],
                num_train_epochs=cfg["num_epochs"],
                per_device_train_batch_size=cfg["batch_size"],
                gradient_accumulation_steps=cfg["gradient_accumulation_steps"],
                learning_rate=cfg["learning_rate"],
                logging_steps=10,
                save_strategy="epoch",
                bf16=True,
                tf32=True,
                report_to="tensorboard",
                optim="paged_adamw_32bit",
            )
            max_steps = int(cfg.get("max_steps") or -1)
            if max_steps and max_steps > 0:
                training_args_kwargs["max_steps"] = max_steps
            if "eval_strategy" in ta_sig.parameters:
                training_args_kwargs["eval_strategy"] = "no"
            else:
                training_args_kwargs["evaluation_strategy"] = "no"
            training_args = TrainingArguments(**training_args_kwargs)

            dpo_kwargs = dict(
                model=model,
                args=training_args,
                train_dataset=dataset,
                tokenizer=tokenizer,
                beta=float(cfg.get("beta", 0.1)),
                max_length=int(cfg["max_seq_length"]),
                max_prompt_length=min(1024, int(cfg["max_seq_length"] // 2)),
            )
            trainer = DPOTrainer(**dpo_kwargs)
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
    parser.add_argument("--max-steps", type=int, help="Optional max_steps override (for smoke runs)")
    args = parser.parse_args()

    cfg = load_config(args.config)
    if args.max_steps is not None:
        cfg["max_steps"] = int(args.max_steps)
    train(cfg)


if __name__ == "__main__":
    main()

