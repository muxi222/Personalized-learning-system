"""
Compute evaluation metrics from SQLite telemetry (metric_events).

This script is intentionally dependency-light:
- Preferred: SQLAlchemy (same DB stack as backend)
- Fallback: stdlib sqlite3 (when SQLAlchemy isn't installed in the current Python env)
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Set, Tuple

# Allow running as a file script from repo root (or any cwd) without installing the package.
# Example: python training/modules/wzm/eval/metrics_from_db.py --module wzm
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "../../../../"))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

_HAVE_SQLALCHEMY = False
_SQLALCHEMY_IMPORT_ERROR: Optional[str] = None
try:
    from sqlalchemy import select, func, case, and_, or_  # type: ignore

    from backend.core.db.session import async_session_maker  # type: ignore
    from backend.core.db.models import MetricEvent  # type: ignore

    _HAVE_SQLALCHEMY = True
except Exception as e:  # pragma: no cover
    _SQLALCHEMY_IMPORT_ERROR = str(e)
    _HAVE_SQLALCHEMY = False


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

    # IMPORTANT: filter in SQL (avoid full table scan + python-side filtering).
    pairs = list(event_filters)
    cond = or_(*[and_(MetricEvent.event_type == et, MetricEvent.event_name == en) for et, en in pairs])
    stmt = select(MetricEvent.user_id, MetricEvent.created_at).where(MetricEvent.module == module).where(cond).where(
        MetricEvent.user_id.isnot(None)
    )
    if start is not None:
        stmt = stmt.where(MetricEvent.created_at >= start)
    if end is not None:
        stmt = stmt.where(MetricEvent.created_at < end)

    rows = (await session.execute(stmt)).all()
    out: Dict[int, Set[str]] = {}
    for uid, ts in rows:
        if uid is None or ts is None:
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


async def compute_metrics(*, module: str = "wzm") -> Dict[str, Any]:
    if not _HAVE_SQLALCHEMY:
        return _compute_metrics_sqlite(module=module)

    since_days = int(os.getenv("EVAL_SINCE_DAYS", "30") or "30")
    progress = (os.getenv("EVAL_PROGRESS", "1") or "1").strip().lower() not in ("0", "false", "no")
    t0 = time.perf_counter()
    if progress:
        print(f"[metrics_from_db] module={module} since_days={since_days} (sqlalchemy)", file=sys.stderr)

    async with async_session_maker() as session:
        # Tool success rate / latency
        t_tools0 = time.perf_counter()
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
        if progress:
            print(f"[metrics_from_db] tools done n_tools={len(tools)} elapsed_ms={int((time.perf_counter()-t_tools0)*1000)}", file=sys.stderr)

        # Recommendation acceptance rate (shown -> accept)
        t_reco0 = time.perf_counter()
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
        if progress:
            print(f"[metrics_from_db] reco done elapsed_ms={int((time.perf_counter()-t_reco0)*1000)}", file=sys.stderr)

        # Feedback rate + positive ratio
        t_fb0 = time.perf_counter()
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
        if progress:
            print(f"[metrics_from_db] feedback done elapsed_ms={int((time.perf_counter()-t_fb0)*1000)}", file=sys.stderr)

        # Task failure rate (best-effort)
        t_task0 = time.perf_counter()
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
        if progress:
            print(f"[metrics_from_db] tasks done elapsed_ms={int((time.perf_counter()-t_task0)*1000)}", file=sys.stderr)

        # Journey duration (ocr analyze)
        t_j0 = time.perf_counter()
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
        if progress:
            print(f"[metrics_from_db] journey agg done elapsed_ms={int((time.perf_counter()-t_j0)*1000)}", file=sys.stderr)

        # Retention (D1/D7) - strict definition via "key event sequence"
        #
        # Cohort (Day0): users who completed OCR analysis (journey.ocr.analyze.done).
        # Retention event set: users who later perform any "meaningful" learning action:
        # - completed OCR analysis again
        # - accepted a recommended similar question
        # - submitted learning feedback
        #
        # This avoids DAU proxy and aligns with product goals.
        t_ret0 = time.perf_counter()
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=since_days)
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
        if progress:
            print(
                f"[metrics_from_db] retention done cohort_users={len(cohort_user_days)} "
                f"elapsed_ms={int((time.perf_counter()-t_ret0)*1000)}",
                file=sys.stderr,
            )

    out = {
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
            "window_days": since_days,
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
    if progress:
        print(f"[metrics_from_db] done total_elapsed_ms={int((time.perf_counter()-t0)*1000)}", file=sys.stderr)
    return out


def _sqlite_path_from_database_url(database_url: str) -> str:
    """
    Resolve sqlite path from SQLAlchemy-style DATABASE_URL.
    Supported:
    - sqlite+aiosqlite:///./data/sqlite/app.db
    - sqlite:///./data/sqlite/app.db
    - sqlite:////abs/path/app.db
    """
    s = (database_url or "").strip()
    if not s:
        return os.path.abspath(os.path.join(_REPO_ROOT, "data/sqlite/app.db"))

    # Strip driver prefix
    if s.startswith("sqlite+aiosqlite:"):
        s = "sqlite:" + s[len("sqlite+aiosqlite:") :]

    if not s.startswith("sqlite:"):
        return os.path.abspath(os.path.join(_REPO_ROOT, s))

    if "///" in s:
        path = s.split("///", 1)[1]
    else:
        path = s.split("sqlite:", 1)[1]
    path = path.strip()

    if os.path.isabs(path):
        return path
    return os.path.abspath(os.path.join(_REPO_ROOT, path))


def _parse_sqlite_dt(v: object) -> Optional[datetime]:
    if v is None:
        return None
    if isinstance(v, datetime):
        dt = v
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    if not isinstance(v, str):
        try:
            dt = datetime.fromisoformat(str(v))
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            return None
    s = v.strip()
    if not s:
        return None
    s2 = s.replace("Z", "")
    try:
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        pass
    try:
        dt = datetime.strptime(s2.split(".", 1)[0].replace("T", " "), "%Y-%m-%d %H:%M:%S")
        return dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _truthy_sqlite(v: object) -> bool:
    if v is None:
        return False
    if isinstance(v, bool):
        return bool(v)
    if isinstance(v, (int, float)):
        return bool(int(v))
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "t", "yes", "y", "ok")
    return False


def _compute_metrics_sqlite(*, module: str) -> Dict[str, Any]:
    """
    Fallback implementation when SQLAlchemy isn't installed.
    Reads telemetry directly from SQLite via stdlib sqlite3.
    """
    database_url = os.getenv("DATABASE_URL") or "sqlite+aiosqlite:///./data/sqlite/app.db"
    db_path = _sqlite_path_from_database_url(database_url)
    if not os.path.exists(db_path):
        raise SystemExit(f"[metrics_from_db] SQLite DB not found: {db_path} (set DATABASE_URL)")

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    tools: Dict[str, Any] = {}
    for row in cur.execute(
        """
        SELECT event_name,
               COUNT(*) AS n,
               SUM(CASE WHEN ok THEN 1 ELSE 0 END) AS ok_n,
               AVG(duration_ms) AS avg_ms,
               MIN(duration_ms) AS min_ms,
               MAX(duration_ms) AS max_ms
        FROM metric_events
        WHERE module = ? AND event_type = 'tool'
        GROUP BY event_name
        """,
        (module,),
    ):
        n = int(row["n"] or 0)
        ok_n = int(row["ok_n"] or 0)
        tools[str(row["event_name"])] = {
            "count": n,
            "success_rate": (ok_n / n) if n else None,
            "avg_ms": float(row["avg_ms"]) if row["avg_ms"] is not None else None,
            "min_ms": float(row["min_ms"]) if row["min_ms"] is not None else None,
            "max_ms": float(row["max_ms"]) if row["max_ms"] is not None else None,
        }

    def _count(event_type: str, event_name: str) -> int:
        r = cur.execute(
            "SELECT COUNT(*) AS n FROM metric_events WHERE module=? AND event_type=? AND event_name=?",
            (module, event_type, event_name),
        ).fetchone()
        return int((r["n"] if r else 0) or 0)

    shown_n = _count("reco", "similar_questions.shown")
    accept_n = _count("reco", "similar_questions.accept")

    feedback_n = _count("feedback", "learning.feedback")
    helpful_n = 0
    if feedback_n:
        for row in cur.execute(
            "SELECT payload FROM metric_events WHERE module=? AND event_type='feedback' AND event_name='learning.feedback'",
            (module,),
        ):
            payload_raw = row["payload"]
            try:
                payload = payload_raw if isinstance(payload_raw, dict) else json.loads(payload_raw or "{}")
            except Exception:
                payload = {}
            if _truthy_sqlite(payload.get("helpful")):
                helpful_n += 1

    task_failed_n = _count("task", "task.failed")
    task_update_n = _count("task", "task.status_update")

    journey_row = cur.execute(
        """
        SELECT COUNT(*) AS n,
               AVG(duration_ms) AS avg_ms,
               MIN(duration_ms) AS min_ms,
               MAX(duration_ms) AS max_ms
        FROM metric_events
        WHERE module=? AND event_type='journey' AND event_name='ocr.analyze.done'
        """,
        (module,),
    ).fetchone()

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=30)
    cohort_filters: Set[Tuple[str, str]] = {("journey", "ocr.analyze.done")}
    retention_filters: Set[Tuple[str, str]] = {
        ("journey", "ocr.analyze.done"),
        ("reco", "similar_questions.accept"),
        ("feedback", "learning.feedback"),
    }

    cohort_user_days: Dict[int, Set[str]] = {}
    retention_user_days: Dict[int, Set[str]] = {}
    for row in cur.execute(
        "SELECT user_id, event_type, event_name, created_at FROM metric_events WHERE module=? AND user_id IS NOT NULL",
        (module,),
    ):
        uid = row["user_id"]
        if uid is None:
            continue
        ts = _parse_sqlite_dt(row["created_at"])
        if ts is None or ts < start:
            continue
        key = (str(row["event_type"]), str(row["event_name"]))
        day = _day_bucket(ts)
        if key in cohort_filters:
            cohort_user_days.setdefault(int(uid), set()).add(day)
        if key in retention_filters:
            retention_user_days.setdefault(int(uid), set()).add(day)

    retention_d1 = _compute_retention_from_user_days(
        cohort_user_days=cohort_user_days, retention_user_days=retention_user_days, day_offset=1
    )
    retention_d7 = _compute_retention_from_user_days(
        cohort_user_days=cohort_user_days, retention_user_days=retention_user_days, day_offset=7
    )

    con.close()

    return {
        "module": module,
        "runtime": {
            "backend_import": "sqlalchemy" if _HAVE_SQLALCHEMY else "sqlite3",
            "sqlalchemy_error": _SQLALCHEMY_IMPORT_ERROR,
            "database_url": database_url,
            "sqlite_path": db_path,
        },
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
            "ocr_analyze_done_count": int((journey_row["n"] if journey_row else 0) or 0),
            "ocr_analyze_avg_ms": float(journey_row["avg_ms"]) if journey_row and journey_row["avg_ms"] is not None else None,
            "ocr_analyze_min_ms": float(journey_row["min_ms"]) if journey_row and journey_row["min_ms"] is not None else None,
            "ocr_analyze_max_ms": float(journey_row["max_ms"]) if journey_row and journey_row["max_ms"] is not None else None,
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
    # Ensure output is flushed in environments with buffered IO.
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass

    # Best-effort: dispose SQLAlchemy engine to avoid lingering non-daemon threads (aiosqlite) that may
    # keep the process alive in some environments.
    if _HAVE_SQLALCHEMY:
        try:
            from backend.core.db.session import engine  # type: ignore

            await engine.dispose()
        except Exception:
            pass


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--module", default="wzm")
    p.add_argument("--db", default=None, help="(unused) set DATABASE_URL env instead")
    args = p.parse_args()

    import asyncio

    asyncio.run(_amain(args))
    # Be explicit about termination for teaching terminals.
    raise SystemExit(0)


if __name__ == "__main__":
    main()

