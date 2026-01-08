#!/usr/bin/env python3
"""
Prepare Tony preference dataset from `feedbacks` table (human preference).

Output format (TRL DPOTrainer-compatible JSONL):
{"prompt": "...", "chosen": "...", "rejected": "...", "meta": {...}}

Source:
- feedbacks.original_response (rejected)
- feedbacks.preferred_response (chosen)
- join questions for prompt context
"""

from __future__ import annotations

import argparse
import sqlite3
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

_p = Path(__file__).resolve()
while _p.name != "training" and _p.parent != _p:
    _p = _p.parent
_repo_root = _p.parent if _p.name == "training" else Path.cwd()
sys.path.insert(0, str(_repo_root))

from training.core.datasets.io import write_jsonl, safe_text


def iter_preference_rows(conn: sqlite3.Connection, subjects: List[str], limit: Optional[int]) -> Iterator[Dict[str, Any]]:
    subj_vals: List[str] = []
    for s in subjects:
        s = safe_text(s)
        if not s:
            continue
        subj_vals.append(s)
        subj_vals.append(s.upper())
    seen = set()
    subj_vals = [x for x in subj_vals if not (x in seen or seen.add(x))]

    where = f"q.subject IN ({', '.join(['?'] * len(subj_vals))})" if subj_vals else "1=1"
    sql = f"""
    SELECT
      f.id AS feedback_id,
      f.user_id AS user_id,
      f.question_id AS question_id,
      COALESCE(f.original_response, '') AS rejected,
      COALESCE(f.preferred_response, '') AS chosen,
      COALESCE(q.subject, '') AS subject,
      COALESCE(q.content, '') AS content,
      COALESCE(q.student_answer, '') AS student_answer,
      COALESCE(q.correct_answer, '') AS correct_answer,
      COALESCE(q.chapter, '') AS chapter,
      COALESCE(q.knowledge_points, '[]') AS knowledge_points
    FROM feedbacks f
    JOIN questions q ON q.id = f.question_id
    WHERE ({where})
    ORDER BY f.created_at DESC, f.id DESC
    """
    if limit:
        sql += f" LIMIT {int(limit)}"

    for row in conn.execute(sql, subj_vals).fetchall():
        chosen = safe_text(row["chosen"], max_len=8000)
        rejected = safe_text(row["rejected"], max_len=8000)
        if not chosen or not rejected:
            continue

        # Prompt reconstruction (best-effort).
        # In production we'd store the exact prompt; for now we rebuild from the question context.
        prompt_parts = [
            "你是学习小书童，一位温暖、有耐心、专业的学习助手。",
            "请针对下面的错题，给出讲解、错因分析和复习建议。",
            "",
            f"学科: {safe_text(row['subject'])}",
            f"章节: {safe_text(row['chapter'])}" if safe_text(row["chapter"]) else "",
            "",
            "题目:",
            safe_text(row["content"], max_len=6000),
        ]
        if safe_text(row["student_answer"]):
            prompt_parts += ["", "学生作答:", safe_text(row["student_answer"], max_len=2000)]
        if safe_text(row["correct_answer"]):
            prompt_parts += ["", "参考答案:", safe_text(row["correct_answer"], max_len=2000)]

        prompt = "\n".join([p for p in prompt_parts if p != ""]).strip() + "\n\n回答:"

        yield {
            "prompt": prompt,
            "chosen": chosen,
            "rejected": rejected,
            "meta": {
                "feedback_id": int(row["feedback_id"]),
                "user_id": int(row["user_id"]),
                "question_id": int(row["question_id"]),
                "subject": safe_text(row["subject"]),
                "source": "feedbacks",
            },
        }


def main():
    parser = argparse.ArgumentParser(description="Prepare Tony preference dataset (DPO/ORPO)")
    parser.add_argument(
        "--sqlite",
        default=str(_repo_root / "data" / "sqlite" / "app.db"),
        help="Path to app SQLite DB",
    )
    parser.add_argument(
        "--output",
        default=str(_repo_root / "data" / "training" / "tony" / "datasets" / "preference" / "train.jsonl"),
        help="Output JSONL path",
    )
    parser.add_argument(
        "--subjects",
        nargs="*",
        default=["history", "geography", "other"],
        help="Subjects to include",
    )
    parser.add_argument("--limit", type=int, default=0, help="Optional limit for smoke runs")
    args = parser.parse_args()

    sqlite_path = Path(args.sqlite)
    if not sqlite_path.exists():
        raise FileNotFoundError(f"SQLite DB not found: {sqlite_path}")

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    limit = int(args.limit) if int(args.limit) > 0 else None

    conn = sqlite3.connect(str(sqlite_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = list(iter_preference_rows(conn, args.subjects, limit))
    finally:
        conn.close()

    n = write_jsonl(out_path, rows)
    print(f"✅ wrote {n} rows to {out_path}")


if __name__ == "__main__":
    main()

