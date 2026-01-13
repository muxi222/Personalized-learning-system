"""
Metrics / Telemetry Service

Tony phase:
- Provide a single place to write MetricEvent rows.
- Keep it best-effort (must not break user flows).

Evaluation scripts can later compute:
- tool call success rate / latency distribution
- task failure rate / retry success
- recommendation acceptance / feedback
- user journey duration metrics
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, Dict, Optional

from backend.core.db.session import async_session_maker
from backend.core.crud.crud_metric_event import create_metric_event

logger = logging.getLogger(__name__)


class MetricsService:
    async def log_event(
        self,
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
    ) -> None:
        try:
            async with async_session_maker() as session:
                await create_metric_event(
                    session,
                    event_type=event_type,
                    event_name=event_name,
                    ok=ok,
                    duration_ms=duration_ms,
                    user_id=user_id,
                    module=module,
                    subject=subject,
                    task_id=task_id,
                    question_id=question_id,
                    exam_correction_id=exam_correction_id,
                    payload=payload,
                )
                await session.commit()
        except Exception as e:
            logger.debug(f"[metrics] failed to log event {event_type}.{event_name}: {e}")

    async def log_tool_call(
        self,
        *,
        tool: str,
        ok: bool,
        t_ms: float,
        module: Optional[str] = None,
        subject: Optional[str] = None,
        user_id: Optional[int] = None,
        task_id: Optional[str] = None,
        question_id: Optional[int] = None,
        payload: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        p = dict(payload or {})
        if error:
            p["error"] = error
        await self.log_event(
            event_type="tool",
            event_name=str(tool),
            ok=bool(ok),
            duration_ms=float(t_ms),
            user_id=user_id,
            module=module,
            subject=subject,
            task_id=task_id,
            question_id=question_id,
            payload=p,
        )


@lru_cache()
def get_metrics_service() -> MetricsService:
    return MetricsService()

