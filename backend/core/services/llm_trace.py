"""
LLM Trace (Tony module only)

Goal:
- Persist FULL LLM request/response (including raw model outputs) for debugging.
- Avoid breaking other modules; enable only when MODULE_NAME == "tony".

Default behavior (tony):
- enabled = true
- write traces to ./logs/llm_trace/...
- print full content to main logs only when env TONY_LLM_TRACE_PRINT=1
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


def tony_llm_trace_enabled() -> bool:
    v = os.getenv("TONY_LLM_TRACE_ENABLED")
    # Tony default: enabled (to files). Other modules: disabled (by module check above).
    if v is None:
        return True
    return str(v).strip().lower() not in ("0", "false", "no", "off")


def tony_llm_trace_print() -> bool:
    v = os.getenv("TONY_LLM_TRACE_PRINT")
    # Tony default: print (text payloads) to make debugging easy.
    # Can be disabled by explicitly setting TONY_LLM_TRACE_PRINT=0/false.
    if v is None:
        return True
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")


def _base_trace_dir() -> Path:
    # Prefer colocating with LOG_FILE if available; fallback to ./logs
    try:
        log_file = getattr(settings, "LOG_FILE", "") or "./logs/app.log"
        base = Path(log_file).expanduser().resolve().parent
    except Exception:
        base = Path("./logs").resolve()
    return base / "llm_trace"


def _safe_name(name: str) -> str:
    return "".join([c if (c.isalnum() or c in ("-", "_", ".")) else "_" for c in (name or "trace")])


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def write_llm_trace(
    *,
    trace_id: str,
    stage: str,
    kind: str,
    payload: Any,
    suffix: str = "json",
    also_log_full: Optional[bool] = None,
    log_prefix: str = "",
) -> Optional[str]:
    """
    Write FULL payload to a trace file and optionally print full content to main logs.
    Returns file path string.
    """
    if not tony_llm_trace_enabled():
        return None

    trace_id = _safe_name(trace_id)
    stage = _safe_name(stage)
    kind = _safe_name(kind)

    t_ms = int(time.time() * 1000)
    base_dir = Path(os.getenv("TONY_LLM_TRACE_DIR") or str(_base_trace_dir()))
    out_dir = base_dir / trace_id
    _ensure_dir(out_dir)

    fname = f"{t_ms}_{stage}_{kind}.{_safe_name(suffix)}"
    fpath = out_dir / fname

    try:
        if suffix.lower() in ("json",):
            with open(fpath, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
        else:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write("" if payload is None else str(payload))
    except Exception as e:
        logger.warning(f"[llm_trace] failed to write trace file: {type(e).__name__}: {e}")
        return None

    should_print = tony_llm_trace_print() if also_log_full is None else bool(also_log_full)
    if should_print:
        # Print full content to main logs (may be huge!)
        try:
            # logger.info(f"[llm_trace] {log_prefix} FULL TRACE {stage}/{kind} file={str(fpath)}")
            if suffix.lower() in ("json",):
                logger.info(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
            else:
                logger.info("" if payload is None else str(payload))
        except Exception:
            pass
    else:
        logger.info(f"[llm_trace] {log_prefix} trace_saved stage={stage} kind={kind} file={str(fpath)}")

    return str(fpath)


