#!/usr/bin/env python3
"""
Fetch free/public datasets from the Internet (HuggingFace Datasets) and convert them into
Tony SFT JSONL rows, split by subject.

Why this exists:
- Users asked for 10k+ (<=50k) extra "subject question" data fetched from the Internet.
- We keep this separate from DB-based SFT preparation so it can be enabled/disabled and audited.

Important:
- Only fetch datasets that are free/open and comply with the dataset license.
- This script intentionally generates a *minimal, non-hallucinated* assistant response:
  it outputs the correct option and generic revision direction (no fabricated detailed rationale).

Output layout (default):
  data/training/tony/datasets/sft_web/<subject>/train_web.jsonl
"""

from __future__ import annotations

import argparse
import os
import random
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

_p = Path(__file__).resolve()
while _p.name != "training" and _p.parent != _p:
    _p = _p.parent
_repo_root = _p.parent if _p.name == "training" else Path.cwd()
sys.path.insert(0, str(_repo_root))

from training.core.datasets.io import write_jsonl, safe_text


def _require_datasets():
    try:
        import datasets  # type: ignore

        return datasets
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "Missing dependency: datasets. Install with: pip install datasets>=2.16.0 "
            "(or `pip install -r requirements.txt`)."
        ) from e


def _hf_get_dataset_config_names(dataset_name: str) -> List[str]:
    ds = _require_datasets()
    return list(ds.get_dataset_config_names(dataset_name))


def _hf_load_dataset(dataset_name: str, config: Optional[str], split: str):
    ds = _require_datasets()
    if config is None:
        return ds.load_dataset(dataset_name, split=split)
    return ds.load_dataset(dataset_name, config, split=split)


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


def normalize_subject(s: str) -> str:
    s = safe_text(s).strip().lower()
    if not s:
        return "other"
    # K12 / exam naming patterns
    if "middle_school" in s or "junior" in s:
        # Let the later subject keyword decide
        pass
    if "high_school" in s or "senior" in s:
        pass
    if "history" in s or s.endswith("_history") or "world_history" in s or "us_history" in s:
        return "history"
    if "geography" in s:
        return "geography"
    if "politic" in s or "government" in s or "law" in s:
        return "politics"
    if "math" in s:
        return "math"
    if "physics" in s:
        return "physics"
    if "chem" in s:
        return "chemistry"
    if "bio" in s:
        return "biology"
    if "english" in s:
        return "english"
    if "chinese" in s:
        return "chinese"
    return "other"


def _letter(idx: int) -> str:
    return "ABCD"[idx] if 0 <= idx <= 3 else str(idx)


def _format_mcq_input(subject_norm: str, question: str, choices: List[str], student_answer: Optional[str]) -> str:
    subj_disp = SUBJECT_DISPLAY.get(subject_norm, subject_norm.upper())
    parts = [f"学科: {subj_disp}", "", "题目:", safe_text(question, max_len=6000).strip(), "", "选项:"]
    for i, c in enumerate(choices[:4]):
        parts.append(f"{_letter(i)}. {safe_text(c, max_len=1500).strip()}")
    if student_answer:
        parts += ["", "学生作答:", student_answer]
    return "\n".join([p for p in parts if p != ""]).strip()


def _format_mcq_output(correct_letter: str) -> str:
    # Minimal response: correct option + generic revision direction (no fabricated detailed rationale)
    return "\n".join(
        [
            f"正确答案: {correct_letter}",
            "",
            "复习方向:",
            "- 回到对应章节，梳理本题涉及的核心概念/条件/史实与常见干扰项。",
            "- 总结“题干关键词 → 对应知识点 → 排除干扰项”的解题流程，做 3-5 道同类题巩固。",
            "- 将本题加入错题清单：隔 1 天 / 3 天 / 7 天复习一次。",
        ]
    ).strip()

def _try_get_configs(dataset_names: List[str]) -> tuple[str, List[str]]:
    last_err: Optional[Exception] = None
    for name in dataset_names:
        try:
            cfgs = _hf_get_dataset_config_names(name)
            return name, cfgs
        except Exception as e:  # pragma: no cover
            last_err = e
            continue
    raise RuntimeError(f"Failed to list configs for any of: {dataset_names}. Last error: {last_err}") from last_err


def _try_load_dataset(dataset_names: List[str], config: str, split: str):
    last_err: Optional[Exception] = None
    for name in dataset_names:
        try:
            return name, _hf_load_dataset(name, config, split)
        except Exception as e:  # pragma: no cover
            last_err = e
            continue
    raise RuntimeError(
        f"Failed to load dataset for any of: {dataset_names}, config={config}, split={split}. Last error: {last_err}"
    ) from last_err


def _try_load_dataset_splits(dataset_names: List[str], config: str, splits: List[str]):
    last_err: Optional[Exception] = None
    for sp in splits:
        try:
            name, ds = _try_load_dataset(dataset_names, config, sp)
            return name, ds, sp
        except Exception as e:  # pragma: no cover
            last_err = e
            continue
    raise RuntimeError(
        f"Failed to load dataset for any of: {dataset_names}, config={config}, splits={splits}. Last error: {last_err}"
    ) from last_err


def _try_load_dataset_no_config(dataset_names: List[str], split: str):
    last_err: Optional[Exception] = None
    for name in dataset_names:
        try:
            return name, _hf_load_dataset(name, config=None, split=split)  # type: ignore[arg-type]
        except Exception as e:  # pragma: no cover
            last_err = e
            continue
    raise RuntimeError(
        f"Failed to load dataset for any of: {dataset_names}, split={split}. Last error: {last_err}"
    ) from last_err


def _try_load_dataset_no_config_splits(dataset_names: List[str], splits: List[str]):
    last_err: Optional[Exception] = None
    for sp in splits:
        try:
            name, ds = _try_load_dataset_no_config(dataset_names, sp)
            return name, ds, sp
        except Exception as e:  # pragma: no cover
            last_err = e
            continue
    raise RuntimeError(
        f"Failed to load dataset for any of: {dataset_names}, splits={splits}. Last error: {last_err}"
    ) from last_err


def _extract_question(ex: Dict[str, Any]) -> str:
    for k in ["question", "query", "prompt", "problem", "stem"]:
        q = safe_text(ex.get(k))
        if q:
            return q
    return ""


def _extract_choices(ex: Dict[str, Any]) -> List[str]:
    # Common formats:
    # - {"A": "...", "B": "...", "C": "...", "D": "..."}
    # - {"options": ["..","..","..",".."]} / {"choices": [...]}
    # - {"options": {"A": "...", ...}}
    # - {"choices": {"A": "...", ...}}
    for k in ["options", "choices", "option", "candidates"]:
        v = ex.get(k)
        if isinstance(v, list):
            out = [safe_text(x) for x in v if safe_text(x)]
            return out[:4]
        if isinstance(v, dict):
            # Prefer ordered A-D keys if present
            if all(x in v for x in ["A", "B"]):
                out = [safe_text(v.get(x)) for x in ["A", "B", "C", "D"] if safe_text(v.get(x))]
                return out[:4]
            # Otherwise dict values
            out = [safe_text(x) for x in v.values() if safe_text(x)]
            return out[:4]
        if isinstance(v, str):
            # Sometimes serialized; keep as a single blob (not ideal but better than empty)
            s = safe_text(v)
            if s:
                return [s]

    # Direct A/B/C/D fields
    if any(ex.get(x) for x in ["A", "B", "C", "D"]):
        out = [safe_text(ex.get(x)) for x in ["A", "B", "C", "D"] if safe_text(ex.get(x))]
        return out[:4]

    return []


def _extract_answer_letter(ex: Dict[str, Any]) -> str:
    for k in ["answer", "gold", "label", "target", "correct", "correct_answer"]:
        v = ex.get(k)
        if isinstance(v, int) and 0 <= v <= 3:
            return _letter(v)
        s = safe_text(v).strip().upper()
        if s in {"A", "B", "C", "D"}:
            return s
        # Sometimes "0/1/2/3"
        if s.isdigit():
            try:
                n = int(s)
                if 0 <= n <= 3:
                    return _letter(n)
            except Exception:
                pass
        # Sometimes like "答案：A"
        for ch in ["A", "B", "C", "D"]:
            if ch in s:
                return ch
    return ""


def iter_mmlu_rows(
    *,
    max_items: int,
    seed: int,
    include_subjects: Optional[List[str]],
) -> Iterator[Tuple[str, Dict[str, Any]]]:
    """
    Pulls from HF dataset `cais/mmlu` across all configs (subtasks).
    Total volume can exceed 10k across all tasks.
    """
    rng = random.Random(seed)
    dataset_name = "cais/mmlu"

    configs = _hf_get_dataset_config_names(dataset_name)
    # Use test split; it exists for most configs and keeps consistent schema
    split = "test"

    remaining = max_items
    for cfg in configs:
        if remaining <= 0:
            break
        subject_norm = normalize_subject(cfg)
        if include_subjects and subject_norm not in include_subjects:
            continue

        ds = _hf_load_dataset(dataset_name, cfg, split)
        for ex in ds:
            if remaining <= 0:
                break
            q = safe_text(ex.get("question"))
            choices = ex.get("choices") or []
            if not q or not isinstance(choices, list) or len(choices) < 2:
                continue
            ans = ex.get("answer")
            if isinstance(ans, int):
                correct = _letter(ans)
            else:
                # Some variants may store letter strings
                correct = safe_text(ans).strip().upper()[:1]
                if correct not in {"A", "B", "C", "D"}:
                    continue

            # Create a "wrong" student answer for "错题" style; keep deterministic but varied
            wrong_pool = [c for c in ["A", "B", "C", "D"] if c != correct]
            student = rng.choice(wrong_pool) if wrong_pool else None

            row = {
                "subject": subject_norm,
                "instruction": "请解答下列选择题：给出正确选项，并用 1-3 句话给出复习方向（不要编造具体教材页码）。",
                "input": _format_mcq_input(subject_norm, q, [safe_text(x) for x in choices], student),
                "output": _format_mcq_output(correct),
                "meta": {
                    "source": "hf",
                    "dataset": dataset_name,
                    "config": cfg,
                    "split": split,
                    "subject": subject_norm,
                },
            }
            remaining -= 1
            yield subject_norm, row


def iter_ceval_rows(
    *,
    max_items: int,
    seed: int,
    include_subjects: Optional[List[str]],
) -> Iterator[Tuple[str, Dict[str, Any]]]:
    """
    Pulls from the Chinese exam-style dataset C-Eval.

    C-Eval has many K12-like subjects, including high_school_* and middle_school_* tasks.
    Repo id can vary; we try a few common names.
    """
    rng = random.Random(seed)
    candidate_names = [
        "ceval/ceval-exam",
        "ceval/ceval",
        "C-Eval/C-Eval",
    ]
    dataset_name, configs = _try_get_configs(candidate_names)
    split = "val"

    remaining = max_items
    for cfg in configs:
        if remaining <= 0:
            break
        subject_norm = normalize_subject(cfg)
        if include_subjects and subject_norm not in include_subjects:
            continue

        used_name, ds = _try_load_dataset(candidate_names, cfg, split)
        # keep dataset_name consistent for meta
        dataset_name = used_name
        for ex in ds:
            if remaining <= 0:
                break

            q = safe_text(ex.get("question"))
            if not q:
                continue

            # typical schema: A/B/C/D columns + answer letter
            choices = [
                safe_text(ex.get("A")),
                safe_text(ex.get("B")),
                safe_text(ex.get("C")),
                safe_text(ex.get("D")),
            ]
            if sum(1 for c in choices if c) < 2:
                # some variants may store options as list
                opt = ex.get("choices") or ex.get("options")
                if isinstance(opt, list):
                    choices = [safe_text(x) for x in opt][:4]
            choices = [c for c in choices if c][:4]
            if len(choices) < 2:
                continue

            ans = safe_text(ex.get("answer")).strip().upper()[:1]
            if ans not in {"A", "B", "C", "D"}:
                # sometimes numeric
                raw = ex.get("answer")
                if isinstance(raw, int) and 0 <= raw <= 3:
                    ans = _letter(raw)
                else:
                    continue

            wrong_pool = [c for c in ["A", "B", "C", "D"] if c != ans]
            student = rng.choice(wrong_pool) if wrong_pool else None

            row = {
                "subject": subject_norm,
                "instruction": "请解答下列选择题：给出正确选项，并用 1-3 句话给出复习方向（不要编造具体教材页码）。",
                "input": _format_mcq_input(subject_norm, q, choices, student),
                "output": _format_mcq_output(ans),
                "meta": {
                    "source": "hf",
                    "dataset": dataset_name,
                    "config": cfg,
                    "split": split,
                    "subject": subject_norm,
                },
            }
            remaining -= 1
            yield subject_norm, row


def iter_race_rows(
    *,
    max_items: int,
    seed: int,
    include_subjects: Optional[List[str]],
) -> Iterator[Tuple[str, Dict[str, Any]]]:
    """
    Pulls from RACE (English exams for Chinese middle/high school students).

    This is K12 exam-style but not a Chinese-language question bank; we map it to subject=english.
    """
    rng = random.Random(seed)
    subject_norm = "english"
    if include_subjects and subject_norm not in include_subjects:
        return

    candidate_names = ["race", "ehovy/race"]
    dataset_name = candidate_names[0]
    split = "train"
    remaining = max_items

    for cfg in ["middle", "high"]:
        if remaining <= 0:
            break
        used_name, ds = _try_load_dataset(candidate_names, cfg, split)
        dataset_name = used_name
        for ex in ds:
            if remaining <= 0:
                break
            article = safe_text(ex.get("article"), max_len=2500).strip()
            q = safe_text(ex.get("question"), max_len=800).strip()
            opts = ex.get("options")
            if not q or not isinstance(opts, list) or len(opts) < 2:
                continue
            choices = [safe_text(x, max_len=800).strip() for x in opts][:4]
            # RACE answer is one of "A/B/C/D"
            ans = safe_text(ex.get("answer")).strip().upper()[:1]
            if ans not in {"A", "B", "C", "D"}:
                continue

            wrong_pool = [c for c in ["A", "B", "C", "D"] if c != ans]
            student = rng.choice(wrong_pool) if wrong_pool else None

            # include reading passage as context
            input_text = "\n".join(
                [
                    f"学科: {SUBJECT_DISPLAY.get(subject_norm)}",
                    f"来源: RACE-{cfg}",
                    "",
                    "阅读材料:",
                    article,
                    "",
                    "问题:",
                    q,
                    "",
                    "选项:",
                    "\n".join([f"{_letter(i)}. {c}" for i, c in enumerate(choices)]),
                    "",
                    "学生作答:",
                    student or "(未作答)",
                ]
            ).strip()

            row = {
                "subject": subject_norm,
                "instruction": "请解答下列阅读理解选择题：给出正确选项，并用 1-3 句话给出复习方向（词汇/语法/主旨/细节定位）。",
                "input": input_text,
                "output": _format_mcq_output(ans),
                "meta": {
                    "source": "hf",
                    "dataset": dataset_name,
                    "config": cfg,
                    "split": split,
                    "subject": subject_norm,
                },
            }
            remaining -= 1
            yield subject_norm, row


def iter_gaokao_bench_rows(
    *,
    max_items: int,
    seed: int,
    include_subjects: Optional[List[str]],
) -> Iterator[Tuple[str, Dict[str, Any]]]:
    """
    Pulls from RUCAIBox/gaokao-bench (Gaokao exam benchmark).

    Notes:
    - Mostly "test" split; used for eval. We can still use it as SFT-style MCQ training data.
    - Config names usually encode subject/year slices; we map config_name to subject via heuristics.
    """
    rng = random.Random(seed)
    candidate_names = ["RUCAIBox/gaokao-bench"]
    dataset_name, configs = _try_get_configs(candidate_names)
    # many configs are test-only
    split_candidates = ["train", "validation", "val", "test"]

    remaining = max_items
    for cfg in configs:
        if remaining <= 0:
            break
        subject_norm = normalize_subject(cfg)
        if include_subjects and subject_norm not in include_subjects:
            continue

        used_name, ds, split = _try_load_dataset_splits(candidate_names, cfg, split_candidates)
        dataset_name = used_name
        for ex in ds:
            if remaining <= 0:
                break
            if not isinstance(ex, dict):
                continue
            q = _extract_question(ex)
            choices = _extract_choices(ex)
            ans = _extract_answer_letter(ex)
            if not q or not choices or not ans:
                continue

            wrong_pool = [c for c in ["A", "B", "C", "D"] if c != ans]
            student = rng.choice(wrong_pool) if wrong_pool else None

            row = {
                "subject": subject_norm,
                "instruction": "请解答下列选择题：给出正确选项，并用 1-3 句话给出复习方向（不要编造具体教材页码）。",
                "input": _format_mcq_input(subject_norm, q, choices, student),
                "output": _format_mcq_output(ans),
                "meta": {
                    "source": "hf",
                    "dataset": dataset_name,
                    "config": cfg,
                    "split": split,
                    "subject": subject_norm,
                },
            }
            remaining -= 1
            yield subject_norm, row


def iter_agieval_gaokao_chinese_rows(
    *,
    max_items: int,
    seed: int,
    include_subjects: Optional[List[str]],
) -> Iterator[Tuple[str, Dict[str, Any]]]:
    """
    Pulls from hails/agieval-gaokao-chinese.

    Expected schema (per user):
    - query: question text
    - choices: list of options
    - gold: correct answer label (A/B/C/D or 0-3)

    Subject is forced to `chinese` (gaokao-chinese).
    """
    rng = random.Random(seed)
    subject_norm = "chinese"
    if include_subjects and subject_norm not in include_subjects:
        return

    candidate_names = ["hails/agieval-gaokao-chinese"]
    split_candidates = ["train", "validation", "val", "test"]
    dataset_name, ds, split = _try_load_dataset_no_config_splits(candidate_names, split_candidates)

    remaining = max_items
    for ex in ds:
        if remaining <= 0:
            break
        if not isinstance(ex, dict):
            continue

        q = safe_text(ex.get("query")) or _extract_question(ex)
        choices_raw = ex.get("choices")
        if isinstance(choices_raw, list):
            choices = [safe_text(x) for x in choices_raw if safe_text(x)][:4]
        else:
            choices = _extract_choices(ex)
        ans = _extract_answer_letter({"gold": ex.get("gold"), "answer": ex.get("answer"), "label": ex.get("label")})

        if not q or len(choices) < 2 or not ans:
            continue

        wrong_pool = [c for c in ["A", "B", "C", "D"] if c != ans]
        student = rng.choice(wrong_pool) if wrong_pool else None

        row = {
            "subject": subject_norm,
            "instruction": "请解答下列高考语文选择题：给出正确选项，并用 1-3 句话给出复习方向（不要编造具体教材页码）。",
            "input": _format_mcq_input(subject_norm, q, choices, student),
            "output": _format_mcq_output(ans),
            "meta": {
                "source": "hf",
                "dataset": dataset_name,
                "config": None,
                "split": split,
                "subject": subject_norm,
            },
        }
        remaining -= 1
        yield subject_norm, row


def _dedupe(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out: List[Dict[str, Any]] = []
    for r in rows:
        key = (safe_text(r.get("subject")), safe_text(r.get("input")), safe_text(r.get("output")))
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch web (HF) subject datasets and convert to Tony SFT JSONL")
    parser.add_argument(
        "--provider",
        default="hf-mmlu",
        choices=["hf-mmlu", "hf-ceval", "hf-race", "hf-gaokao-bench", "hf-agieval-gaokao-chinese"],
        help=(
            "Which web provider to use. "
            "hf-mmlu: cais/mmlu (general academic). "
            "hf-ceval: C-Eval Chinese exam style (closer to K12/gaokao-like multiple-choice). "
            "hf-race: RACE English exams (K12 reading comprehension). "
            "hf-gaokao-bench: RUCAIBox/gaokao-bench (Gaokao cross-subject MCQ benchmark). "
            "hf-agieval-gaokao-chinese: hails/agieval-gaokao-chinese (Gaokao Chinese MCQ: query+choices+gold)."
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=str(_repo_root / "data" / "training" / "tony" / "datasets" / "sft_web"),
        help="Base output dir. Writes to <output-dir>/<subject>/train_web.jsonl",
    )
    parser.add_argument("--min-total", type=int, default=10000, help="Minimum rows to fetch (best effort).")
    parser.add_argument("--max-total", type=int, default=50000, help="Maximum rows to fetch (hard cap).")
    parser.add_argument(
        "--all-proxy",
        default="",
        help='Optional: set env var ALL_PROXY for this run (example: "socks5h://127.0.0.1:10800"). '
        "This script does NOT import socks; ensure your environment has SOCKS-capable deps installed "
        "(e.g. requests[socks]/huggingface_hub[socks]).",
    )
    parser.add_argument(
        "--no-proxy",
        action="store_true",
        help="Ignore proxy env vars (HTTP_PROXY/HTTPS_PROXY/ALL_PROXY). Useful if proxy is misconfigured.",
    )
    parser.add_argument(
        "--subjects",
        nargs="*",
        default=[],
        help="Optional subject filters (history/geography/politics/math/...). Empty means all.",
    )
    parser.add_argument("--seed", type=int, default=7, help="Random seed (wrong-answer selection, sampling).")
    args = parser.parse_args()

    if safe_text(args.all_proxy):
        os.environ["ALL_PROXY"] = safe_text(args.all_proxy)

    if bool(args.no_proxy):
        for k in ["ALL_PROXY", "HTTPS_PROXY", "HTTP_PROXY", "all_proxy", "https_proxy", "http_proxy"]:
            os.environ.pop(k, None)

    max_total = int(args.max_total)
    if max_total <= 0:
        raise ValueError("--max-total must be > 0")
    if max_total > 50000:
        raise ValueError("--max-total must be <= 50000 (requested cap)")

    include_subjects = [normalize_subject(x) for x in args.subjects] if args.subjects else None

    out_base = Path(args.output_dir)
    out_base.mkdir(parents=True, exist_ok=True)

    rows_by_subject: Dict[str, List[Dict[str, Any]]] = {}
    try:
        if args.provider == "hf-mmlu":
            for subj, row in iter_mmlu_rows(max_items=max_total, seed=int(args.seed), include_subjects=include_subjects):
                rows_by_subject.setdefault(subj, []).append(row)
        elif args.provider == "hf-ceval":
            for subj, row in iter_ceval_rows(max_items=max_total, seed=int(args.seed), include_subjects=include_subjects):
                rows_by_subject.setdefault(subj, []).append(row)
        elif args.provider == "hf-race":
            for subj, row in iter_race_rows(max_items=max_total, seed=int(args.seed), include_subjects=include_subjects):
                rows_by_subject.setdefault(subj, []).append(row)
        elif args.provider == "hf-gaokao-bench":
            for subj, row in iter_gaokao_bench_rows(
                max_items=max_total, seed=int(args.seed), include_subjects=include_subjects
            ):
                rows_by_subject.setdefault(subj, []).append(row)
        elif args.provider == "hf-agieval-gaokao-chinese":
            for subj, row in iter_agieval_gaokao_chinese_rows(
                max_items=max_total, seed=int(args.seed), include_subjects=include_subjects
            ):
                rows_by_subject.setdefault(subj, []).append(row)
        else:  # pragma: no cover
            raise ValueError(f"Unknown provider: {args.provider}")
    except Exception as e:
        msg = str(e)
        if "Missing dependencies for SOCKS support" in msg:
            raise RuntimeError(
                "SOCKS proxy detected but missing SOCKS dependencies.\n\n"
                "You can fix it by installing one of:\n"
                "- `pip install PySocks` (recommended)\n"
                "- `pip install 'requests[socks]'`\n\n"
                "If your shell already has `ALL_PROXY=socks5h://...` set, pip may fail *before* it can\n"
                "download PySocks. In that case, temporarily disable proxies for the install:\n"
                "- `env -u ALL_PROXY -u all_proxy -u HTTP_PROXY -u http_proxy -u HTTPS_PROXY -u https_proxy pip install PySocks`\n\n"
                "Or disable proxies for this run:\n"
                "- add `--no-proxy`\n"
            ) from e
        raise

    # TODO(student modules):
    # - wzy/wzm/rpj/xmx should implement their own subject-specific providers
    #   by reusing the patterns in this script (HF dataset -> SFT JSONL -> per-subject output).

    total = 0
    for subj, rows in sorted(rows_by_subject.items(), key=lambda x: x[0]):
        rows = _dedupe(rows)
        p = out_base / subj / "train_web.jsonl"
        n = write_jsonl(p, rows)
        total += n
        print(f"✅ wrote {n} web rows to {p}")

    if total < int(args.min_total):
        print(
            f"⚠️ fetched {total} (< min-total {int(args.min_total)}). "
            "Try widening subject filters or adding more providers."
        )
    else:
        print(f"🎯 fetched total web rows: {total}")


if __name__ == "__main__":
    main()

