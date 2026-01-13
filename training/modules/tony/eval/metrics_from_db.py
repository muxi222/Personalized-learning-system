"""
Compute evaluation metrics from SQLite telemetry (metric_events).

This script is intentionally dependency-light: it uses SQLAlchemy (already in repo).
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy import select, func, case

from backend.core.db.session import async_session_maker
from backend.core.db.models import MetricEvent


def _day_bucket(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


async def _load_user_days(
    *,
    session,
    module: str,
    event_filters: Set[Tuple[str, str]],
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
) -> Dict[int, Set[str]]:
    """
    Return user->set(day_str) where day_str is YYYY-MM-DD for events matching filters.

    event_filters: set of (event_type, event_name)
    """
    if not event_filters:
        return {}

    # Build OR conditions over (type,name).
    # SQLite: we keep it simple by filtering in Python after selecting a reasonably small slice.
    stmt = (
        select(MetricEvent.user_id, MetricEvent.event_type, MetricEvent.event_name, MetricEvent.created_at)
        .where(MetricEvent.module == module)
        .where(MetricEvent.user_id.isnot(None))
    )
    if start is not None:
        stmt = stmt.where(MetricEvent.created_at >= start)
    if end is not None:
        stmt = stmt.where(MetricEvent.created_at < end)

    rows = (await session.execute(stmt)).all()
    out: Dict[int, Set[str]] = {}
    for uid, et, en, ts in rows:
        if uid is None or ts is None:
            continue
        key = (str(et), str(en))
        if key not in event_filters:
            continue
        out.setdefault(int(uid), set()).add(_day_bucket(ts))
    return out


def _compute_retention_from_user_days(
    *,
    cohort_user_days: Dict[int, Set[str]],
    retention_user_days: Dict[int, Set[str]],
    day_offset: int,
) -> Dict[str, Any]:
    """
    Cohort is defined by the user's **first** cohort day in cohort_user_days.
    Retained on D+offset if they have any retention event on that target day.
    """
    cohort_users = list(cohort_user_days.keys())
    if not cohort_users:
        return {"cohort_size": 0, "retained": 0, "rate": None}

    retained = 0
    for uid, cohort_days in cohort_user_days.items():
        if not cohort_days:
            continue
        day0 = min(cohort_days)
        # day strings are YYYY-MM-DD; convert to date
        d0 = datetime.strptime(day0, "%Y-%m-%d").date()
        target = (d0 + timedelta(days=day_offset)).strftime("%Y-%m-%d")
        if target in (retention_user_days.get(uid) or set()):
            retained += 1
    n = len(cohort_users)
    return {"cohort_size": n, "retained": retained, "rate": (retained / n) if n else None}


async def compute_metrics(*, module: str = "tony") -> Dict[str, Any]:
    async with async_session_maker() as session:
        # Tool success rate / latency
        tool_stmt = (
            select(
                MetricEvent.event_name,
                func.count(MetricEvent.id).label("n"),
                func.sum(case((MetricEvent.ok == True, 1), else_=0)).label("ok_n"),  # noqa: E712
                func.avg(MetricEvent.duration_ms).label("avg_ms"),
                func.min(MetricEvent.duration_ms).label("min_ms"),
                func.max(MetricEvent.duration_ms).label("max_ms"),
            )
            .where(MetricEvent.module == module)
            .where(MetricEvent.event_type == "tool")
            .group_by(MetricEvent.event_name)
        )
        tool_rows = (await session.execute(tool_stmt)).all()
        tools: Dict[str, Any] = {}
        for r in tool_rows:
            n = int(r.n or 0)
            ok_n = int(r.ok_n or 0)
            tools[str(r.event_name)] = {
                "count": n,
                "success_rate": (ok_n / n) if n else None,
                "avg_ms": float(r.avg_ms) if r.avg_ms is not None else None,
                "min_ms": float(r.min_ms) if r.min_ms is not None else None,
                "max_ms": float(r.max_ms) if r.max_ms is not None else None,
            }

        # Recommendation acceptance rate (shown -> accept)
        shown_n = (
            await session.execute(
                select(func.count(MetricEvent.id))
                .where(MetricEvent.module == module)
                .where(MetricEvent.event_name == "similar_questions.shown")
                .where(MetricEvent.event_type == "reco")
            )
        ).scalar() or 0
        accept_n = (
            await session.execute(
                select(func.count(MetricEvent.id))
                .where(MetricEvent.module == module)
                .where(MetricEvent.event_name == "similar_questions.accept")
                .where(MetricEvent.event_type == "reco")
            )
        ).scalar() or 0

        # Feedback rate + positive ratio
        feedback_n = (
            await session.execute(
                select(func.count(MetricEvent.id))
                .where(MetricEvent.module == module)
                .where(MetricEvent.event_name == "learning.feedback")
                .where(MetricEvent.event_type == "feedback")
            )
        ).scalar() or 0
        helpful_n = (
            await session.execute(
                select(func.count(MetricEvent.id))
                .where(MetricEvent.module == module)
                .where(MetricEvent.event_name == "learning.feedback")
                .where(MetricEvent.event_type == "feedback")
                .where(func.json_extract(MetricEvent.payload, "$.helpful") == True)  # noqa: E712
            )
        ).scalar() or 0

        # Task failure rate (best-effort)
        task_failed_n = (
            await session.execute(
                select(func.count(MetricEvent.id))
                .where(MetricEvent.module == module)
                .where(MetricEvent.event_name == "task.failed")
                .where(MetricEvent.event_type == "task")
            )
        ).scalar() or 0
        task_update_n = (
            await session.execute(
                select(func.count(MetricEvent.id))
                .where(MetricEvent.module == module)
                .where(MetricEvent.event_name == "task.status_update")
                .where(MetricEvent.event_type == "task")
            )
        ).scalar() or 0

        # Journey duration (ocr analyze)
        journey_done = (
            await session.execute(
                select(
                    func.count(MetricEvent.id),
                    func.avg(MetricEvent.duration_ms),
                    func.min(MetricEvent.duration_ms),
                    func.max(MetricEvent.duration_ms),
                )
                .where(MetricEvent.module == module)
                .where(MetricEvent.event_name == "ocr.analyze.done")
                .where(MetricEvent.event_type == "journey")
            )
        ).one()

        # Retention (D1/D7) - strict definition via "key event sequence"
        #
        # Cohort (Day0): users who completed OCR analysis (journey.ocr.analyze.done).
        # Retention event set: users who later perform any "meaningful" learning action:
        # - completed OCR analysis again
        # - accepted a recommended similar question
        # - submitted learning feedback
        #
        # This avoids DAU proxy and aligns with product goals.
        now = datetime.utcnow()
        start = now - timedelta(days=30)
        cohort_filters: Set[Tuple[str, str]] = {("journey", "ocr.analyze.done")}
        retention_filters: Set[Tuple[str, str]] = {
            ("journey", "ocr.analyze.done"),
            ("reco", "similar_questions.accept"),
            ("feedback", "learning.feedback"),
        }
        cohort_user_days = await _load_user_days(
            session=session, module=module, event_filters=cohort_filters, start=start
        )
        retention_user_days = await _load_user_days(
            session=session, module=module, event_filters=retention_filters, start=start
        )
        retention_d1 = _compute_retention_from_user_days(
            cohort_user_days=cohort_user_days, retention_user_days=retention_user_days, day_offset=1
        )
        retention_d7 = _compute_retention_from_user_days(
            cohort_user_days=cohort_user_days, retention_user_days=retention_user_days, day_offset=7
        )

    return {
        "module": module,
        "tools": tools,
        "recommendation": {
            "shown": int(shown_n),
            "accepted": int(accept_n),
            "accept_rate": (int(accept_n) / int(shown_n)) if shown_n else None,
        },
        "feedback": {
            "count": int(feedback_n),
            "helpful": int(helpful_n),
            "positive_ratio": (int(helpful_n) / int(feedback_n)) if feedback_n else None,
        },
        "tasks": {
            "status_updates": int(task_update_n),
            "failed": int(task_failed_n),
            "failure_rate": (int(task_failed_n) / int(task_update_n)) if task_update_n else None,
        },
        "journey": {
            "ocr_analyze_done_count": int(journey_done[0] or 0),
            "ocr_analyze_avg_ms": float(journey_done[1]) if journey_done[1] is not None else None,
            "ocr_analyze_min_ms": float(journey_done[2]) if journey_done[2] is not None else None,
            "ocr_analyze_max_ms": float(journey_done[3]) if journey_done[3] is not None else None,
        },
        "retention": {
            "window_days": 30,
            "cohort_event": {"event_type": "journey", "event_name": "ocr.analyze.done"},
            "retention_events": [
                {"event_type": "journey", "event_name": "ocr.analyze.done"},
                {"event_type": "reco", "event_name": "similar_questions.accept"},
                {"event_type": "feedback", "event_name": "learning.feedback"},
            ],
            "d1": retention_d1,
            "d7": retention_d7,
        },
    }


async def _amain(args: argparse.Namespace) -> None:
    # Note: DB path is controlled by env DATABASE_URL, not by args.
    # For evaluation runs, set:
    #   export DATABASE_URL=sqlite+aiosqlite:///./data/sqlite/app.db
    out = await compute_metrics(module=args.module)
    print(json.dumps(out, ensure_ascii=False, indent=2))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--module", default="tony")
    p.add_argument("--db", default=None, help="(unused) set DATABASE_URL env instead")
    args = p.parse_args()

    import anyio

    anyio.run(lambda: _amain(args))


if __name__ == "__main__":
    main()

