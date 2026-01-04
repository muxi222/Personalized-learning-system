"""
LLM Utilities

- Retry-After parsing
- Exponential backoff with jitter
- Per-process concurrency limiter (asyncio.Semaphore)
"""

from __future__ import annotations

import asyncio
import os
import random
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Optional

from backend.core.base_config import get_base_settings

settings = get_base_settings()

_llm_semaphore: Optional[asyncio.Semaphore] = None


def get_llm_semaphore() -> asyncio.Semaphore:
    """
    Limit concurrent calls to upstream LLM endpoint within a single process.
    This reduces bursty traffic and lowers the chance of HTTP 429.
    """
    global _llm_semaphore
    if _llm_semaphore is None:
        try:
            max_conc = int(os.getenv("LLM_MAX_CONCURRENCY") or str(getattr(settings, "LLM_MAX_CONCURRENCY", 2)))
        except Exception:
            max_conc = 2
        max_conc = max(1, max_conc)
        _llm_semaphore = asyncio.Semaphore(max_conc)
    return _llm_semaphore


def parse_retry_after_seconds(value: Optional[str]) -> Optional[float]:
    """
    Parse Retry-After header value into seconds.
    Supports:
    - delta-seconds: "120"
    - HTTP-date: "Wed, 21 Oct 2015 07:28:00 GMT"
    """
    if not value:
        return None
    v = str(value).strip()
    if not v:
        return None
    if v.isdigit():
        try:
            return max(0.0, float(v))
        except Exception:
            return None
    try:
        dt = parsedate_to_datetime(v)
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.0, (dt - datetime.now(timezone.utc)).total_seconds())
    except Exception:
        return None


def compute_backoff_delay_seconds(
    *,
    attempt: int,
    base_delay: float,
    max_delay: float,
    retry_after_s: Optional[float] = None,
    jitter: float = 0.2,
) -> float:
    """
    Compute sleep time for retries.
    attempt is 0-based.
    """
    delay = min(float(max_delay), float(base_delay) * (2 ** int(attempt)))
    if retry_after_s is not None:
        delay = max(delay, float(retry_after_s))
    if jitter > 0:
        delay += random.random() * float(jitter)
    return float(delay)


