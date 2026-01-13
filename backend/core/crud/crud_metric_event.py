"""
CRUD for MetricEvent (telemetry).

Tony evaluation uses this to compute:
- tool call latency/success
- task failure rates
- acceptance/feedback rates
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.db.models import MetricEvent


async def create_metric_event(
    db: AsyncSession,
    *,
    event_type: str,
    event_name: str,
    ok: bool = True,
    duration_ms: Optional[float] = None,
    user_id: Optional[int] = None,
    module: Optional[str] = None,
    subject: Optional[str] = None,
    task_id: Optional[str] = None,
    question_id: Optional[int] = None,
    exam_correction_id: Optional[int] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> MetricEvent:
    ev = MetricEvent(
        event_type=str(event_type),
        event_name=str(event_name),
        ok=bool(ok),
        duration_ms=float(duration_ms) if duration_ms is not None else None,
        user_id=user_id,
        module=module,
        subject=subject,
        task_id=task_id,
        question_id=question_id,
        exam_correction_id=exam_correction_id,
        payload=payload or {},
    )
    db.add(ev)
    await db.flush()
    return ev

