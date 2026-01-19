"""
HuggingFace Hub download helpers (resumable / cache-first).

Goal:
- Avoid re-downloading large base models (e.g. OpenPipe/Qwen3-14B-Instruct)
- Support flaky networks: if download is interrupted, next run should continue
- Prefer local cache snapshot for training to avoid any network calls mid-run

This file is used by:
- training/core/fine_tuning/train_sft.py
- training/core/fine_tuning/train_dpo.py
"""

from __future__ import annotations

import json
import os
import time
from fnmatch import fnmatch
from pathlib import Path
from typing import Optional


def _local_dir_for_model(model_id: str) -> Optional[Path]:
    """
    Optional stable local directory for a model, controlled by env `HF_MODEL_LOCAL_DIR`.
    This is useful to make "resume" visible and to avoid relying on snapshot selection logic.
    """
    base = os.environ.get("HF_MODEL_LOCAL_DIR") or ""
    base = str(base).strip()
    model_id = str(model_id or "").strip()
    if not base or not model_id or "/" not in model_id:
        return None
    org, repo = model_id.split("/", 1)
    if not org or not repo:
        return None
    return Path(base) / f"{org}--{repo}"


def _is_complete_model_dir(model_dir: Path) -> bool:
    """
    Heuristic completeness check for a model directory (either HF snapshot or local_dir).
    """
    if not model_dir.exists() or not model_dir.is_dir():
        return False
    idx = model_dir / "model.safetensors.index.json"
    if idx.exists():
        try:
            data = json.loads(idx.read_text(encoding="utf-8"))
            weights = data.get("weight_map") or {}
            shard_files = sorted({Path(v).name for v in weights.values() if isinstance(v, str) and v})
            if shard_files and not all((model_dir / f).exists() for f in shard_files):
                return False
            return True
        except Exception:
            return False
    if (model_dir / "model.safetensors").exists() or (model_dir / "pytorch_model.bin").exists():
        return True
    return False


def _model_cache_root(model_id: str) -> Optional[Path]:
    """
    Return HF hub cache root for a model:
      $HF_HUB_CACHE/models--org--repo
    """
    model_id = str(model_id or "").strip()
    if not model_id or "/" not in model_id:
        return None
    org, repo = model_id.split("/", 1)
    if not org or not repo:
        return None
    hf_home = Path(os.environ.get("HF_HOME") or (Path.home() / ".cache" / "huggingface"))
    hub_dir = Path(os.environ.get("HF_HUB_CACHE") or (hf_home / "hub"))
    return hub_dir / f"models--{org}--{repo}"


def _snapshot_missing_shards(snapshot_dir: Path) -> list[str]:
    """
    Return a list of missing shard filenames for a HF snapshot directory.
    This is purely local/offline inspection (no Hub calls).
    """
    snapshot_dir = Path(snapshot_dir)
    if not snapshot_dir.exists() or not snapshot_dir.is_dir():
        return ["<snapshot_dir_not_found>"]
    idx = snapshot_dir / "model.safetensors.index.json"
    if idx.exists():
        try:
            data = json.loads(idx.read_text(encoding="utf-8"))
            weights = data.get("weight_map") or {}
            shard_files = sorted({Path(v).name for v in weights.values() if isinstance(v, str) and v})
            missing = [f for f in shard_files if not (snapshot_dir / f).exists()]
            return missing
        except Exception:
            return ["<failed_to_parse_index_json>"]
    # Non-sharded forms: treat "model.safetensors"/"pytorch_model.bin" as the minimum.
    if (snapshot_dir / "model.safetensors").exists() or (snapshot_dir / "pytorch_model.bin").exists():
        return []
    return ["<weights_missing>"]


def _describe_cache_status(model_id: str, *, revision: Optional[str]) -> str:
    """
    Return a short human-readable summary about the local cache state for this model.
    Useful to reassure users about resumable downloads and to debug incomplete shards.
    """
    root = _model_cache_root(model_id)
    if root is None:
        return "cache: <not_a_hf_repo_id>"
    parts: list[str] = [f"cache_root={root}"]
    rev = (revision or "").strip()
    if rev:
        ref = root / "refs" / rev
        if ref.exists():
            sha = ref.read_text(encoding="utf-8").strip()
            parts.append(f"ref[{rev}]={sha or '<empty>'}")
            if sha:
                snap = root / "snapshots" / sha
                if snap.exists():
                    missing = _snapshot_missing_shards(snap)
                    if not missing:
                        parts.append("snapshot=complete")
                    else:
                        show = ", ".join(missing[:5])
                        more = f" (+{len(missing)-5})" if len(missing) > 5 else ""
                        parts.append(f"snapshot=incomplete missing={show}{more}")
                else:
                    parts.append("snapshot_dir_missing_for_ref")
        else:
            parts.append(f"ref[{rev}]=<missing>")
    # Check for incomplete blob files (common marker for interrupted downloads).
    blobs = root / "blobs"
    if blobs.exists():
        try:
            inc = sorted(p.name for p in blobs.glob("*.incomplete"))
            if inc:
                parts.append(f"incomplete_blobs={len(inc)}")
        except Exception:
            pass
    return " | ".join(parts)


def _match_allow_patterns(path_in_repo: str, allow_patterns: list[str]) -> bool:
    # Mirror huggingface_hub allow_patterns behavior (glob-style matching).
    p = str(path_in_repo or "")
    return any(fnmatch(p, pat) for pat in allow_patterns)


def _count_existing_missing_files(
    *, model_id: str, local_dir: Path, allow_patterns: list[str], revision: Optional[str]
) -> tuple[int, int, Optional[int]]:
    """
    Return (existing, missing, total) for files matching allow_patterns.

    - If repo file listing fails (offline / auth / network), returns (existing, 0, None)
      where existing is the number of local files currently present under local_dir.
    """
    # local existing count (best-effort)
    try:
        existing_local = sum(1 for p in local_dir.rglob("*") if p.is_file())
    except Exception:
        existing_local = 0

    try:
        from huggingface_hub import HfApi

        api = HfApi()
        repo_files = api.list_repo_files(repo_id=model_id, revision=revision)
        wanted = [f for f in repo_files if _match_allow_patterns(f, allow_patterns)]
        total = len(wanted)
        existing = 0
        for f in wanted:
            if (local_dir / f).exists():
                existing += 1
        missing = total - existing
        return existing, missing, total
    except Exception:
        return existing_local, 0, None


def _best_effort_snapshot_dir(model_id: str, *, revision: Optional[str]) -> Optional[Path]:
    """
    Return a snapshot dir even if incomplete (for progress reporting).
    Preference:
    1) refs/<revision> -> snapshots/<sha> if present
    2) newest snapshots/<sha> directory if any
    """
    model_root = _model_cache_root(model_id)
    if model_root is None:
        return None
    snaps = model_root / "snapshots"
    if not snaps.exists():
        return None
    rev = (revision or "").strip()
    if rev:
        ref = model_root / "refs" / rev
        try:
            if ref.exists():
                sha = ref.read_text(encoding="utf-8").strip()
                if sha:
                    p = snaps / sha
                    if p.exists() and p.is_dir():
                        return p
        except Exception:
            pass
    try:
        cands = [p for p in snaps.iterdir() if p.is_dir()]
        if not cands:
            return None
        cands.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return cands[0]
    except Exception:
        return None


def _count_existing_missing_in_hub_snapshot(
    *, model_id: str, allow_patterns: list[str], revision: Optional[str]
) -> tuple[int, int, Optional[int]]:
    """
    Best-effort progress counter using:
    - remote repo file listing (HfApi.list_repo_files)
    - local hub snapshot directory (refs/<revision> preferred, otherwise newest snapshot)
    Returns (existing, missing, total) where total may be None if remote listing fails.
    """
    snap = _best_effort_snapshot_dir(model_id, revision=revision)
    # local existing count (best-effort)
    existing_local = 0
    if snap is not None and snap.exists():
        try:
            existing_local = sum(1 for p in snap.rglob("*") if p.is_file())
        except Exception:
            existing_local = 0

    try:
        from huggingface_hub import HfApi

        api = HfApi()
        repo_files = api.list_repo_files(repo_id=model_id, revision=revision)
        wanted = [f for f in repo_files if _match_allow_patterns(f, allow_patterns)]
        total = len(wanted)
        if snap is None:
            return 0, total, total
        existing = 0
        for f in wanted:
            if (snap / f).exists():
                existing += 1
        missing = total - existing
        return existing, missing, total
    except Exception:
        return existing_local, 0, None


def resolve_preferred_model_dir(model_id: str, *, revision: Optional[str] = "main") -> Optional[Path]:
    """
    Resolve a fully-downloaded local directory to load from.
    Priority:
    1) `HF_MODEL_LOCAL_DIR/<org>--<repo>` if complete
    2) HuggingFace snapshot cache if complete
    """
    model_id = str(model_id or "").strip()
    local_dir = _local_dir_for_model(model_id)
    if local_dir is not None and _is_complete_model_dir(local_dir):
        return local_dir
    snap = resolve_hf_model_snapshot_dir(model_id, revision=revision)
    if snap is not None and _is_complete_model_dir(snap):
        return snap
    return None


def resolve_hf_model_snapshot_dir(model_id: str, *, revision: Optional[str] = None) -> Optional[Path]:
    """
    If `model_id` is a HF repo id like "org/name", try to resolve its local snapshot dir:
      $HF_HUB_CACHE/models--org--name/snapshots/<sha>

    Returns None if:
    - model is not cached
    - snapshot is incomplete (e.g. missing shards / .incomplete blobs)
    """
    model_id = str(model_id or "").strip()
    model_root = _model_cache_root(model_id)
    if model_root is None:
        return None
    snapshots_dir = model_root / "snapshots"
    if not snapshots_dir.exists():
        return None

    # If caller provides a revision name (default: main), prefer the snapshot pointed to by refs/<revision>.
    # This guarantees stable snapshots/<sha> across retries unless the upstream revision moves.
    if revision:
        try:
            ref_path = model_root / "refs" / str(revision)
            if ref_path.exists():
                sha = ref_path.read_text(encoding="utf-8").strip()
                if sha:
                    snap = snapshots_dir / sha
                    if snap.exists() and snap.is_dir():
                        # Validate shard symlinks via index if present; otherwise check single-file weights.
                        idx = snap / "model.safetensors.index.json"
                        if idx.exists():
                            data = json.loads(idx.read_text(encoding="utf-8"))
                            weights = data.get("weight_map") or {}
                            shard_files = sorted({Path(v).name for v in weights.values() if isinstance(v, str) and v})
                            if shard_files and not all((snap / f).exists() for f in shard_files):
                                return None
                            return snap
                        if (snap / "model.safetensors").exists() or (snap / "pytorch_model.bin").exists():
                            return snap
        except Exception:
            # Fall back to best-effort below
            pass

    snapshots = [p for p in snapshots_dir.iterdir() if p.is_dir()]
    if not snapshots:
        return None

    # Pick the most recently modified snapshot
    snapshots.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    snap = snapshots[0]

    # If safetensors is sharded, the index lists required shard filenames.
    idx = snap / "model.safetensors.index.json"
    if idx.exists():
        try:
            data = json.loads(idx.read_text(encoding="utf-8"))
            weights = data.get("weight_map") or {}
            shard_files = sorted({Path(v).name for v in weights.values() if isinstance(v, str) and v})
            if shard_files and not all((snap / f).exists() for f in shard_files):
                return None
        except Exception:
            return None

    # Non-sharded forms
    if (snap / "model.safetensors").exists() or (snap / "pytorch_model.bin").exists():
        return snap

    return None


def prefetch_model_snapshot(
    model_id: str,
    *,
    max_workers: int = 32,
    etag_timeout: float = 60,
    revision: Optional[str] = "main",
) -> Optional[Path]:
    """
    Best-effort: download the full model snapshot with parallel workers.

    On modern huggingface_hub, downloads are resumable by default:
    - interrupted downloads leave partial files in cache
    - the next call will continue rather than restart
    """
    model_id = str(model_id or "").strip()
    if not model_id or "/" not in model_id:
        return None

    try:
        from huggingface_hub import snapshot_download
    except Exception:
        return None

    # Version-aware behavior:
    # - newer huggingface_hub (>=0.20) resumes downloads by default; `resume_download` is deprecated
    # - `local_dir_use_symlinks` is deprecated/ignored in newer versions
    try:
        import huggingface_hub  # type: ignore

        hub_version = getattr(huggingface_hub, "__version__", "") or ""
    except Exception:
        hub_version = ""

    def _ver_tuple(v: str) -> tuple[int, int, int]:
        parts = (v.split("+", 1)[0].split(".", 2) + ["0", "0", "0"])[:3]
        out = []
        for p in parts:
            try:
                out.append(int("".join(ch for ch in p if ch.isdigit()) or "0"))
            except Exception:
                out.append(0)
        return tuple(out[:3])  # type: ignore[return-value]

    hub_ge_020 = _ver_tuple(hub_version) >= (0, 20, 0)

    # Older huggingface_hub versions exposed `resume_download`; newer versions
    # resume by default and removed the parameter. We enable it when available.
    try:
        import inspect

        sig = inspect.signature(snapshot_download)
        has_resume = ("resume_download" in sig.parameters) and (not hub_ge_020)
    except Exception:
        has_resume = False

    allow_patterns = [
        # config
        "config.json",
        "generation_config.json",
        # tokenizer
        "tokenizer.json",
        "tokenizer.model",
        "tokenizer_config.json",
        "special_tokens_map.json",
        "vocab.json",
        "merges.txt",
        # weights
        "*.safetensors",
        "*.safetensors.index.json",
        "pytorch_model.bin",
        "pytorch_model.bin.index.json",
    ]

    def _workers_schedule(n: int) -> list[int]:
        n = max(1, int(n))
        out: list[int] = []
        while n >= 1:
            out.append(n)
            if n == 1:
                break
            n = max(1, n // 2)
        # de-dupe while preserving order
        seen = set()
        out2: list[int] = []
        for x in out:
            if x in seen:
                continue
            seen.add(x)
            out2.append(x)
        return out2

    # Optional mirror endpoint (common best-practice in restricted networks):
    # Set env `HF_ENDPOINT` (supported broadly across huggingface_hub versions).
    # We intentionally do NOT pass `endpoint=...` into snapshot_download to keep
    # compatibility with older huggingface_hub (<1.0) APIs.

    attempt = 0
    for workers in _workers_schedule(max_workers):
        for _ in range(3):
            attempt += 1
            try:
                print(f"🧭 Cache status (before): {_describe_cache_status(model_id, revision=revision)}")
            except Exception:
                pass
            print(f"⬇️  Prefetching model snapshot (attempt {attempt}) workers={workers} ...")
            # Report existing/missing counts using hub snapshot (even when HF_MODEL_LOCAL_DIR is disabled).
            try:
                existing, missing, total = _count_existing_missing_in_hub_snapshot(
                    model_id=model_id, allow_patterns=allow_patterns, revision=revision
                )
                if total is None:
                    print(f"📦 Prefetch status: 已存在文件数={existing}（无法获取远端清单，无法计算缺失文件数）")
                else:
                    print(f"📦 Prefetch status: 已存在文件数={existing} / 缺失文件数={missing}（总计={total}）")
                    # If we already have everything, skip the download attempt entirely.
                    if missing <= 0 and total > 0:
                        preferred = resolve_preferred_model_dir(model_id, revision=revision)
                        if preferred is not None:
                            print("✅ Prefetch skipped: snapshot already complete in local cache.")
                            return preferred
            except Exception:
                pass
            try:
                # cache_dir should point to HF hub cache root (pipeline.sh sets HF_HUB_CACHE)
                kwargs = dict(
                    repo_id=model_id,
                    cache_dir=os.environ.get("HF_HUB_CACHE") or None,
                    local_files_only=False,
                    allow_patterns=allow_patterns,
                    max_workers=int(workers),
                    etag_timeout=float(etag_timeout),
                )
                if revision:
                    kwargs["revision"] = str(revision)
                if has_resume:
                    kwargs["resume_download"] = True
                local_dir = _local_dir_for_model(model_id)
                if local_dir is not None:
                    kwargs["local_dir"] = str(local_dir)
                    # Log existing/missing counts BEFORE download, to make resume visible.
                    existing, missing, total = _count_existing_missing_files(
                        model_id=model_id, local_dir=local_dir, allow_patterns=allow_patterns, revision=revision
                    )
                    if total is None:
                        print(f"📦 Prefetch status: 已存在文件数={existing}（无法获取远端清单，无法计算缺失文件数）")
                    else:
                        print(
                            f"📦 Prefetch status: 已存在文件数={existing} / 缺失文件数={missing}（总计={total}）"
                        )

                # Some environments observe "download stops early" symptoms (e.g. a subset of files
                # downloaded then no further progress). To make this robust, we loop until missing=0
                # (when we can compute it), re-triggering snapshot_download as needed.
                cycles = 0
                while True:
                    cycles += 1
                    local_dir = snapshot_download(**kwargs)

                    preferred = resolve_preferred_model_dir(model_id, revision=revision)
                    if preferred is not None:
                        try:
                            print(f"🧭 Cache status (after): {_describe_cache_status(model_id, revision=revision)}")
                        except Exception:
                            pass
                        return Path(local_dir)

                    # If we can compute missing, keep trying until it reaches 0.
                    if local_dir is None:
                        break
                    local_dir_path = Path(str(kwargs.get("local_dir") or local_dir))
                    if local_dir_path.exists():
                        existing2, missing2, total2 = _count_existing_missing_files(
                            model_id=model_id,
                            local_dir=local_dir_path,
                            allow_patterns=allow_patterns,
                            revision=revision,
                        )
                        if total2 is not None:
                            print(
                                f"📦 Prefetch status (post-cycle {cycles}): 已存在文件数={existing2} / 缺失文件数={missing2}（总计={total2}）"
                            )
                            if missing2 <= 0:
                                return Path(local_dir)
                            # Prevent infinite loops in pathological cases
                            if cycles >= 10:
                                break
                            continue
                    break
            except Exception as e:
                sleep_s = min(30, 2 ** min(5, attempt - 1))
                print(f"⚠️  Prefetch failed (workers={workers}): {e}. Retrying in {sleep_s}s ...")
                time.sleep(sleep_s)
                continue

    return None

