#!/usr/bin/env python3
"""
Model evaluation (OpenAI-compatible endpoints, e.g. vLLM)

Why this evaluator?
- Many labs/companies use an OpenAI-compatible serving layer (vLLM/TGI/LMDeploy) and run eval
  by calling `/v1/chat/completions` with a fixed prompt set.
- For "soft" tasks (explanations, tutoring tone), a common industry approach is LLM-as-a-judge
  with a rubric. We support that optionally.

This script supports:
1) Basic automatic metrics (lightweight, no extra deps):
   - exact match / option match (for MCQ)
   - token/character F1 overlap (for short reference answers)
2) Optional rubric judge:
   - If `--judge-api-base` is provided, call a judge model to score 1~10 per sample.

Input format (JSONL, one per line):
{
  "id": "optional",
  "messages": [{"role":"user","content":"..."}],  # preferred
  "prompt": "..." ,                              # fallback
  "reference": "..." ,                           # optional
  "type": "freeform|mcq",                        # optional
  "gold": "A"                                    # optional for mcq
}
"""

from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _norm_text(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def _exact_match(pred: str, ref: str) -> Optional[bool]:
    p = _norm_text(pred)
    r = _norm_text(ref)
    if not r:
        return None
    return bool(p == r)


def _lcs_len(a: str, b: str) -> int:
    # LCS over characters (stdlib DP, O(n*m), fine for short eval references)
    a = a or ""
    b = b or ""
    n, m = len(a), len(b)
    if n == 0 or m == 0:
        return 0
    # rolling DP to save memory
    prev = [0] * (m + 1)
    cur = [0] * (m + 1)
    for i in range(1, n + 1):
        ai = a[i - 1]
        for j in range(1, m + 1):
            if ai == b[j - 1]:
                cur[j] = prev[j - 1] + 1
            else:
                cur[j] = prev[j] if prev[j] >= cur[j - 1] else cur[j - 1]
        prev, cur = cur, prev
    return int(prev[m])


def _rouge_l_f1(pred: str, ref: str) -> Optional[float]:
    """
    ROUGE-L F1 based on char-level LCS (language-agnostic, works for Chinese without tokenizers).
    """
    p = _norm_text(pred)
    r = _norm_text(ref)
    if not p or not r:
        return None
    lcs = _lcs_len(p, r)
    if lcs <= 0:
        return 0.0
    prec = lcs / max(1, len(p))
    rec = lcs / max(1, len(r))
    if prec + rec == 0:
        return 0.0
    return 2 * prec * rec / (prec + rec)


def _char_ngrams(s: str, n: int) -> List[str]:
    s = _norm_text(s)
    if not s:
        return []
    s = s.replace(" ", "")
    if len(s) < n:
        return []
    return [s[i : i + n] for i in range(0, len(s) - n + 1)]


def _bleu4_char(pred: str, ref: str) -> Optional[float]:
    """
    Tiny BLEU-4 (char n-gram) with brevity penalty.
    This is not sacrebleu; it's a lightweight proxy for classroom eval.
    """
    p = _norm_text(pred).replace(" ", "")
    r = _norm_text(ref).replace(" ", "")
    if not p or not r:
        return None
    import math
    from collections import Counter

    precisions: List[float] = []
    for n in (1, 2, 3, 4):
        pn = _char_ngrams(p, n)
        rn = _char_ngrams(r, n)
        if not pn or not rn:
            precisions.append(0.0)
            continue
        pc = Counter(pn)
        rc = Counter(rn)
        inter = sum((pc & rc).values())
        precisions.append(inter / max(1, sum(pc.values())))
    # geometric mean with smoothing (avoid log(0))
    eps = 1e-12
    score = math.exp(sum(math.log(max(eps, x)) for x in precisions) / 4.0)
    # brevity penalty
    bp = 1.0 if len(p) > len(r) else math.exp(1.0 - (len(r) / max(1, len(p))))
    return float(bp * score)


def _char_f1(pred: str, ref: str) -> Optional[float]:
    """
    Lightweight overlap metric for short answers (no external deps).
    """
    p = _norm_text(pred)
    r = _norm_text(ref)
    if not p or not r:
        return None
    # char-level bag overlap
    from collections import Counter

    pc = Counter(p)
    rc = Counter(r)
    inter = sum((pc & rc).values())
    if inter <= 0:
        return 0.0
    prec = inter / max(1, sum(pc.values()))
    rec = inter / max(1, sum(rc.values()))
    if prec + rec == 0:
        return 0.0
    return 2 * prec * rec / (prec + rec)


_MCQ_RE = re.compile(r"\b([ABCD])\b", re.IGNORECASE)


def _extract_mcq_choice(text: str) -> Optional[str]:
    """
    Best-effort parse for "final answer A/B/C/D".
    """
    t = (text or "").strip()
    if not t:
        return None
    m = _MCQ_RE.search(t[::-1])  # reverse search is tricky; fallback to forward below
    # Actually do a forward scan but prefer the last match (final answer often at end)
    matches = _MCQ_RE.findall(t)
    if not matches:
        return None
    return matches[-1].upper()


@dataclass
class EvalRow:
    id: str
    messages: List[Dict[str, str]]
    reference: str
    typ: str
    gold: str


def load_eval_set(path: Path) -> List[EvalRow]:
    rows: List[EvalRow] = []
    with path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            s = (line or "").strip()
            if not s:
                continue
            obj = json.loads(s)
            rid = str(obj.get("id") or f"row-{i}")
            msgs = obj.get("messages")
            if not msgs:
                prompt = str(obj.get("prompt") or obj.get("input") or "").strip()
                msgs = [{"role": "user", "content": prompt}]
            reference = str(obj.get("reference") or obj.get("expected") or "").strip()
            typ = str(obj.get("type") or "freeform").strip().lower()
            gold = str(obj.get("gold") or "").strip().upper()
            rows.append(EvalRow(id=rid, messages=list(msgs), reference=reference, typ=typ, gold=gold))
    return rows


def _messages_to_prompt(messages: List[Dict[str, str]]) -> str:
    """
    Convert chat messages into a single prompt string for `/v1/completions`.

    This is a robust fallback for OpenAI-compatible servers (e.g. vLLM) when the tokenizer
    has no chat_template and `/v1/chat/completions` returns 400.
    """
    parts: List[str] = []
    for m in (messages or []):
        role = str(m.get("role") or "user").strip().lower()
        content = str(m.get("content") or "").rstrip()
        if not content:
            continue
        if role == "system":
            parts.append(f"System:\n{content}")
        elif role == "assistant":
            parts.append(f"Assistant:\n{content}")
        else:
            parts.append(f"User:\n{content}")
    prompt = "\n\n".join(parts).strip()
    if prompt:
        prompt += "\n\nAssistant:\n"
    return prompt


def _looks_like_missing_chat_template_error(e: Exception) -> bool:
    s = str(e) or ""
    s = s.lower()
    return ("chat template" in s and "must provide" in s) or ("default chat template" in s and "no longer allowed" in s)


async def call_chat(
    *,
    api_base: str,
    api_key: str,
    model: str,
    messages: List[Dict[str, str]],
    temperature: float,
    max_tokens: int,
) -> str:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key or "sk-local", base_url=api_base, timeout=120)
    try:
        res = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=float(temperature),
            max_tokens=int(max_tokens),
        )
        return (res.choices[0].message.content or "").strip()
    except Exception as e:
        # vLLM + transformers>=4.44: tokenizer without chat_template will hard-fail chat-completions.
        # Fall back to the simpler `/v1/completions` API which accepts a plain `prompt`.
        if _looks_like_missing_chat_template_error(e):
            prompt = _messages_to_prompt(messages)
            res2 = await client.completions.create(
                model=model,
                prompt=prompt,
                temperature=float(temperature),
                max_tokens=int(max_tokens),
            )
            # openai-python: `choices[0].text` for completions
            txt = getattr(res2.choices[0], "text", "") if res2 and res2.choices else ""
            return (txt or "").strip()
        raise


def build_judge_prompt(*, user_prompt: str, model_answer: str, reference: str) -> List[Dict[str, str]]:
    rubric = (
        "You are an expert evaluator for a tutoring assistant.\n"
        "Score the assistant answer on a 1-10 scale.\n"
        "Criteria:\n"
        "- correctness (most important)\n"
        "- clarity & structure\n"
        "- helpfulness & actionable study guidance\n"
        "- warmth/encouragement (emotional value)\n"
        "If a reference answer is provided, use it as a correctness anchor.\n"
        "\n"
        "Return ONLY JSON with keys: score (int 1-10), reasons (string).\n"
    )
    payload = {
        "user_prompt": user_prompt,
        "assistant_answer": model_answer,
        "reference": reference,
    }
    return [
        {"role": "system", "content": rubric},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def try_parse_judge_json(text: str) -> Tuple[Optional[int], Optional[str]]:
    t = (text or "").strip()
    if not t:
        return None, None
    # strip markdown fences if any
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?", "", t).strip()
        t = re.sub(r"\n?```$", "", t).strip()
    try:
        obj = json.loads(t)
        score = obj.get("score")
        reasons = obj.get("reasons")
        return (int(score) if score is not None else None), (str(reasons) if reasons is not None else None)
    except Exception:
        return None, None


async def main_async() -> int:
    parser = argparse.ArgumentParser(description="OpenAI-compatible model eval (vLLM)")
    parser.add_argument("--eval-set", required=True, help="Path to eval JSONL")
    parser.add_argument("--api-base", required=True, help="Model API base, e.g. http://127.0.0.1:8001/v1")
    parser.add_argument("--api-key", default="sk-local", help="API key (vLLM usually ignores)")
    parser.add_argument("--model", required=True, help="Model id for requests, e.g. tony-dpo")
    parser.add_argument("--out", required=True, help="Output JSON report path")
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-tokens", type=int, default=800)
    parser.add_argument("--limit", type=int, default=0, help="Optional limit N")

    # Optional judge
    parser.add_argument("--judge-api-base", default="", help="Optional judge base url")
    parser.add_argument("--judge-api-key", default="sk-local")
    parser.add_argument("--judge-model", default="", help="Optional judge model id")
    args = parser.parse_args()

    eval_path = Path(args.eval_set)
    rows = load_eval_set(eval_path)
    if args.limit and args.limit > 0:
        rows = rows[: int(args.limit)]
    if not rows:
        print("No eval rows found.")
        Path(args.out).write_text(json.dumps({"n": 0}, ensure_ascii=False, indent=2), encoding="utf-8")
        return 0

    judge_enabled = bool(args.judge_api_base and args.judge_model)

    per: List[Dict[str, Any]] = []
    start = time.time()
    n_mcq = 0
    mcq_ok = 0
    f1s: List[float] = []
    ems: List[bool] = []
    rouges: List[float] = []
    bleus: List[float] = []
    latencies: List[float] = []
    judge_scores: List[int] = []

    for r in rows:
        t0 = time.time()
        pred = await call_chat(
            api_base=args.api_base,
            api_key=args.api_key,
            model=args.model,
            messages=r.messages,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
        )
        dt = (time.time() - t0) * 1000.0
        latencies.append(float(dt))

        row_out: Dict[str, Any] = {
            "id": r.id,
            "type": r.typ,
            "gold": r.gold,
            "reference": r.reference,
            "pred": pred,
            "latency_ms": dt,
        }

        if r.typ == "mcq" and r.gold:
            n_mcq += 1
            choice = _extract_mcq_choice(pred)
            ok = bool(choice and choice == r.gold)
            row_out["pred_choice"] = choice
            row_out["mcq_correct"] = ok
            if ok:
                mcq_ok += 1

        if r.reference:
            em = _exact_match(pred, r.reference)
            row_out["exact_match"] = em
            if em is True or em is False:
                ems.append(bool(em))

            f1 = _char_f1(pred, r.reference)
            row_out["char_f1"] = f1
            if f1 is not None:
                f1s.append(float(f1))
            rl = _rouge_l_f1(pred, r.reference)
            row_out["rouge_l_f1"] = rl
            if rl is not None:
                rouges.append(float(rl))
            b4 = _bleu4_char(pred, r.reference)
            row_out["bleu4_char"] = b4
            if b4 is not None:
                bleus.append(float(b4))

        if judge_enabled:
            user_prompt = r.messages[-1].get("content", "") if r.messages else ""
            judge_text = await call_chat(
                api_base=args.judge_api_base,
                api_key=args.judge_api_key,
                model=args.judge_model,
                messages=build_judge_prompt(user_prompt=user_prompt, model_answer=pred, reference=r.reference),
                temperature=0.0,
                max_tokens=300,
            )
            score, reasons = try_parse_judge_json(judge_text)
            row_out["judge_raw"] = judge_text
            row_out["judge_score"] = score
            row_out["judge_reasons"] = reasons
            if score is not None:
                judge_scores.append(int(score))

        per.append(row_out)

    def _pct(xs: List[float], p: float) -> Optional[float]:
        if not xs:
            return None
        ys = sorted(xs)
        if len(ys) == 1:
            return float(ys[0])
        # nearest-rank
        k = int(round((p / 100.0) * (len(ys) - 1)))
        k = max(0, min(len(ys) - 1, k))
        return float(ys[k])

    total_ms = (time.time() - start) * 1000.0
    # Conclusion (simple heuristics)
    mcq_acc = (mcq_ok / n_mcq) if n_mcq else None
    avg_f1 = (sum(f1s) / len(f1s)) if f1s else None
    avg_rouge = (sum(rouges) / len(rouges)) if rouges else None
    avg_bleu = (sum(bleus) / len(bleus)) if bleus else None
    avg_judge = (sum(judge_scores) / len(judge_scores)) if judge_scores else None

    notes: List[str] = []
    if mcq_acc is not None:
        notes.append(f"MCQ acc={mcq_acc:.3f} (n={n_mcq})")
    if avg_f1 is not None:
        notes.append(f"char-F1 avg={avg_f1:.3f} (n={len(f1s)})")
    if avg_rouge is not None:
        notes.append(f"ROUGE-L(F1) avg={avg_rouge:.3f} (n={len(rouges)})")
    if avg_bleu is not None:
        notes.append(f"BLEU-4(char) avg={avg_bleu:.3f} (n={len(bleus)})")
    if avg_judge is not None:
        notes.append(f"judge avg={avg_judge:.2f} (n={len(judge_scores)})")

    report = {
        "n": len(rows),
        "api_base": args.api_base,
        "model": args.model,
        "total_latency_ms": total_ms,
        "avg_latency_ms": total_ms / max(1, len(rows)),
        "latency_ms": {
            "p50": _pct(latencies, 50),
            "p95": _pct(latencies, 95),
            "min": min(latencies) if latencies else None,
            "max": max(latencies) if latencies else None,
        },
        "mcq": {
            "n": n_mcq,
            "correct": mcq_ok,
            "acc": mcq_acc,
        },
        "exact_match": {
            "n": len(ems),
            "rate": (sum(1 for x in ems if x) / len(ems)) if ems else None,
        },
        "char_f1": {
            "n": len(f1s),
            "avg": avg_f1,
        },
        "rouge_l_f1": {
            "n": len(rouges),
            "avg": avg_rouge,
        },
        "bleu4_char": {
            "n": len(bleus),
            "avg": avg_bleu,
        },
        "judge": {
            "enabled": judge_enabled,
            "n": len(judge_scores),
            "avg": avg_judge,
        },
        "conclusion": {
            "summary": " | ".join(notes) if notes else "No reference/MCQ fields found; only latency was measured.",
            "recommendations": [
                "If /v1/chat/completions fails due to missing chat_template, inject a vLLM --chat-template at serve time.",
                "Use a larger, module-specific eval set for stable metrics (current set may be minimal).",
                "For tutoring quality, enable a judge endpoint and track judge score trend over time.",
            ],
        },
        "items": per,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote report: {out_path}")
    return 0


def main() -> int:
    import asyncio

    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())

