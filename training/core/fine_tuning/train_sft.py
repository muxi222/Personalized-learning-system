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
import inspect
import json
import os
from pathlib import Path
from typing import Optional

import torch
from datasets import load_dataset
from transformers import (
    AutoModelForCausalLM,
    AutoConfig,
    AutoTokenizer,
    BitsAndBytesConfig,
    TrainingArguments,
)

# Dependency compatibility guard (keep the error actionable).
#
# Qwen3 models require a recent transformers that recognizes model_type="qwen3".
# Verified working set in this repo's Python 3.12 env (312_edu):
#   transformers>=4.57.0
#   peft>=0.18.1
#   trl>=0.27.0
try:
    import transformers as _tfm
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
except Exception as e:
    raise RuntimeError(
        "Fine-tuning dependency mismatch detected (failed to import transformers/peft).\n\n"
        "Fix (recommended set for Qwen3):\n"
        "  pip install -U 'transformers>=4.57.0' 'peft>=0.18.1' 'trl>=0.27.0'\n\n"
        "Debug:\n"
        f"  transformers_version={getattr(_tfm, '__version__', 'unknown')}\n"
        f"  original_error={repr(e)}\n"
    ) from e

from trl import SFTTrainer


from training.core.fine_tuning.hf_download import (
    prefetch_model_snapshot,
    resolve_preferred_model_dir,
)


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
    # HF download
    "hf_max_workers": 32,
    "hf_revision": "main",
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

    # Prefer a local cached snapshot if present to avoid any hub network requests.
    model_ref: str | Path = str(config["model_name"])
    revision = str(config.get("hf_revision") or "main")
    preferred = resolve_preferred_model_dir(str(config["model_name"]), revision=revision)
    if preferred is None:
        # If snapshot is missing/incomplete, try to prefetch (resume + parallel workers)
        # so training doesn't fail halfway through model/tokenizer download.
        prefetch_workers = int(config.get("hf_max_workers") or 8)
        etag_timeout = float(os.environ.get("HF_HUB_ETAG_TIMEOUT") or 60)
        prefetch_model_snapshot(
            str(config["model_name"]),
            max_workers=prefetch_workers,
            etag_timeout=etag_timeout,
            revision=revision,
        )
        preferred = resolve_preferred_model_dir(str(config["model_name"]), revision=revision)
        if preferred is None and "/" in str(config["model_name"]):
            raise RuntimeError(
                "Model snapshot is still incomplete after resumable prefetch attempts.\n"
                f"- model: {config['model_name']}\n"
                f"- HF_HOME: {os.environ.get('HF_HOME')}\n"
                f"- HF_HUB_CACHE: {os.environ.get('HF_HUB_CACHE')}\n\n"
                "Suggestions:\n"
                "- Retry with fewer workers (often more stable): add `--hf-max-workers 4` (or 2/1)\n"
                "- If huggingface.co is unstable/blocked, set a mirror endpoint via env `HF_ENDPOINT` and retry\n"
                "- Ensure the cache has no lingering `.incomplete` blobs once download finishes\n"
            )
    if preferred is not None:
        print(f"📦 Using local model dir: {preferred}")
        model_ref = preferred

    # bfloat16 is not supported on some GPUs; fall back to fp16 automatically.
    compute_dtype_name = str(config.get("bnb_4bit_compute_dtype") or "bfloat16")
    if compute_dtype_name == "bfloat16" and hasattr(torch.cuda, "is_bf16_supported") and not torch.cuda.is_bf16_supported():
        compute_dtype_name = "float16"
    compute_dtype = getattr(torch, compute_dtype_name)

    if not torch.cuda.is_available():
        raise RuntimeError(
            "CUDA is not available, but this SFT recipe uses 4-bit quantization + device_map='auto' (QLoRA).\n"
            "Please run on a machine with an NVIDIA GPU + CUDA, or switch to a smaller base model.\n"
            f"- model: {config['model_name']}\n"
            f"- use_4bit: {config.get('use_4bit')}\n"
        )
    try:
        p = torch.cuda.get_device_properties(torch.cuda.current_device())
        vram_gb = p.total_memory / (1024**3)
        print(f"🖥️  CUDA device: {p.name} (VRAM={vram_gb:.1f} GB)")
    except Exception:
        pass
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=bool(config["use_4bit"]),
        bnb_4bit_quant_type=str(config["bnb_4bit_quant_type"]),
        bnb_4bit_compute_dtype=compute_dtype,
        bnb_4bit_use_double_quant=bool(config["use_nested_quant"]),
    )

    def _load_model(device_map={"": 0}, **extra_kwargs):
        return AutoModelForCausalLM.from_pretrained(
            model_ref,
            quantization_config=bnb_config,
            device_map=device_map,
            trust_remote_code=True,
            local_files_only=bool(preferred is not None),
            **extra_kwargs,
        )

    try:
        model = _load_model()
    except ValueError as e:
        msg = str(e) or ""
        # transformers/bnb guard: when GPU VRAM is not enough, parts may be dispatched to CPU/disk.
        # Enable FP32 CPU offload explicitly and retry (best-effort).
        if "dispatched on the cpu or the disk" in msg.lower():
            offload_dir = Path(os.environ.get("SFT_OFFLOAD_DIR") or "./data/offload").resolve()
            offload_dir.mkdir(parents=True, exist_ok=True)
            print("⚠️  GPU VRAM seems insufficient for the quantized model with device_map='auto'.")
            print("⚠️  Retrying with CPU offload enabled + custom device_map (may be slower).")
            print(f"⚠️  Offload dir: {offload_dir}")
            # NOTE: bitsandbytes 4bit requires a *custom* device_map when offloading,
            # `device_map="auto"` is not sufficient (will raise the same error again).
            try:
                from accelerate import infer_auto_device_map, init_empty_weights
            except Exception as ie:
                raise RuntimeError(
                    "GPU VRAM is currently not enough to load the quantized model while keeping all modules on GPU.\n"
                    "This often happens when a vLLM server is already running and occupies most VRAM.\n\n"
                    "Fix options:\n"
                    "1) Stop the running model server, then retry training:\n"
                    "   ./deploy/scripts/pipeline.sh serve-model --module tony down\n"
                    "2) Or train on a different GPU by setting CUDA_VISIBLE_DEVICES.\n"
                    "3) Or install accelerate and retry to enable safe CPU offload:\n"
                    "   pip install -U accelerate\n\n"
                    f"original_error={repr(e)}\n"
                    f"accelerate_import_error={repr(ie)}\n"
                ) from e

            # Estimate per-device memory (prefer free VRAM to avoid immediate OOM).
            free_b, total_b = torch.cuda.mem_get_info()
            free_gib = max(1, int((free_b / (1024**3)) - 2))  # keep some headroom
            max_memory = {0: f"{free_gib}GiB", "cpu": "128GiB"}

            cfg = AutoConfig.from_pretrained(
                model_ref,
                trust_remote_code=True,
                local_files_only=bool(preferred is not None),
            )
            with init_empty_weights():
                empty_model = AutoModelForCausalLM.from_config(cfg, trust_remote_code=True)
            no_split = getattr(empty_model, "_no_split_modules", None) or []
            device_map = infer_auto_device_map(
                empty_model,
                max_memory=max_memory,
                no_split_module_classes=no_split,
            )

            model = _load_model(
                device_map=device_map,
                max_memory=max_memory,
                #llm_int8_enable_fp32_cpu_offload=True,
                offload_folder=str(offload_dir),
            )
        else:
            raise
    model.config.use_cache = False
    model.config.pretraining_tp = 1

    tokenizer = AutoTokenizer.from_pretrained(
        model_ref,
        trust_remote_code=True,
        local_files_only=bool(preferred is not None),
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

    # TRL >= 0.26 uses SFTConfig (which already uses eval_strategy) + processing_class.
    # Fall back to transformers.TrainingArguments for older TRL.
    max_steps = int(config.get("max_steps") or -1)
    sft_sig = inspect.signature(SFTTrainer.__init__)
    if "processing_class" in sft_sig.parameters:
        from trl.trainer.sft_config import SFTConfig  # local import to keep compatibility

        training_args = SFTConfig(
            output_dir=str(config["output_dir"]),
            num_train_epochs=float(config["num_epochs"]),
            per_device_train_batch_size=int(config["batch_size"]),
            gradient_accumulation_steps=int(config["gradient_accumulation_steps"]),
            learning_rate=float(config["learning_rate"]),
            weight_decay=float(config["weight_decay"]),
            warmup_ratio=float(config["warmup_ratio"]),
            lr_scheduler_type="cosine",
            logging_steps=10,
            save_strategy="epoch",
            eval_strategy="no",
            bf16=True,
            tf32=True,
            max_grad_norm=0.3,
            report_to="tensorboard",
            optim="paged_adamw_32bit",
            max_length=int(config["max_seq_length"]),
            packing=False,
            max_steps=max_steps,
        )
    else:  # pragma: no cover
        # transformers compatibility:
        # - older versions use `evaluation_strategy`
        # - newer versions (e.g. 4.57+) renamed it to `eval_strategy`
        ta_sig = inspect.signature(TrainingArguments.__init__)
        training_args_kwargs = dict(
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
            bf16=True,
            tf32=True,
            max_grad_norm=0.3,
            group_by_length=True,
            report_to="tensorboard",
            optim="paged_adamw_32bit",
        )
        if max_steps and max_steps > 0:
            training_args_kwargs["max_steps"] = max_steps
        if "eval_strategy" in ta_sig.parameters:
            training_args_kwargs["eval_strategy"] = "no"
        else:
            training_args_kwargs["evaluation_strategy"] = "no"
        training_args = TrainingArguments(**training_args_kwargs)

    # TRL compatibility:
    # - older versions accepted `tokenizer=...`
    # - newer versions (trl>=0.26) use `processing_class=...` and removed tokenizer/max_seq_length/packing.
    sft_kwargs = dict(
        model=model,
        args=training_args,
        train_dataset=dataset,
        formatting_func=lambda x: format_sft_example(x, config),
    )
    if "processing_class" in sft_sig.parameters:
        sft_kwargs["processing_class"] = tokenizer
    else:  # pragma: no cover
        sft_kwargs["tokenizer"] = tokenizer
    trainer = SFTTrainer(**sft_kwargs)

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
    parser.add_argument("--max-steps", type=int, help="Optional max_steps override (for smoke runs)")
    parser.add_argument("--hf-max-workers", type=int, help="Max parallel download workers for HF snapshot_download (default: 32)")
    parser.add_argument("--hf-revision", help="HF model revision (default: main). Use commit hash/tag to pin snapshots.")

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
    if args.max_steps is not None:
        config["max_steps"] = int(args.max_steps)
    if args.hf_max_workers is not None:
        config["hf_max_workers"] = int(args.hf_max_workers)
    if args.hf_revision:
        config["hf_revision"] = str(args.hf_revision)

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

