#!/usr/bin/env python3
"""
Prepare Wzm preference dataset from `feedbacks` table (human preference).

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
import random
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

_p = Path(__file__).resolve()
while _p.name != "training" and _p.parent != _p:
    _p = _p.parent
_repo_root = _p.parent if _p.name == "training" else Path.cwd()
sys.path.insert(0, str(_repo_root))

from training.core.datasets.io import iter_jsonl, write_jsonl, safe_text


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


def _pick_default_demo_sft_paths(subjects: List[str]) -> List[Path]:
    """
    Prefer per-subject SFT datasets if present; fall back to legacy sft/train.jsonl.
    """
    out: List[Path] = []
    for s in subjects:
        s = safe_text(s).lower()
        if not s:
            continue
        p = _repo_root / "data" / "training" / "wzm" / "datasets" / "sft" / s / "train.jsonl"
        if p.exists():
            out.append(p)
    legacy = _repo_root / "data" / "training" / "wzm" / "datasets" / "sft" / "train.jsonl"
    if legacy.exists():
        out.append(legacy)
    # de-dupe preserve order
    seen = set()
    out2 = []
    for p in out:
        if p in seen:
            continue
        seen.add(p)
        out2.append(p)
    return out2


def _make_rejected_from_chosen(chosen: str) -> str:
    """
    Make a "worse" answer without introducing factual errors:
    - remove structure/steps
    - be less specific / less actionable
    """
    chosen = safe_text(chosen, max_len=8000)
    if not chosen:
        return ""
    # Heuristic: keep only the first ~2 blocks and remove practice/summary parts.
    parts = [p.strip() for p in chosen.split("\n\n") if p.strip()]
    if len(parts) <= 1:
        return "这题主要考查相关知识点。建议先回顾课本对应章节，再做几道同类题巩固。"
    head = parts[:2]
    tail = (
        "建议：先把核心概念记牢，再多做同类型题目巩固；遇到不会的步骤回到课本/笔记查漏补缺。"
    )
    return "\n\n".join(head + [tail])


def iter_demo_preference_rows(
    *,
    subjects: List[str],
    n: int,
    seed: int,
) -> Iterator[Dict[str, Any]]:
    """
    Generate a demo preference dataset from existing SFT JSONL.
    This is a realistic *workflow* example when real feedback pairs are not yet available.
    """
    paths = _pick_default_demo_sft_paths(subjects)
    if not paths:
        raise FileNotFoundError(
            "No SFT dataset found to generate demo preference pairs.\n"
            "Expected one of:\n"
            "- data/training/wzm/datasets/sft/<subject>/train.jsonl\n"
            "- data/training/wzm/datasets/sft/train.jsonl\n"
        )

    pool: List[Dict[str, Any]] = []
    for p in paths:
        for obj in iter_jsonl(p):
            inst = safe_text(obj.get("instruction"))
            inp = safe_text(obj.get("input"))
            out = safe_text(obj.get("output"))
            if not inst or not out:
                continue
            pool.append({"instruction": inst, "input": inp, "output": out, "_path": str(p)})

    if not pool:
        raise RuntimeError("SFT dataset exists but contains no usable rows (need instruction/output).")

    rng = random.Random(int(seed))
    for i in range(int(n)):
        ex = pool[rng.randrange(len(pool))]
        instruction = safe_text(ex["instruction"], max_len=2000)
        input_text = safe_text(ex["input"], max_len=6000)
        chosen = safe_text(ex["output"], max_len=8000)
        rejected = _make_rejected_from_chosen(chosen)
        if not rejected:
            continue

        prompt_parts = [
            "你是学习小书童，一位温暖、有耐心、专业的学习助手。",
            "请针对下面的错题，给出讲解、错因分析和复习建议。",
            "",
            f"指令: {instruction}",
        ]
        if input_text:
            prompt_parts += ["", "输入:", input_text]
        prompt = "\n".join([p for p in prompt_parts if p != ""]).strip() + "\n\n回答:"

        yield {
            "prompt": prompt,
            "chosen": chosen,
            "rejected": rejected,
            "meta": {
                "feedback_id": f"demo-{i+1:04d}",
                "user_id": 0,
                "question_id": 0,
                "subject": (subjects[0] if subjects else "unknown"),
                "source": "demo_sft",
                "sft_path": safe_text(ex.get("_path")),
                "seed": int(seed),
            },
        }


def main():
    parser = argparse.ArgumentParser(description="Prepare Wzm preference dataset (DPO/ORPO)")
    parser.add_argument(
        "--sqlite",
        default=str(_repo_root / "data" / "sqlite" / "app.db"),
        help="Path to app SQLite DB",
    )
    parser.add_argument(
        "--output",
        default=str(_repo_root / "data" / "training" / "wzm" / "datasets" / "preference" / "train.jsonl"),
        help="Output JSONL path",
    )
    parser.add_argument(
        "--subjects",
        nargs="*",
        default=["chemistry"],
        help="Subjects to include",
    )
    parser.add_argument("--limit", type=int, default=0, help="Optional limit for smoke runs")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="If no real feedback pairs are found, generate a demo preference dataset from SFT samples.",
    )
    parser.add_argument("--demo-n", type=int, default=100, help="Demo preference rows to generate (default: 100)")
    parser.add_argument("--demo-seed", type=int, default=42, help="Demo RNG seed (default: 42)")
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

    if not rows and args.demo:
        demo_n = max(1, int(args.demo_n))
        rows = list(iter_demo_preference_rows(subjects=args.subjects, n=demo_n, seed=int(args.demo_seed)))
        print(f"ℹ️  No real feedback pairs found; generated demo preference rows: {len(rows)}")

    n = write_jsonl(out_path, rows)
    print(f"✅ wrote {n} rows to {out_path}")


if __name__ == "__main__":
    main()

