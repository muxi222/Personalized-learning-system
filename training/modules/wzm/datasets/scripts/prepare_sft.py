#!/usr/bin/env python3
"""
Prepare Wzm SFT dataset from the production SQLite DB.

Output format matches `training/fine_tuning/scripts/train_sft.py`:
JSONL rows of: {"instruction": "...", "input": "...", "output": "..."}

Data sources (current DB schema):
- questions: content, student_answer, correct_answer, knowledge_points, tags, error_analysis, explanation...
- exam_corrections: overall_analysis, weak_points, improvement_suggestions, stats...

Notes:
- This is intentionally "no external LLM" so it can run offline.
- The dataset quality improves as the system accumulates more structured fields
  (error_analysis, explanation, weak_points, etc.).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

_p = Path(__file__).resolve()
while _p.name != "training" and _p.parent != _p:
    _p = _p.parent
_repo_root = _p.parent if _p.name == "training" else Path.cwd()
sys.path.insert(0, str(_repo_root))

from training.core.datasets.io import iter_jsonl, write_jsonl, safe_text


def _json_load(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return None
        try:
            return json.loads(s)
        except Exception:
            return s
    return val


def _json_list(val: Any) -> List[str]:
    obj = _json_load(val)
    if obj is None:
        return []
    if isinstance(obj, list):
        return [safe_text(x) for x in obj if safe_text(x)]
    if isinstance(obj, str):
        return [obj] if obj else []
    return []


SUBJECT_DISPLAY = {
    "history": "HISTORY",
    "geography": "GEOGRAPHY",
    "politics": "POLITICS",
    "math": "MATH",
    "physics": "PHYSICS",
    "chemistry": "CHEMISTRY",
    "biology": "BIOLOGY",
    "chinese": "CHINESE",
    "english": "ENGLISH",
    "other": "OTHER",
}


def _normalize_subject(val: Any) -> str:
    s = safe_text(val).strip().lower()
    if not s:
        return "other"

    # Common aliases
    alias = {
        "hist": "history",
        "geo": "geography",
        "political": "politics",
        "chem": "chemistry",
        "bio": "biology",
        "maths": "math",
        "cn": "chinese",
        "zh": "chinese",
        "en": "english",
    }
    s = alias.get(s, s)

    # Some DB rows may store uppercase labels
    if s in SUBJECT_DISPLAY:
        return s

    # Heuristic contains-matching
    if "hist" in s or "history" in s:
        return "history"
    if "geo" in s or "geograph" in s:
        return "geography"
    if "politic" in s:
        return "politics"
    if "phys" in s:
        return "physics"
    if "chem" in s:
        return "chemistry"
    if "bio" in s:
        return "biology"
    if "math" in s:
        return "math"
    if "english" in s:
        return "english"
    if "chinese" in s or "语文" in s or "中文" in s:
        return "chinese"

    return "other"


def _format_question_input(row: sqlite3.Row, subject_norm: str) -> str:
    kp = _json_list(row["knowledge_points"])
    tags = _json_list(row["tags"])
    subj_disp = SUBJECT_DISPLAY.get(subject_norm, safe_text(row["subject"]))
    parts = [
        f"学科: {subj_disp}",
        f"章节: {safe_text(row['chapter'])}" if safe_text(row["chapter"]) else "",
        f"知识点: {', '.join(kp)}" if kp else "",
        f"标签: {', '.join(tags)}" if tags else "",
        "",
        "题目:",
        safe_text(row["content"], max_len=6000),
    ]

    if safe_text(row["student_answer"]):
        parts += ["", "学生作答:", safe_text(row["student_answer"], max_len=2000)]
    if safe_text(row["correct_answer"]):
        parts += ["", "参考答案:", safe_text(row["correct_answer"], max_len=2000)]

    return "\n".join([p for p in parts if p != ""])


def _format_question_output(row: sqlite3.Row) -> Optional[str]:
    ea = safe_text(row["error_analysis"], max_len=6000)
    exp = safe_text(row["explanation"], max_len=6000)
    kp = _json_list(row["knowledge_points"])

    if not (ea or exp or kp):
        return None

    parts: List[str] = []
    if kp:
        parts += ["知识点梳理:", "- " + "\n- ".join(kp), ""]
    if ea:
        parts += ["错因分析:", ea, ""]
    if exp:
        parts += ["题目解析/解题思路:", exp, ""]

    # Simple, stable template suggestions (can be replaced by model output later)
    if kp:
        parts += [
            "复习建议:",
            "- 回到课本/笔记，把以上知识点各自的定义、常见题型和典型陷阱写成一页总结。",
            "- 每个知识点做 3~5 道基础题，确保“概念-方法-步骤”完整。",
            "- 把本题加入错题复习清单：隔 1 天 / 3 天 / 7 天各复习一次。",
        ]

    return "\n".join(parts).strip()


def _expand_subject_filters(subjects: List[str]) -> List[str]:
    subj_vals: List[str] = []
    for s in subjects:
        s = safe_text(s)
        if not s:
            continue
        subj_vals.append(s)
        subj_vals.append(s.upper())
    seen = set()
    subj_vals = [x for x in subj_vals if not (x in seen or seen.add(x))]
    return subj_vals


def iter_sft_rows_from_questions(
    conn: sqlite3.Connection, subjects: List[str], limit: Optional[int]
) -> Iterator[Tuple[str, Dict[str, Any]]]:
    subj_vals = _expand_subject_filters(subjects)

    where = f"subject IN ({', '.join(['?'] * len(subj_vals))})" if subj_vals else "1=1"
    sql = f"""
    SELECT
      id, user_id, subject, content,
      COALESCE(chapter, '') AS chapter,
      COALESCE(knowledge_points, '[]') AS knowledge_points,
      COALESCE(tags, '[]') AS tags,
      COALESCE(student_answer, '') AS student_answer,
      COALESCE(correct_answer, '') AS correct_answer,
      COALESCE(error_analysis, '') AS error_analysis,
      COALESCE(explanation, '') AS explanation
    FROM questions
    WHERE ({where})
    ORDER BY created_at DESC, id DESC
    """
    if limit:
        sql += f" LIMIT {int(limit)}"

    for row in conn.execute(sql, subj_vals).fetchall():
        subject_norm = _normalize_subject(row["subject"])
        out = _format_question_output(row)
        if not out:
            continue
        yield subject_norm, {
            "subject": subject_norm,
            "instruction": "请根据题目与学生作答，指出错误原因，并给出正确思路/解法与复习建议。",
            "input": _format_question_input(row, subject_norm),
            "output": out,
            "meta": {
                "source": "questions",
                "subject": subject_norm,
                "question_id": int(row["id"]),
                "user_id": int(row["user_id"]),
            },
        }


def iter_sft_rows_from_exam_corrections(
    conn: sqlite3.Connection, subjects: List[str], limit: Optional[int]
) -> Iterator[Tuple[str, Dict[str, Any]]]:
    subj_vals = _expand_subject_filters(subjects)

    where = f"subject IN ({', '.join(['?'] * len(subj_vals))})" if subj_vals else "1=1"
    sql = f"""
    SELECT
      id, user_id, subject,
      COALESCE(grade, '') AS grade,
      COALESCE(exam_title, '') AS exam_title,
      COALESCE(total_score, 0) AS total_score,
      COALESCE(max_score, 100) AS max_score,
      COALESCE(accuracy_rate, 0) AS accuracy_rate,
      COALESCE(question_count, 0) AS question_count,
      COALESCE(wrong_count, 0) AS wrong_count,
      COALESCE(overall_analysis, '') AS overall_analysis,
      COALESCE(weak_points, '[]') AS weak_points,
      COALESCE(improvement_suggestions, '[]') AS improvement_suggestions
    FROM exam_corrections
    WHERE ({where})
    ORDER BY created_at DESC, id DESC
    """
    if limit:
        sql += f" LIMIT {int(limit)}"

    for row in conn.execute(sql, subj_vals).fetchall():
        subject_norm = _normalize_subject(row["subject"])
        weak = _json_list(row["weak_points"])
        sugg = _json_list(row["improvement_suggestions"])
        overall = safe_text(row["overall_analysis"], max_len=8000)

        if not (weak or sugg or overall):
            continue

        subj_disp = SUBJECT_DISPLAY.get(subject_norm, safe_text(row["subject"]))
        input_parts = [
            f"学科: {subj_disp}",
            f"年级: {safe_text(row['grade'])}" if safe_text(row["grade"]) else "",
            f"试卷: {safe_text(row['exam_title'])}" if safe_text(row["exam_title"]) else "",
            f"得分: {row['total_score']}/{row['max_score']} (正确率: {row['accuracy_rate']})",
            f"题量: {row['question_count']} (错题: {row['wrong_count']})",
            "",
            "薄弱知识点(系统统计):",
            "- " + "\n- ".join(weak) if weak else "(无)",
            "",
            "总体分析(系统/老师/AI):",
            overall if overall else "(无)",
        ]
        input_text = "\n".join([p for p in input_parts if p != ""]).strip()

        output_parts: List[str] = []
        if weak:
            output_parts += ["薄弱点结论:", "- " + "\n- ".join(weak), ""]
        if overall:
            output_parts += ["学习诊断:", overall, ""]
        if sugg:
            output_parts += ["改进建议:", "- " + "\n- ".join(sugg), ""]

        # Minimal daily plan template (fine-tuning target)
        if weak:
            output_parts += [
                "7天学习/复习计划(示例):",
                "第1-2天：逐个薄弱点回归概念 + 例题；每天 30-45 分钟。",
                "第3-4天：每个薄弱点做 5-10 道分层练习（基础→提高）。",
                "第5天：综合套题/真题小练，记录仍错的题型。",
                "第6天：错题复盘 + 总结模板化步骤（如何审题、列条件、检查）。",
                "第7天：回顾薄弱点清单 + 轻量巩固（2-3题/点）。",
            ]

        yield subject_norm, {
            "subject": subject_norm,
            "instruction": "请根据本次试卷批改统计，提炼薄弱知识点，并给出可执行的学习/复习计划。",
            "input": input_text,
            "output": "\n".join(output_parts).strip(),
            "meta": {
                "source": "exam_corrections",
                "subject": subject_norm,
                "exam_correction_id": int(row["id"]),
                "user_id": int(row["user_id"]),
            },
        }


def _iter_extra_sft_rows(extra_dir: Path) -> Iterator[Tuple[str, Dict[str, Any]]]:
    """
    Reads extra SFT jsonl from a directory.

    Supported layouts:
    - <extra_dir>/<subject>/*.jsonl
    - <extra_dir>/**/*.jsonl with rows that contain {"subject": "..."}
    """
    if not extra_dir.exists():
        return

    for p in sorted(extra_dir.glob("**/*.jsonl")):
        rel = p.relative_to(extra_dir)
        subject_hint = rel.parts[0] if rel.parts else "other"
        for row in iter_jsonl(p):
            subj = _normalize_subject(row.get("subject") or row.get("meta", {}).get("subject") or subject_hint)
            row["subject"] = subj
            meta = row.get("meta") if isinstance(row.get("meta"), dict) else {}
            meta["subject"] = subj
            row["meta"] = meta
            yield subj, row


def _dedupe_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out: List[Dict[str, Any]] = []
    for r in rows:
        key = (
            safe_text(r.get("instruction")),
            safe_text(r.get("input")),
            safe_text(r.get("output")),
            safe_text(r.get("subject")),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def main():
    parser = argparse.ArgumentParser(description="Prepare Wzm SFT dataset")
    parser.add_argument(
        "--sqlite",
        default=str(_repo_root / "data" / "sqlite" / "app.db"),
        help="Path to app SQLite DB",
    )
    parser.add_argument(
        "--output-dir",
        default=str(_repo_root / "data" / "training" / "wzm" / "datasets" / "sft"),
        help="Output base directory. Per-subject files are written to <output-dir>/<subject>/train.jsonl",
    )
    parser.add_argument(
        "--legacy-output",
        default=str(_repo_root / "data" / "training" / "wzm" / "datasets" / "sft" / "train.jsonl"),
        help="Optional legacy single-file output (merged across subjects). Set to empty to disable.",
    )
    parser.add_argument(
        "--subjects",
        nargs="*",
        default=["history", "geography", "other"],
        help="Subjects to include",
    )
    parser.add_argument(
        "--extra-sft-dir",
        default="",
        help="Optional extra SFT directory to merge (e.g. web-ingested data). Supports <dir>/<subject>/*.jsonl.",
    )
    parser.add_argument(
        "--write-split-artifacts",
        action="store_true",
        help="Also write train_db.jsonl and train_extra.jsonl per subject for inspection.",
    )
    parser.add_argument("--limit", type=int, default=0, help="Optional limit for smoke runs")
    args = parser.parse_args()

    sqlite_path = Path(args.sqlite)
    if not sqlite_path.exists():
        raise FileNotFoundError(f"SQLite DB not found: {sqlite_path}")

    out_base = Path(args.output_dir)
    out_base.mkdir(parents=True, exist_ok=True)

    limit = int(args.limit) if int(args.limit) > 0 else None

    conn = sqlite3.connect(str(sqlite_path))
    conn.row_factory = sqlite3.Row
    try:
        db_rows_by_subject: Dict[str, List[Dict[str, Any]]] = {}
        for subj, r in iter_sft_rows_from_questions(conn, args.subjects, limit):
            db_rows_by_subject.setdefault(subj, []).append(r)
        for subj, r in iter_sft_rows_from_exam_corrections(conn, args.subjects, limit):
            db_rows_by_subject.setdefault(subj, []).append(r)
    finally:
        conn.close()

    extra_rows_by_subject: Dict[str, List[Dict[str, Any]]] = {}
    if safe_text(args.extra_sft_dir):
        extra_dir = Path(args.extra_sft_dir)
        for subj, r in _iter_extra_sft_rows(extra_dir):
            extra_rows_by_subject.setdefault(subj, []).append(r)

    # Write per-subject datasets (merged)
    total = 0
    subjects_to_write = sorted(set(list(db_rows_by_subject.keys()) + list(extra_rows_by_subject.keys())))
    for subj in subjects_to_write:
        db_rows = db_rows_by_subject.get(subj, [])
        extra_rows = extra_rows_by_subject.get(subj, [])
        merged = _dedupe_rows(db_rows + extra_rows)

        subj_dir = out_base / subj
        subj_dir.mkdir(parents=True, exist_ok=True)

        if args.write_split_artifacts:
            write_jsonl(subj_dir / "train_db.jsonl", _dedupe_rows(db_rows))
            if extra_rows:
                write_jsonl(subj_dir / "train_extra.jsonl", _dedupe_rows(extra_rows))

        n = write_jsonl(subj_dir / "train.jsonl", merged)
        total += n
        print(f"✅ wrote {n} rows to {subj_dir / 'train.jsonl'} (db={len(db_rows)}, extra={len(extra_rows)})")

    # Optional legacy output for backwards compatibility
    legacy_path = Path(args.legacy_output) if safe_text(args.legacy_output) else None
    if legacy_path is not None:
        legacy_path.parent.mkdir(parents=True, exist_ok=True)
        legacy_rows: List[Dict[str, Any]] = []
        for subj in subjects_to_write:
            legacy_rows.extend(_dedupe_rows(db_rows_by_subject.get(subj, []) + extra_rows_by_subject.get(subj, [])))
        legacy_rows = _dedupe_rows(legacy_rows)
        n_legacy = write_jsonl(legacy_path, legacy_rows)
        print(f"✅ wrote {n_legacy} rows to legacy output {legacy_path}")
    print(f"🎯 total per-subject rows written: {total}")


if __name__ == "__main__":
    main()

