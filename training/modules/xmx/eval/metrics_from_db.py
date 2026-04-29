import argparse
import asyncio
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Set, Tuple

# 设置路径，确保能找到项目根目录
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "../../../../"))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# 导入通用工具逻辑（复用 Tony 的 retention 计算逻辑）
from training.modules.tony.eval.metrics_from_db import (
    _compute_retention_from_user_days,
    _day_bucket,
    _parse_sqlite_dt,
    _truthy_sqlite,
    _sqlite_path_from_database_url
)

async def compute_xmx_metrics(*, module: str = "xmx") -> Dict[str, Any]:
    """
    专门针对 XMX 经济学板块的指标计算逻辑。
    涵盖：
    - 经济学 OCR 批改耗时与成功率
    - 经济学相似题推荐采纳率 (reco.economics_practice)
    - 留存率 (基于经济学核心学习行为)
    """
    database_url = os.getenv("DATABASE_URL") or "sqlite+aiosqlite:///./data/sqlite/app.db"
    db_path = _sqlite_path_from_database_url(database_url)
    
    if not os.path.exists(db_path):
        raise SystemExit(f"[metrics_from_db] XMX SQLite DB not found: {db_path}")

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # 1. 工具调用性能（如检索经济学知识库）
    tools: Dict[str, Any] = {}
    for row in cur.execute(
        """
        SELECT event_name, 
               COUNT(*) AS n, 
               SUM(CASE WHEN ok THEN 1 ELSE 0 END) AS ok_n,
               AVG(duration_ms) AS avg_ms
        FROM metric_events 
        WHERE module = ? AND event_type = 'tool'
        GROUP BY event_name
        """, (module,)
    ):
        n = int(row["n"] or 0)
        ok_n = int(row["ok_n"] or 0)
        tools[str(row["event_name"])] = {
            "count": n,
            "success_rate": (ok_n / n) if n else None,
            "avg_ms": float(row["avg_ms"]) if row["avg_ms"] is not None else None
        }

    # 2. 经济学题目推荐采纳率 (针对 xmx 的业务埋点)
    def _count(event_type: str, event_name: str) -> int:
        r = cur.execute(
            "SELECT COUNT(*) AS n FROM metric_events WHERE module=? AND event_type=? AND event_name=?",
            (module, event_type, event_name),
        ).fetchone()
        return int((r["n"] if r else 0) or 0)

    # XMX 业务埋点：economics_practice.shown -> economics_practice.accept
    shown_n = _count("reco", "economics_practice.shown")
    accept_n = _count("reco", "economics_practice.accept")

    # 3. 经济学导师反馈 (Feedback)
    feedback_n = _count("feedback", "xmx_tutor.feedback")
    helpful_n = 0
    if feedback_n:
        for row in cur.execute(
            "SELECT payload FROM metric_events WHERE module=? AND event_type='feedback' AND event_name='xmx_tutor.feedback'",
            (module,),
        ):
            try:
                payload = json.loads(row["payload"] or "{}")
                if _truthy_sqlite(payload.get("helpful")):
                    helpful_n += 1
            except: pass

    # 4. 核心路径：经济学试卷 OCR 批改 (Journey)
    journey_row = cur.execute(
        """
        SELECT COUNT(*) AS n, AVG(duration_ms) AS avg_ms
        FROM metric_events 
        WHERE module=? AND event_type='journey' AND event_name='ocr.analyze.done'
        """, (module,)
    ).fetchone()

    # 5. XMX 专属留存计算 (Retention)
    # 定义经济学板块的“活跃”行为：批改试卷、接受推荐练习、提交导师反馈
    now = datetime.now(timezone.utc)
    start_lookback = now - timedelta(days=30)
    
    cohort_filters = {("journey", "ocr.analyze.done")}
    retention_filters = {
        ("journey", "ocr.analyze.done"),
        ("reco", "economics_practice.accept"),
        ("feedback", "xmx_tutor.feedback"),
    }

    cohort_user_days: Dict[int, Set[str]] = {}
    retention_user_days: Dict[int, Set[str]] = {}
    
    for row in cur.execute(
        "SELECT user_id, event_type, event_name, created_at FROM metric_events WHERE module=? AND user_id IS NOT NULL",
        (module,),
    ):
        uid = row["user_id"]
        ts = _parse_sqlite_dt(row["created_at"])
        if ts is None or ts < start_lookback: continue
        
        day = _day_bucket(ts)
        key = (str(row["event_type"]), str(row["event_name"]))
        
        if key in cohort_filters:
            cohort_user_days.setdefault(int(uid), set()).add(day)
        if key in retention_filters:
            retention_user_days.setdefault(int(uid), set()).add(day)

    retention_d1 = _compute_retention_from_user_days(
        cohort_user_days=cohort_user_days, retention_user_days=retention_user_days, day_offset=1
    )

    con.close()

    return {
        "module": module,
        "subject": "Economics",
        "performance": {
            "ocr_analyze_count": int(journey_row["n"] or 0),
            "ocr_avg_latency_ms": float(journey_row["avg_ms"]) if journey_row["avg_ms"] else None,
            "tool_metrics": tools
        },
        "business_metrics": {
            "reco_shown": shown_n,
            "reco_accepted": accept_n,
            "reco_accept_rate": (accept_n / shown_n) if shown_n else None,
            "feedback_positive_ratio": (helpful_n / feedback_n) if feedback_n else None
        },
        "retention": {
            "d1": retention_d1,
            "description": "Cohort defined by Economics OCR upload; Retained by any practice/feedback action."
        }
    }

async def _amain():
    parser = argparse.ArgumentParser()
    parser.add_argument("--module", default="xmx")
    args = parser.parse_args()
    
    metrics = await compute_xmx_metrics(module=args.module)
    print(json.dumps(metrics, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    asyncio.run(_amain())