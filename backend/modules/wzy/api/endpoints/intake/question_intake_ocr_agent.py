"""
错题录入OCR Agent - Question Intake OCR Agent (WZY版本)
专门用于"录入错题"功能，只处理物理和数学学科

功能流程:
1. 接收用户输入 (图片/文字JSON)
2. 图片模式: OCR识别题目内容
3. 文字模式: 大模型处理总结
4. 数据存储 - 保存到数据库（记录原始输入和总结后的输入）
5. 触发异步Embedding
"""

import logging
import json
import os
import time
from typing import Dict, Any, Optional, List, Tuple
from collections import Counter

from langgraph.graph import StateGraph, END

from backend.core.agents.state import QuestionIntakeState
from backend.core.agents.base_agent import BaseAgent
from backend.modules.wzy.config import settings  # WZY配置

logger = logging.getLogger(__name__)

# -------------------------
# Logging helpers (wzy)
# -------------------------
def _ctx(state: Dict[str, Any]) -> str:
    """Compact log context for tracing one intake request across stages."""
    task_id = state.get("task_id")
    user_id = state.get("user_id")
    subject = state.get("subject")
    difficulty = state.get("difficulty")
    input_type = state.get("input_type")
    return f"task={task_id} user={user_id} subject={subject} diff={difficulty} type={input_type}"

def _extract_json_object_loose(raw: str) -> Optional[Dict[str, Any]]:
    """
    Best-effort JSON extractor for *either* a JSON object or a JSON array.
    - If a JSON object is found, return it.
    - If a JSON array is found (common when model outputs results as a top-level list),
      wrap it as {"results": [...]} for backward compatibility with callers.

    Models sometimes prepend/append text or code fences, or include stray braces/brackets.
    This scans for the first parseable top-level JSON object/array.
    """
    if not raw:
        return None
    s = raw.strip()

    def _wrap_if_array(v: Any) -> Optional[Dict[str, Any]]:
        if isinstance(v, dict):
            return v
        if isinstance(v, list):
            return {"results": v}
        return None

    def _try_full(t: str) -> Optional[Dict[str, Any]]:
        tt = (t or "").strip()
        if not tt:
            return None
        if (tt.startswith("{") and tt.endswith("}")) or (tt.startswith("[") and tt.endswith("]")):
            try:
                return _wrap_if_array(json.loads(tt))
            except Exception:
                return None
        return None

    def _scan_balanced(t: str, open_ch: str, close_ch: str) -> Optional[Dict[str, Any]]:
        if not t:
            return None
        start_positions = [i for i, ch in enumerate(t) if ch == open_ch][:50]
        for start in start_positions:
            depth = 0
            for end in range(start, min(len(t), start + 50000)):
                ch = t[end]
                if ch == open_ch:
                    depth += 1
                elif ch == close_ch:
                    depth -= 1
                    if depth == 0:
                        candidate = t[start : end + 1]
                        try:
                            parsed = json.loads(candidate)
                            wrapped = _wrap_if_array(parsed)
                            if wrapped is not None:
                                return wrapped
                        except Exception:
                            # keep scanning; later balanced segment may be valid JSON
                            continue
        return None

    def _parse_any(t: str) -> Optional[Dict[str, Any]]:
        # 1) Full-string parse (fast)
        got = _try_full(t)
        if got is not None:
            return got
        # 2) Balanced object scan
        got = _scan_balanced(t, "{", "}")
        if got is not None:
            return got
        # 3) Balanced array scan
        got = _scan_balanced(t, "[", "]")
        if got is not None:
            return got
        return None

    # If code fences exist, try each fenced segment first (pick the one that parses)
    if "```" in s:
        s2 = s.replace("```json", "```").replace("```JSON", "```")
        parts = [p.strip() for p in s2.split("```") if p.strip()]
        # try larger blocks first (more likely to contain the JSON payload)
        for part in sorted(parts, key=len, reverse=True)[:12]:
            got = _parse_any(part)
            if got is not None:
                return got

    return _parse_any(s)

# 全局变量：保存初始状态，供节点访问（用于解决 LangGraph Dict state 类型的状态传递问题）
_initial_state_cache: Dict[str, Dict[str, Any]] = {}

# =========================
# 学科分类（chapter/tags）- WZY版本只处理物理和数学
# =========================
CATEGORY_TAXONOMY: Dict[str, Dict[str, List[str]]] = {
    # 物理
    "physics": {
        "junior": ["力学", "热学", "光学", "电学", "声学", "综合"],
        "senior": ["力学", "热学", "光学", "电学", "近代物理", "综合"],
    },
    # 数学
    "math": {
        "junior": ["代数", "几何", "函数", "统计与概率", "综合"],
        "senior": ["代数", "几何", "函数", "微积分", "概率与统计", "综合"],
    },
}

KNOWLEDGE_POINT_TAXONOMY: Dict[str, Dict[str, List[str]]] = {
    # 物理
    "physics": {
        "junior": [
            "运动学", "牛顿定律", "功和能", "热传递", "光的反射折射", "电路基础", "声音传播", "综合",
        ],
        "senior": [
            "运动学", "牛顿定律", "功和能", "动量", "电场与磁场", "电路分析", "光的干涉衍射", "原子物理", "综合",
        ],
    },
    # 数学
    "math": {
        "junior": [
            "数与式", "方程与不等式", "平面几何", "函数基础", "统计初步", "综合",
        ],
        "senior": [
            "函数与导数", "三角函数", "数列", "立体几何", "解析几何", "概率统计", "微积分", "综合",
        ],
    },
}

def normalize_grade_bucket(grade: Optional[str]) -> str:
    """
    将前端输入的年级/学段归一化为 junior/senior。
    支持：初中/高中/junior/senior/七八九/高一二三 等模糊输入。
    """
    if not grade:
        return "junior"
    g = str(grade).lower()
    if "senior" in g or "高中" in g or "高一" in g or "高二" in g or "高三" in g:
        return "senior"
    if "junior" in g or "初中" in g or "初一" in g or "初二" in g or "初三" in g:
        return "junior"
    return "junior"

def get_category_candidates(subject: str, grade: Optional[str]) -> List[str]:
    """获取学科分类候选 - WZY版本只处理物理和数学"""
    if subject not in ["physics", "math"]:
        return ["综合"]  # 非物理数学学科返回默认值
    
    bucket = normalize_grade_bucket(grade)
    return CATEGORY_TAXONOMY.get(subject, {}).get(bucket, ["综合"])

def get_knowledge_point_candidates(subject: str, grade: Optional[str]) -> List[str]:
    """获取知识点候选 - WZY版本只处理物理和数学"""
    if subject not in ["physics", "math"]:
        return ["综合"]  # 非物理数学学科返回默认值
    
    bucket = normalize_grade_bucket(grade)
    return KNOWLEDGE_POINT_TAXONOMY.get(subject, {}).get(bucket, ["综合"])

def get_text_reasoning_model_names() -> List[str]:
    """
    文本深度推理模型列表（用于：学科判定、分类、错因分析、总结等"纯文本"任务）。
    - 读取 WZY_TEXT_REASONING_MODELS=gemini-3-pro-preview,gpt-5.2,...
    - 为空则回退到 settings.GEMINI_MODEL
    """
    raw = (os.getenv("WZY_TEXT_REASONING_MODELS") or "").strip()
    if raw:
        models = [m.strip() for m in raw.split(",") if m.strip()]
        return models
    return [settings.GEMINI_MODEL or "gemini-2.5-flash"]

def _sanitize_label(label: str, *, max_len: int = 30) -> str:
    s = (label or "").strip()
    if s.lower().startswith("new:"):
        s = s[4:].strip()
    s = s.replace("\n", " ").replace("\r", " ").strip()
    if len(s) > max_len:
        s = s[:max_len].strip()
    return s


def _coerce_results_list(
    parsed: Any,
    *,
    expected_len: int,
) -> Optional[List[Dict[str, Any]]]:
    """
    Coerce various model output shapes into the canonical:
      {"results": [ { "index": int, ... }, ... ]}

    We keep this tolerant because upstream LLM sometimes returns:
    - results as dict keyed by index
    - results as JSON string
    - top-level list (treated as results)
    - alternative keys like items/data/result
    """
    if parsed is None:
        return None

    # Top-level list -> treat as results
    if isinstance(parsed, list):
        out = [x for x in parsed if isinstance(x, dict)]
        if not out:
            return None
        # ensure index
        for i, r in enumerate(out):
            if not isinstance(r.get("index"), int):
                r["index"] = i
        return out

    if not isinstance(parsed, dict):
        return None

    candidates = [
        parsed.get("results"),
        parsed.get("items"),
        parsed.get("data"),
        parsed.get("result"),
    ]

    def _from_any(obj: Any) -> Optional[List[Dict[str, Any]]]:
        if obj is None:
            return None
        if isinstance(obj, list):
            out = [x for x in obj if isinstance(x, dict)]
            if not out:
                return None
            for i, r in enumerate(out):
                if not isinstance(r.get("index"), int):
                    r["index"] = i
            return out
        if isinstance(obj, dict):
            # Nested wrapper like {"results": {...}} or {"items": [...]}
            for k in ("results", "items", "data"):
                inner = obj.get(k)
                got = _from_any(inner)
                if got is not None:
                    return got

            # Dict keyed by index -> list
            out: List[Dict[str, Any]] = []
            for k, v in obj.items():
                if not isinstance(v, dict):
                    continue
                if not isinstance(v.get("index"), int):
                    try:
                        v["index"] = int(k)
                    except Exception:
                        # fallback later
                        pass
                out.append(v)
            if not out:
                return None
            # stable order by index then insertion
            def _key(r: Dict[str, Any]) -> tuple[int, int]:
                idx = r.get("index")
                if not isinstance(idx, int):
                    idx = 10**9
                return (idx, id(r))
            out.sort(key=_key)
            # fill missing indices
            for i, r in enumerate(out):
                if not isinstance(r.get("index"), int):
                    r["index"] = i
            return out
        if isinstance(obj, str):
            s = obj.strip()
            if not s:
                return None
            try:
                j = json.loads(s)
            except Exception:
                return None
            return _from_any(j)
        return None

    def _maybe_shift_one_based_indices(got: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Some models output 1-based indices (1..n) even when we provide 0-based indices.
        If we detect 1-based indexing, shift all indices by -1 so they align with base_items.
        """
        try:
            idxs = [int(r.get("index")) for r in got if isinstance(r.get("index"), int)]
        except Exception:
            return got
        if not idxs:
            return got
        if 0 in idxs:
            return got
        min_idx = min(idxs)
        max_idx = max(idxs)
        # Typical cases:
        # - expected_len == n and model returns 1..n
        # - expected_len == 1 and model returns index=1
        if min_idx == 1 and expected_len > 0 and (max_idx == expected_len or max_idx == len(got)):
            for r in got:
                if isinstance(r.get("index"), int):
                    r["index"] = int(r["index"]) - 1
        return got

    for c in candidates:
        got = _from_any(c)
        if got is not None:
            # Fix common 1-based indexing before clamping
            got = _maybe_shift_one_based_indices(got)
            # best-effort clamp to expected size
            if expected_len > 0:
                got = [r for r in got if isinstance(r.get("index"), int)]
                # keep only indices within range
                got = [r for r in got if 0 <= int(r["index"]) < expected_len]
            return got
    return None

async def get_dynamic_taxonomy_candidates(
    *,
    user_id: int,
    subject: str,
    grade: Optional[str],
    max_chapters: int = 20,
    max_kps: int = 30,
) -> Dict[str, List[str]]:
    """
    从数据库中动态提取"该用户在该学科下已经出现过的分类"，作为 taxonomy 候选。
    只处理物理和数学学科。
    """
    # 非物理数学学科返回空列表
    if subject not in ["physics", "math"]:
        return {"chapters": ["综合"], "knowledge_points": ["综合"]}
    
    from sqlalchemy import select, func
    from backend.core.db.session import async_session_maker
    from backend.core.db.models import Question, SubjectEnum

    # seed（兜底）：仍保留少量"教学大类"
    seed_chapters = get_category_candidates(subject, grade) or ["综合"]
    seed_kps = get_knowledge_point_candidates(subject, grade) or ["综合"]

    try:
        subject_enum = SubjectEnum(subject)
    except Exception:
        subject_enum = SubjectEnum.OTHER

    chapters: List[str] = []
    kps: List[str] = []

    async with async_session_maker() as db:
        # 章节/题目类型：可直接 group by
        stmt_ch = (
            select(Question.chapter, func.count(Question.id))
            .where(
                Question.user_id == int(user_id),
                Question.subject == subject_enum,
                Question.chapter.is_not(None),
                Question.chapter != "",
            )
            .group_by(Question.chapter)
            .order_by(func.count(Question.id).desc())
            .limit(max_chapters)
        )
        rows = (await db.execute(stmt_ch)).all()
        chapters = [str(ch).strip() for ch, _cnt in rows if ch and str(ch).strip()]

        # 知识点：JSON list，SQLite 中不好按元素 group by，直接拉取后 Python 计数（用户数据量通常可控）
        stmt_kp = (
            select(Question.knowledge_points)
            .where(
                Question.user_id == int(user_id),
                Question.subject == subject_enum,
            )
            .limit(800)
        )
        rows2 = (await db.execute(stmt_kp)).all()
        counter: Counter = Counter()
        for (kp_list,) in rows2:
            if isinstance(kp_list, list):
                for kp in kp_list:
                    s = str(kp).strip()
                    if s:
                        counter[s] += 1
        kps = [kp for kp, _cnt in counter.most_common(max_kps)]

    # 合并 seed + 动态候选
    def uniq(seq: List[str]) -> List[str]:
        out: List[str] = []
        seen = set()
        for x in seq:
            x = str(x).strip()
            if not x:
                continue
            if x not in seen:
                out.append(x)
                seen.add(x)
        return out

    return {
        "chapters": uniq(chapters + seed_chapters + ["综合"]),
        "knowledge_points": uniq(kps + seed_kps + ["综合"]),
    }

async def deep_enrich_ocr_items(
    *,
    user_selected_subject: str,
    grade: str,
    taxonomy: Dict[str, Dict[str, List[str]]],
    items: List[Dict[str, Any]],
    trace_id: Optional[str] = None,
    trace_stage: str = "deep_enrich",
    log_ctx: str = "",
) -> List[Dict[str, Any]]:
    """
    图片模式的"深度解析"：在 OCR(浅层) 输出基础上，用强文本模型做二次推理，补全/强化。
    只处理物理和数学学科。
    """
    # 非物理数学学科直接返回原数据
    if user_selected_subject not in ["physics", "math"]:
        return items
    
    if not items:
        return items

    max_items = int(os.getenv("WZY_DEEP_ENRICH_MAX_ITEMS") or "10")
    max_new_chapters = int(os.getenv("WZY_MAX_NEW_CHAPTERS_PER_REQUEST") or "2")
    max_new_kps = int(os.getenv("WZY_MAX_NEW_KPS_PER_REQUEST") or "6")

    prompt_items = [
        {
            "index": i,
            "question_content": (it.get("question_content") or "")[:1200],
            "student_answer": (it.get("student_answer") or "")[:400],
            "correct_answer": (it.get("correct_answer") or "")[:400],
            "ocr_knowledge_points": it.get("knowledge_points", []),
            "ocr_chapter": it.get("chapter") or "",
        }
        for i, it in enumerate(items[:max_items])
    ]

    prompt = f"""你是资深物理/数学教研员与讲题老师。现在给你 OCR(浅层) 提取出的多道错题，请你做"深度解析 + 分类归一化"。

用户选择学科：{user_selected_subject}
年级/学段：{grade or "未知"}

请输出：
1) detected_subject（必须是 ["physics","math"] 之一）与 confidence(0~1)
2) 对每道题输出 results：
   - question_content：更清晰、更完整的题干（尽量保留关键条件）
   - student_answer / correct_answer：若能从上下文推断则补全，否则保留原样
   - explanation：简要解题思路（可为空）
   - error_analysis：错因分析（要具体）
   - suggested_questions：3~5 个"同类型训练点"或"举一反三方向"（短句）
   - chapter：优先从候选 chapters 选择；如确实需要新增，用 "NEW:xxx"（新增总数不超过 {max_new_chapters}）
   - knowledge_points：优先从候选 knowledge_points 选择 1~3 个；如确实需要新增，用 "NEW:xxx"（新增总数不超过 {max_new_kps}）
   - tags：2~6 个短标签

候选分类（优先从候选中选择；语义接近必须选候选，避免发散）：
{json.dumps(taxonomy, ensure_ascii=False)}

题目列表：
{json.dumps(prompt_items, ensure_ascii=False)}

严格输出 JSON：
{{
  "detected_subject": "physics|math",
  "confidence": 0.0,
  "results": [
    {{
      "index": 0,
      "question_content": "...",
      "student_answer": "...",
      "correct_answer": "...",
      "explanation": "...",
      "error_analysis": "...",
      "suggested_questions": ["...", "..."],
      "chapter": "...",
      "knowledge_points": ["..."],
      "tags": ["..."]
    }}
  ]
}}"""

    parsed = await call_router_llm_json(
        prompt,
        log_ctx=log_ctx,
        trace_id=trace_id,
        trace_stage=trace_stage,
    )
    results = (parsed or {}).get("results")
    if not isinstance(results, list):
        return items

    # 门控：整个请求中 NEW 的数量受限
    new_chapters: List[str] = []
    new_kps: List[str] = []

    for r in results:
        if not isinstance(r, dict):
            continue
        idx = r.get("index")
        if not isinstance(idx, int) or idx < 0 or idx >= len(items):
            continue

        # 题干/分析增强
        for key in ["question_content", "student_answer", "correct_answer", "explanation", "error_analysis"]:
            if isinstance(r.get(key), str) and r.get(key).strip():
                items[idx][key] = r.get(key).strip()
        if isinstance(r.get("suggested_questions"), list):
            items[idx]["suggested_questions"] = [str(x).strip() for x in r["suggested_questions"] if str(x).strip()][:5]
        if isinstance(r.get("tags"), list):
            items[idx]["tags"] = [str(x).strip() for x in r["tags"] if str(x).strip()][:6]

        # 分类归一化（候选优先 + NEW 门控）
        allowed_chapters = set(taxonomy.get(user_selected_subject, {}).get("chapters", []) or [])
        allowed_kps = set(taxonomy.get(user_selected_subject, {}).get("knowledge_points", []) or [])

        ch_raw = str(r.get("chapter") or "").strip()
        if ch_raw in allowed_chapters:
            items[idx]["chapter"] = ch_raw
        elif ch_raw.lower().startswith("new:"):
            new_label = _sanitize_label(ch_raw)
            if new_label and len(new_chapters) < max_new_chapters:
                items[idx]["chapter"] = new_label
                if new_label not in new_chapters:
                    new_chapters.append(new_label)

        kp_raw_list = r.get("knowledge_points") or []
        norm_kps: List[str] = []
        if isinstance(kp_raw_list, list):
            for kp in kp_raw_list:
                s = str(kp).strip()
                if not s:
                    continue
                if s in allowed_kps and s not in norm_kps:
                    norm_kps.append(s)
                elif s.lower().startswith("new:"):
                    new_label = _sanitize_label(s)
                    if new_label and len(new_kps) < max_new_kps and new_label not in norm_kps:
                        norm_kps.append(new_label)
                        if new_label not in new_kps:
                            new_kps.append(new_label)
                if len(norm_kps) >= 3:
                    break
        if norm_kps:
            items[idx]["knowledge_points"] = norm_kps

    return items

async def call_router_llm(
    prompt: str,
    *,
    model: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    log_ctx: str = "",
    trace_id: Optional[str] = None,
    trace_stage: str = "llm",
) -> str:
    """
    通过 settings.LLM_API_ENDPOINT 调用 OpenAI-compatible /chat/completions。
    该端点在本项目中用于 Gemini 模型调用。
    """
    import httpx
    import asyncio
    import random
    from backend.core.services.llm_utils import get_llm_semaphore, parse_retry_after_seconds, compute_backoff_delay_seconds
    from backend.core.services.llm_trace import write_llm_trace

    if not settings.LLM_API_ENDPOINT:
        raise RuntimeError("LLM_API_ENDPOINT not configured")

    endpoint = settings.LLM_API_ENDPOINT.rstrip("/")
    models_to_try = [model] if (model and model.strip()) else get_text_reasoning_model_names()
    headers = {}
    if getattr(settings, "LLM_API_KEY", None):
        headers["authorization"] = f"Bearer {settings.LLM_API_KEY}"

    timeout_s = float(os.getenv("WZY_TEXT_REASONING_TIMEOUT_SECONDS") or os.getenv("LLM_TEXT_TIMEOUT_SECONDS") or "90")
    async with httpx.AsyncClient(base_url=endpoint, timeout=timeout_s) as client:
        last_err: Optional[Exception] = None
        for m in models_to_try:
            # 对单个模型做短重试（应对 503/5xx/短暂网络抖动）
            max_attempts = int(os.getenv("LLM_RETRY_MAX_ATTEMPTS") or "3")
            base_delay = float(os.getenv("LLM_RETRY_BASE_DELAY_SECONDS") or "0.6")
            max_delay = float(os.getenv("LLM_RETRY_MAX_DELAY_SECONDS") or "30")
            for attempt in range(max_attempts):
                try:
                    req = {
                        "model": m,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    }
                    if trace_id:
                        # Save FULL prompt + request (WZY-only). Print gated by env.
                        write_llm_trace(
                            trace_id=str(trace_id),
                            stage=str(trace_stage or "llm"),
                            kind=f"request_attempt_{attempt+1}",
                            payload={
                                "endpoint": f"{endpoint}/chat/completions",
                                "request": req,
                            },
                            suffix="json",
                            also_log_full=None,
                            log_prefix=f"{log_ctx} ",
                        )
                    async with get_llm_semaphore():
                        resp = await client.post("/chat/completions", json=req, headers=headers)
                    if trace_id:
                        try:
                            resp_text = resp.text
                        except Exception:
                            resp_text = None
                        write_llm_trace(
                            trace_id=str(trace_id),
                            stage=str(trace_stage or "llm"),
                            kind=f"response_attempt_{attempt+1}_http_{resp.status_code}",
                            payload={
                                "status_code": resp.status_code,
                                "headers": dict(resp.headers),
                                "text": resp_text,
                            },
                            suffix="json",
                            also_log_full=None,
                            log_prefix=f"{log_ctx} ",
                        )
                    # Retryable status handling
                    if resp.status_code in (429, 500, 502, 503, 504) and attempt < max_attempts - 1:
                        retry_after_s = parse_retry_after_seconds(resp.headers.get("retry-after"))
                        delay = compute_backoff_delay_seconds(
                            attempt=attempt,
                            base_delay=base_delay,
                            max_delay=max_delay,
                            retry_after_s=retry_after_s,
                            jitter=0.2,
                        )
                        logger.warning(
                            f"[call_router_llm] {log_ctx} Retryable HTTP {resp.status_code} from LLM endpoint; "
                            f"model={m}, attempt={attempt+1}/{max_attempts}, "
                            f"retry_after={retry_after_s if retry_after_s is not None else 'n/a'}s, sleep={delay:.2f}s"
                        )
                        await asyncio.sleep(delay)
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    if trace_id:
                        write_llm_trace(
                            trace_id=str(trace_id),
                            stage=str(trace_stage or "llm"),
                            kind="response_json",
                            payload=data,
                            suffix="json",
                            also_log_full=None,
                            log_prefix=f"{log_ctx} ",
                        )
                    return data["choices"][0]["message"]["content"]
                except httpx.HTTPStatusError as e:
                    last_err = e
                    # Non-retryable or exhausted attempts -> try next model
                    break
                except (httpx.TimeoutException, httpx.NetworkError, httpx.TransportError) as e:
                    last_err = e
                    if trace_id:
                        write_llm_trace(
                            trace_id=str(trace_id),
                            stage=str(trace_stage or "llm"),
                            kind=f"exception_attempt_{attempt+1}",
                            payload={"type": type(e).__name__, "message": str(e)},
                            suffix="json",
                            also_log_full=None,
                            log_prefix=f"{log_ctx} ",
                        )
                    if attempt < max_attempts - 1:
                        delay = compute_backoff_delay_seconds(
                            attempt=attempt,
                            base_delay=base_delay,
                            max_delay=max_delay,
                            retry_after_s=None,
                            jitter=0.2,
                        )
                        logger.warning(
                            f"[call_router_llm] {log_ctx} Network error; model={m}, attempt={attempt+1}/{max_attempts}, "
                            f"sleep={delay:.2f}s, err={type(e).__name__}"
                        )
                        await asyncio.sleep(delay)
                        continue
                    break
                except Exception as e:
                    last_err = e
                    break
        # 给前端/任务状态更友好的错误（避免把上游 URL/堆栈直接暴露给学生/用户）
        if last_err is not None:
            try:
                import httpx as _httpx
                if isinstance(last_err, _httpx.HTTPStatusError):
                    code = last_err.response.status_code
                    if code in (429, 500, 502, 503, 504):
                        raise RuntimeError(f"模型服务暂时不可用（HTTP {code}），请稍后重试")
            except Exception:
                pass
        raise last_err or RuntimeError("LLM call failed")

async def call_router_llm_with_meta(
    prompt: str,
    *,
    model: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    log_ctx: str = "",
    trace_id: Optional[str] = None,
    trace_stage: str = "llm",
) -> Tuple[str, str]:
    """
    Same as call_router_llm, but returns (content, used_model) for observability.
    """
    import httpx
    import asyncio
    import random
    from backend.core.services.llm_utils import get_llm_semaphore, parse_retry_after_seconds, compute_backoff_delay_seconds
    from backend.core.services.llm_trace import write_llm_trace

    if not settings.LLM_API_ENDPOINT:
        raise RuntimeError("LLM_API_ENDPOINT not configured")

    endpoint = settings.LLM_API_ENDPOINT.rstrip("/")
    models_to_try = [model] if (model and model.strip()) else get_text_reasoning_model_names()
    headers = {}
    if getattr(settings, "LLM_API_KEY", None):
        headers["authorization"] = f"Bearer {settings.LLM_API_KEY}"

    timeout_s = float(os.getenv("WZY_TEXT_REASONING_TIMEOUT_SECONDS") or os.getenv("LLM_TEXT_TIMEOUT_SECONDS") or "90")
    async with httpx.AsyncClient(base_url=endpoint, timeout=timeout_s) as client:
        last_err: Optional[Exception] = None
        for m in models_to_try:
            max_attempts = int(os.getenv("LLM_RETRY_MAX_ATTEMPTS") or "3")
            base_delay = float(os.getenv("LLM_RETRY_BASE_DELAY_SECONDS") or "0.6")
            max_delay = float(os.getenv("LLM_RETRY_MAX_DELAY_SECONDS") or "30")
            for attempt in range(max_attempts):
                try:
                    req = {
                        "model": m,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    }
                    if trace_id:
                        write_llm_trace(
                            trace_id=str(trace_id),
                            stage=str(trace_stage or "llm"),
                            kind=f"request_attempt_{attempt+1}",
                            payload={
                                "endpoint": f"{endpoint}/chat/completions",
                                "request": req,
                            },
                            suffix="json",
                            also_log_full=None,
                            log_prefix=f"{log_ctx} ",
                        )
                    async with get_llm_semaphore():
                        resp = await client.post("/chat/completions", json=req, headers=headers)
                    if trace_id:
                        try:
                            resp_text = resp.text
                        except Exception:
                            resp_text = None
                        write_llm_trace(
                            trace_id=str(trace_id),
                            stage=str(trace_stage or "llm"),
                            kind=f"response_attempt_{attempt+1}_http_{resp.status_code}",
                            payload={
                                "status_code": resp.status_code,
                                "headers": dict(resp.headers),
                                "text": resp_text,
                            },
                            suffix="json",
                            also_log_full=None,
                            log_prefix=f"{log_ctx} ",
                        )
                    if resp.status_code in (429, 500, 502, 503, 504) and attempt < max_attempts - 1:
                        retry_after_s = parse_retry_after_seconds(resp.headers.get("retry-after"))
                        delay = compute_backoff_delay_seconds(
                            attempt=attempt,
                            base_delay=base_delay,
                            max_delay=max_delay,
                            retry_after_s=retry_after_s,
                            jitter=0.2,
                        )
                        logger.warning(
                            f"[call_router_llm] {log_ctx} Retryable HTTP {resp.status_code} from LLM endpoint; "
                            f"model={m}, attempt={attempt+1}/{max_attempts}, "
                            f"retry_after={retry_after_s if retry_after_s is not None else 'n/a'}s, sleep={delay:.2f}s"
                        )
                        await asyncio.sleep(delay)
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    if trace_id:
                        write_llm_trace(
                            trace_id=str(trace_id),
                            stage=str(trace_stage or "llm"),
                            kind="response_json",
                            payload=data,
                            suffix="json",
                            also_log_full=None,
                            log_prefix=f"{log_ctx} ",
                        )
                    return data["choices"][0]["message"]["content"], m
                except httpx.HTTPStatusError as e:
                    last_err = e
                    break
                except (httpx.TimeoutException, httpx.NetworkError, httpx.TransportError) as e:
                    last_err = e
                    if trace_id:
                        write_llm_trace(
                            trace_id=str(trace_id),
                            stage=str(trace_stage or "llm"),
                            kind=f"exception_attempt_{attempt+1}",
                            payload={"type": type(e).__name__, "message": str(e)},
                            suffix="json",
                            also_log_full=None,
                            log_prefix=f"{log_ctx} ",
                        )
                    if attempt < max_attempts - 1:
                        delay = compute_backoff_delay_seconds(
                            attempt=attempt,
                            base_delay=base_delay,
                            max_delay=max_delay,
                            retry_after_s=None,
                            jitter=0.2,
                        )
                        logger.warning(
                            f"[call_router_llm] {log_ctx} Network error; model={m}, attempt={attempt+1}/{max_attempts}, "
                            f"sleep={delay:.2f}s, err={type(e).__name__}"
                        )
                        await asyncio.sleep(delay)
                        continue
                    break
                except Exception as e:
                    last_err = e
                    break
        if last_err is not None:
            try:
                import httpx as _httpx
                if isinstance(last_err, _httpx.HTTPStatusError):
                    code = last_err.response.status_code
                    if code in (429, 500, 502, 503, 504):
                        raise RuntimeError(f"模型服务暂时不可用（HTTP {code}），请稍后重试")
            except Exception:
                pass
        raise last_err or RuntimeError("LLM call failed")

async def call_router_llm_json(
    prompt: str,
    *,
    model: Optional[str] = None,
    log_ctx: str = "",
    trace_id: Optional[str] = None,
    trace_stage: str = "llm_json",
) -> Optional[Dict[str, Any]]:
    """
    调用 LLM 并尝试解析 JSON（允许返回内容包含围栏/额外文本）。
    """
    import re

    raw = await call_router_llm(
        prompt,
        model=model,
        temperature=0.2,
        max_tokens=4096,
        log_ctx=log_ctx,
        trace_id=trace_id,
        trace_stage=trace_stage,
    )
    # Prefer robust extractor; fallback to simple regex for compatibility
    parsed = _extract_json_object_loose(raw or "")
    if parsed is not None:
        return parsed
    m = re.search(r"\{[\s\S]*\}", raw or "")
    if m:
        try:
            obj = json.loads(m.group())
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None
    return None

class QuestionIntakeOCRAgent(BaseAgent):
    """
    错题录入OCR Agent (WZY版本)
    专门用于"录入错题"功能，只支持物理和数学学科
    """

    def __init__(self):
        # WZY版本只支持物理和数学学科
        super().__init__(subjects=["physics", "math"])
        self._graph = None

    def get_graph(self, initial_state: Optional[Dict[str, Any]] = None):
        """获取图实例，支持传入初始状态以解决状态传递问题"""
        # 每次处理时都创建新的图，这样可以传入初始状态
        return create_intake_ocr_graph(initial_state)

    async def process(
        self,
        input_type: str,  # 'image' or 'text'
        user_id: int,
        task_id: str,
        subject: str,
        difficulty: str = "medium",
        grade: str = "",
        source_image_id: Optional[int] = None,
        # 图片模式参数
        image_file: Optional[Any] = None,
        image_path: Optional[str] = None,
        # 文字模式参数
        text_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        处理错题录入（录入错题功能专用）- WZY版本只处理物理和数学

        Args:
            input_type: 输入类型 ('image' 或 'text')
            user_id: 用户ID
            task_id: 任务ID
            subject: 学科（只支持 'physics' 或 'math'）
            difficulty: 难度
            image_file: 图片文件对象（图片模式）
            image_path: 图片路径（图片模式）
            text_data: 文字JSON数据（文字模式）

        Returns:
            处理结果，包含question_id等
        """
        # Validate subject - WZY版本只支持物理和数学
        if subject not in ["physics", "math"]:
            logger.error(f"Subject '{subject}' not supported by WZY module. Only 'physics' and 'math' are supported.")
            return {
                "task_id": task_id,
                "question_id": None,
                "success": False,
                "errors": [f"Subject '{subject}' not supported by WZY module. Only 'physics' and 'math' are supported."],
            }

        # 构建初始状态字典
        state_dict = {
            "raw_input": "",
            "user_id": user_id,
            "task_id": task_id,
            "image_urls": [],
            "errors": [],
            "parse_attempts": 0,
            "parse_success": False,
            "subject": subject,
            "difficulty": difficulty,
            "grade": grade,
            "input_type": input_type,  # 自定义字段用于路由
            "source_image_id": source_image_id,
        }

        # 根据输入类型处理
        if input_type == "image":
            if not image_path and not image_file:
                return {
                    "task_id": task_id,
                    "question_id": None,
                    "success": False,
                    "errors": ["图片模式需要提供图片文件或路径"],
                }
            state_dict["image_path"] = image_path
            state_dict["image_file"] = image_file
        elif input_type == "text":
            if not text_data:
                return {
                    "task_id": task_id,
                    "question_id": None,
                    "success": False,
                    "errors": ["文字模式需要提供text_data"],
                }
            # 保存原始输入（JSON格式）
            state_dict["original_input"] = json.dumps(text_data, ensure_ascii=False)
            state_dict["text_data"] = text_data
        else:
            return {
                "task_id": task_id,
                "question_id": None,
                "success": False,
                "errors": [f"不支持的输入类型: {input_type}，支持: 'image' 或 'text'"],
            }

        # 执行处理流程
        try:
            # 保存初始状态到全局缓存，供节点访问
            _initial_state_cache[task_id] = state_dict.copy()
            
            # 创建图实例，传入初始状态
            graph = self.get_graph(initial_state=state_dict)
            
            # 使用 astream 并手动合并状态，确保 user_id 等字段不会丢失
            final_state = None
            async for state in graph.astream(state_dict):
                for node_name, node_output in state.items():
                    if isinstance(node_output, dict):
                        # 合并策略：初始状态 + 累积状态 + 节点输出
                        final_state = {**state_dict, **(final_state or {}), **node_output}
            
            # 如果 final_state 仍然为 None，使用初始状态
            if final_state is None:
                final_state = state_dict.copy()
            
            # 最后确保关键字段存在（双重保险）
            if final_state.get("user_id") is None and state_dict.get("user_id") is not None:
                final_state["user_id"] = state_dict.get("user_id")
            if final_state.get("task_id") is None and state_dict.get("task_id") is not None:
                final_state["task_id"] = state_dict.get("task_id")
            if final_state.get("subject") is None and state_dict.get("subject") is not None:
                final_state["subject"] = state_dict.get("subject")
            if final_state.get("difficulty") is None and state_dict.get("difficulty") is not None:
                final_state["difficulty"] = state_dict.get("difficulty")
            if final_state.get("input_type") is None and state_dict.get("input_type") is not None:
                final_state["input_type"] = state_dict.get("input_type")
            
            # 清理缓存
            try:
                _initial_state_cache.pop(task_id, None)
            except Exception:
                pass
            
            # 从最终状态构建返回结果
            return {
                "task_id": final_state.get("task_id", task_id),
                "question_id": final_state.get("question_id"),
                "success": final_state.get("parse_success", False) or final_state.get("success", False),
                "errors": final_state.get("errors", []),
                "progress": final_state.get("progress", 100.0),
            }
        except Exception as e:
            logger.error(f"QuestionIntakeOCRAgent process failed: {e}", exc_info=True)
            # 清理缓存
            try:
                _initial_state_cache.pop(task_id, None)
            except Exception:
                pass
            return {
                "task_id": task_id,
                "question_id": None,
                "success": False,
                "errors": [f"处理失败: {str(e)}"],
            }

def create_intake_ocr_graph(initial_state: Optional[Dict[str, Any]] = None):
    """创建录入错题OCR处理图"""
    # 使用 Dict[str, Any] 作为状态类型，更灵活
    from typing import Dict, Any
    
    # 如果提供了初始状态，使用闭包让节点能访问到初始状态
    if initial_state:
        # 创建包装函数，确保节点能访问到初始状态
        def wrap_node(node_func):
            async def wrapped_node(state: Dict[str, Any]) -> Dict[str, Any]:
                # 合并初始状态和当前状态，确保关键字段不丢失
                merged_state = {**initial_state, **state}
                result = await node_func(merged_state)
                # 重要：对 Dict 状态，确保"累计状态"不会被丢失
                if isinstance(result, dict):
                    return {**merged_state, **result}
                return merged_state
            return wrapped_node
        
        process_input_wrapped = wrap_node(process_input)
        ocr_agent_wrapped = wrap_node(ocr_agent)
        reasoner_agent_wrapped = wrap_node(reasoner_agent)
        normalizer_agent_wrapped = wrap_node(normalizer_agent)
        save_question_wrapped = wrap_node(save_question)
    else:
        # 如果没有提供初始状态，使用原始函数
        process_input_wrapped = process_input
        ocr_agent_wrapped = ocr_agent
        reasoner_agent_wrapped = reasoner_agent
        normalizer_agent_wrapped = normalizer_agent
        save_question_wrapped = save_question
    
    graph = StateGraph(Dict[str, Any])

    # 添加节点
    graph.add_node("process_input", process_input_wrapped)
    graph.add_node("ocr_agent", ocr_agent_wrapped)
    graph.add_node("reasoner_agent", reasoner_agent_wrapped)
    graph.add_node("normalizer_agent", normalizer_agent_wrapped)
    graph.add_node("save_question", save_question_wrapped)

    # 设置入口
    graph.set_entry_point("process_input")

    # 添加边
    graph.add_conditional_edges(
        "process_input",
        route_by_input_type,
        {
            "image": "ocr_agent",
            "text": "reasoner_agent",
        }
    )

    graph.add_edge("ocr_agent", "reasoner_agent")
    def route_after_reasoner(state: Dict[str, Any]) -> str:
        # fatal_error -> stop early (usually subject mismatch)
        if state.get("fatal_error") is True:
            return "end"
        return "continue"

    graph.add_conditional_edges(
        "reasoner_agent",
        route_after_reasoner,
        {
            "continue": "normalizer_agent",
            "end": END,
        },
    )
    graph.add_edge("normalizer_agent", "save_question")
    graph.add_edge("save_question", END)

    return graph.compile()

def route_by_input_type(state: Dict[str, Any]) -> str:
    """根据输入类型路由"""
    input_type = state.get("input_type", "image")
    return input_type

async def process_input(state: Dict[str, Any]) -> Dict[str, Any]:
    """处理输入节点"""
    logger.info(f"[process_input] Task {state.get('task_id')}: Processing input")
    # 从全局缓存获取初始状态，确保关键字段不丢失
    task_id = state.get("task_id")
    if task_id and task_id in _initial_state_cache:
        initial_state = _initial_state_cache[task_id]
        # 合并初始状态和当前状态
        merged_state = {**initial_state, **state}
        return {
            **merged_state,  # 保留所有初始字段
            "current_step": "process_input",
            "progress": 10.0,
        }
    # 如果没有缓存，只返回新增字段
    return {
        "current_step": "process_input",
        "progress": 10.0,
    }

async def ocr_agent(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    OCR Agent（多模态快）：
    - 只负责"图片 -> OCR浅层结构化提取"
    - 不做深度推理、错因分析、taxonomy 归一化（这些交给后续 Reasoner/Normalizer）
    """
    task_id = state.get("task_id")
    if task_id and task_id in _initial_state_cache:
        state = {**_initial_state_cache[task_id], **state}

    t0 = time.perf_counter()
    image_path = state.get("image_path")
    logger.info(
        f"[ocr_agent] {_ctx(state)} start vision_model={os.getenv('WZY_OCR_VISION_MODEL') or os.getenv('OCR_VISION_MODEL') or settings.GEMINI_MODEL} "
        f"image={os.path.basename(image_path) if image_path else None}"
    )

    image_path = state.get("image_path")
    subject = state.get("subject", "physics")  # 默认物理
    grade = state.get("grade", "")

    if not image_path:
        return {"errors": ["没有提供图片路径"], "current_step": "ocr_agent", "progress": 10.0}

    try:
        from backend.core.services.gemini_ocr_service import get_gemini_ocr_service, SubjectType

        ocr_service = get_gemini_ocr_service(settings)
        await ocr_service.initialize()

        subject_map = {
            "physics": SubjectType.PHYSICS,
            "math": SubjectType.MATH,
            "history": SubjectType.HISTORY,
            "geography": SubjectType.GEOGRAPHY,
            "chemistry": SubjectType.CHEMISTRY,
            "biology": SubjectType.BIOLOGY,
            "english": SubjectType.ENGLISH,
            "chinese": SubjectType.CHINESE,
            "other": SubjectType.OTHER,
        }
        subject_type = subject_map.get(str(subject).lower(), SubjectType.OTHER)

        analysis_result = await ocr_service.analyze_exam_image(
            image_path=image_path,
            subject=subject_type,
            grade=str(grade or ""),
            user_hint=(
                "这是错题识别场景：一张图片可能包含多道错题。"
                "请识别图片中的所有题目（尽量逐题拆分），并提取每道题的题干、学生答案、正确答案、知识点。"
                "非常重要：请按试卷中题目出现的顺序（从上到下、从左到右）组织 questions 数组，并为每题给出 question_number（如无明确题号，也请按出现顺序从 1 开始编号）。"
            ),
            trace_id=str(task_id) if task_id else None,
            trace_stage="ocr_agent",
        )

        extracted_items: List[Dict[str, Any]] = []
        if getattr(analysis_result, "questions", None):
            def _qnum(x):
                v = getattr(x, "question_number", None)
                try:
                    iv = int(v)
                    return iv if iv > 0 else None
                except Exception:
                    return None

            pairs = []
            for i, qi in enumerate(list(analysis_result.questions or [])):
                q_text = (getattr(qi, "question_text", "") or "").strip()
                if not q_text:
                    continue
                qn = _qnum(qi)
                # 排序 key：优先用题号；若无题号则用模型输出顺序(i+1)，避免把"无题号题目"统一挪到末尾导致顺序错乱
                order_key = qn if qn is not None else (i + 1)
                pairs.append(
                    (
                        order_key,
                        i,
                        {
                            "question_content": q_text,
                            "student_answer": (getattr(qi, "student_answer", "") or "").strip(),
                            "correct_answer": (getattr(qi, "correct_answer", "") or "").strip(),
                            "question_type": (getattr(qi, "question_type", "") or "").strip(),
                            "knowledge_points": getattr(qi, "knowledge_points", []) or [],
                            # 浅层 OCR 阶段不保证错因分析，留空给 Reasoner
                            "error_analysis": (getattr(qi, "error_analysis", "") or "").strip(),
                            "question_number": qn,
                        },
                    )
                )

            # 生成稳定的试卷顺序字段 order（1..n），用于后续入库写入 upload_index
            for j, (_ord, _i, d) in enumerate(sorted(pairs, key=lambda x: (x[0], x[1]))):
                d["order"] = j + 1
                extracted_items.append(d)

        if not extracted_items:
            extracted_items = [
                {
                    "question_content": (getattr(analysis_result, "overall_analysis", "") or "未能识别题目内容").strip()
                    or "未能识别题目内容，请手动输入",
                    "student_answer": "",
                    "correct_answer": "",
                    "question_type": "",
                    "knowledge_points": getattr(analysis_result, "weak_points", []) or [],
                    "error_analysis": "",
                }
            ]

        # 更新任务状态（供 SSE 推送阶段性进度）
        if task_id:
            from backend.core.db.session import async_session_maker
            from backend.core.crud import crud_task
            from backend.core.db.models import TaskStatusEnum
            async with async_session_maker() as db:
                # 写入 OCR 阶段产物（增量 patch）
                compact_items = [
                    {
                        "index": i,
                        "question_content": (it.get("question_content") or "")[:400],
                        "student_answer": (it.get("student_answer") or "")[:200],
                        "correct_answer": (it.get("correct_answer") or "")[:200],
                        "question_type": (it.get("question_type") or "")[:50],
                        "knowledge_points": (it.get("knowledge_points") or [])[:5],
                    }
                    for i, it in enumerate(extracted_items[: int(os.getenv("WZY_DEEP_ENRICH_MAX_ITEMS") or "10")])
                ]
                await crud_task.update_task_status(
                    db,
                    task_id,
                    TaskStatusEnum.PROCESSING,
                    progress=25.0,
                    current_step="OCR识别完成，正在进行深度解析...",
                    result_patch={
                        "ocr_model": os.getenv("WZY_OCR_VISION_MODEL") or os.getenv("OCR_VISION_MODEL"),
                        "items": compact_items,
                        "original_input_preview": (getattr(analysis_result, "raw_response", "") or "")[:1500],
                    },
                    result_stage="ocr",
                )
                await db.commit()

        duration_ms = int((time.perf_counter() - t0) * 1000)
        logger.info(
            f"[ocr_agent] {_ctx(state)} done extracted_count={len(extracted_items)} duration_ms={duration_ms}"
        )

        result = {
            "ocr_items": extracted_items,
            "original_input": getattr(analysis_result, "raw_response", "") or "",
            "summarized_input": getattr(analysis_result, "overall_analysis", "") or "",
            "current_step": "ocr_agent",
            "progress": 25.0,
        }
        for k in ["user_id", "task_id", "subject", "difficulty", "input_type", "image_path", "grade"]:
            if state.get(k) is not None:
                result[k] = state.get(k)
        return result

    except Exception as e:
        duration_ms = int((time.perf_counter() - t0) * 1000) if "t0" in locals() else -1
        logger.error(f"[ocr_agent] {_ctx(state)} error duration_ms={duration_ms}: {e}", exc_info=True)
        return {"errors": [f"OCR 处理错误: {str(e)}"], "current_step": "ocr_agent", "progress": 10.0}

async def reasoner_agent(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Reasoner Agent（强推理补全）：
    - 图片：在 OCR items 基础上做深度解析（更完整题干、错因、举一反三、分类提议）
    - 文字：直接基于文字输入做深度解析与分类提议
    """
    task_id = state.get("task_id")
    if task_id and task_id in _initial_state_cache:
        state = {**_initial_state_cache[task_id], **state}

    t0 = time.perf_counter()
    models = get_text_reasoning_model_names()
    items_in = len(state.get("ocr_items") or []) if state.get("input_type", "image") == "image" else 1
    logger.info(
        f"[reasoner_agent] {_ctx(state)} start text_models={models} items_in={items_in}"
    )

    input_type = state.get("input_type", "image")
    subject = state.get("subject", "physics")  # 默认物理
    grade = state.get("grade", "")
    user_id = state.get("user_id")

    # 构建 taxonomy 提示（动态候选 + seed），用于减少发散
    taxonomy: Dict[str, Dict[str, List[str]]] = {}
    try:
        # WZY版本只处理物理和数学
        for s in ["physics", "math"]:
            taxonomy[s] = await get_dynamic_taxonomy_candidates(
                user_id=int(user_id or 0),
                subject=s,
                grade=grade,
                max_chapters=20,
                max_kps=30,
            )
    except Exception:
        taxonomy = {
            s: {"chapters": get_category_candidates(s, grade), "knowledge_points": get_knowledge_point_candidates(s, grade)}
            for s in ["physics", "math"]
        }

    if input_type == "image":
        items = state.get("ocr_items") if isinstance(state.get("ocr_items"), list) else []
        if not items:
            return {"errors": ["缺少 OCR 结果，无法深度解析"], "current_step": "reasoner_agent", "progress": 30.0}
        prompt_items = [
            {
                "index": i,
                "question_content": (it.get("question_content") or "")[:1200],
                "student_answer": (it.get("student_answer") or "")[:400],
                "correct_answer": (it.get("correct_answer") or "")[:400],
                "ocr_knowledge_points": it.get("knowledge_points", []),
            }
            for i, it in enumerate(items[: int(os.getenv("WZY_DEEP_ENRICH_MAX_ITEMS") or "10")])
        ]
        raw_input = state.get("original_input") or ""
    else:
        text_data = state.get("text_data") or {}
        if not isinstance(text_data, dict) or not text_data:
            return {"errors": ["缺少 text_data，无法深度解析"], "current_step": "reasoner_agent", "progress": 30.0}
        prompt_items = [
            {
                "index": 0,
                "question_content": (str(text_data.get("content") or text_data.get("question") or "") or "")[:1200],
                "student_answer": (str(text_data.get("student_answer") or "") or "")[:400],
                "correct_answer": (str(text_data.get("correct_answer") or "") or "")[:400],
                "ocr_knowledge_points": text_data.get("knowledge_points", []) if isinstance(text_data.get("knowledge_points"), list) else [],
            }
        ]
        raw_input = json.dumps(text_data, ensure_ascii=False)

    mismatch_threshold = float(os.getenv("WZY_SUBJECT_MISMATCH_CONFIDENCE") or "0.75")
    max_new_chapters = int(os.getenv("WZY_MAX_NEW_CHAPTERS_PER_REQUEST") or "2")
    max_new_kps = int(os.getenv("WZY_MAX_NEW_KPS_PER_REQUEST") or "6")

    # Control output size to avoid provider truncation (finish_reason=length => invalid JSON => fallback_no_json)
    max_field_question = int(os.getenv("WZY_REASONER_MAX_CHARS_QUESTION_CONTENT") or "600")
    max_field_expl = int(os.getenv("WZY_REASONER_MAX_CHARS_EXPLANATION") or "300")
    max_field_error = int(os.getenv("WZY_REASONER_MAX_CHARS_ERROR_ANALYSIS") or "420")
    max_field_sq = int(os.getenv("WZY_REASONER_MAX_CHARS_SUGGESTED_Q") or "60")

    prompt = f"""你是资深物理/数学教研员与讲题老师。现在要做"深度解析 + 分类提议（允许受控新增）"。

用户选择学科：{subject}
年级/学段：{grade or "未知"}

请输出：
1) detected_subject（必须是 ["physics","math"] 之一）与 confidence(0~1)
2) results：对每道题输出：
   - question_content：更清晰、更完整的题干
   - student_answer / correct_answer：可推断则补全，否则保留原样
   - explanation：简要解题思路（可为空，务必简洁）
   - error_analysis：错因分析（要具体，但务必简洁）
   - suggested_questions：3 个同类型训练点（短句）
   - chapter：优先选候选；若确实需要新增，用 "NEW:xxx"（新增总数≤{max_new_chapters}）
   - knowledge_points：优先选候选 1~3 个；新增用 "NEW:xxx"（新增总数≤{max_new_kps}）
   - tags：2~6 个短标签

输出长度硬约束（为保证 JSON 不被截断）：
- question_content <= {max_field_question} 字
- explanation <= {max_field_expl} 字
- error_analysis <= {max_field_error} 字
- suggested_questions 每条 <= {max_field_sq} 字
- 如果超长，优先压缩 explanation/error_analysis/suggested_questions，不要输出冗长段落

候选分类（优先从候选中选择；语义接近必须选候选，避免发散）：
{json.dumps(taxonomy, ensure_ascii=False)}

OCR/输入原文（供你参考，可忽略噪声）：
{raw_input[:2000]}

题目列表（注意：index 从 0 开始，是 0-based）：
{json.dumps(prompt_items, ensure_ascii=False)}

严格输出 JSON：
{{
  "detected_subject": "physics|math",
  "confidence": 0.0,
  "results": [{{"index":0,"question_content":"...","student_answer":"...","correct_answer":"...","explanation":"...","error_analysis":"...","suggested_questions":["..."],"chapter":"...","knowledge_points":["..."],"tags":["..."]}}]
}}"""

    raw_preview_limit = int(os.getenv("WZY_REASONER_RAW_PREVIEW_CHARS") or "1200")
    raw_text = ""
    used_model = None
    try:
        reasoner_max_tokens = int(os.getenv("WZY_REASONER_MAX_TOKENS") or "8192")
        raw_text, used_model = await call_router_llm_with_meta(
            prompt,
            model=None,
            temperature=0.2,
            max_tokens=reasoner_max_tokens,
            log_ctx=_ctx(state),
            trace_id=str(task_id) if task_id else None,
            trace_stage="reasoner",
        )
    except Exception as e:
        duration_ms = int((time.perf_counter() - t0) * 1000)
        msg = f"深度解析失败：{str(e) or 'LLM 调用失败'}，已降级为 OCR 结果归一化"
        logger.warning(f"[reasoner_agent] {_ctx(state)} fallback_llm_error duration_ms={duration_ms}: {e}")
        if task_id:
            from backend.core.db.session import async_session_maker
            from backend.core.crud import crud_task
            from backend.core.db.models import TaskStatusEnum
            async with async_session_maker() as db:
                await crud_task.update_task_status(
                    db,
                    task_id,
                    TaskStatusEnum.PROCESSING,
                    progress=45.0,
                    current_step=msg,
                    result_patch={"status": "fallback", "error": "llm_error", "message": str(e)[:200]},
                    result_stage="reasoner",
                )
                await db.commit()
        base_items = list(state.get("ocr_items") or [])
        out = {**state, "reasoned_items": base_items, "current_step": "reasoner_agent", "progress": 45.0}
        out.setdefault("errors", [])
        out["errors"] = list(out.get("errors") or []) + [msg]
        return out

    parsed = _extract_json_object_loose(raw_text) if raw_text else None
    if not parsed:
        duration_ms = int((time.perf_counter() - t0) * 1000)
        msg = "深度解析失败：无法解析模型输出，已降级为 OCR 结果归一化"
        logger.warning(f"[reasoner_agent] {_ctx(state)} fallback_no_json duration_ms={duration_ms}")
        if task_id:
            from backend.core.db.session import async_session_maker
            from backend.core.crud import crud_task
            from backend.core.db.models import TaskStatusEnum
            async with async_session_maker() as db:
                await crud_task.update_task_status(
                    db,
                    task_id,
                    TaskStatusEnum.PROCESSING,
                    progress=45.0,
                    current_step=msg,
                    result_patch={
                        "status": "fallback",
                        "error": "no_json",
                        "used_model": used_model,
                        "raw_output_len": len(raw_text or ""),
                        "raw_output_preview": (raw_text or "")[:raw_preview_limit],
                        "raw_output_truncated": bool(raw_text and len(raw_text) > raw_preview_limit),
                    },
                    result_stage="reasoner",
                )
                await db.commit()
        base_items = list(state.get("ocr_items") or [])
        out = {**state, "reasoned_items": base_items, "current_step": "reasoner_agent", "progress": 45.0}
        out.setdefault("errors", [])
        out["errors"] = list(out.get("errors") or []) + [msg]
        return out

    detected = str(parsed.get("detected_subject") or "").strip().lower()
    try:
        conf_f = float(parsed.get("confidence", 0.0))
    except Exception:
        conf_f = 0.0

    if detected in ("physics", "math") and detected != subject and conf_f >= mismatch_threshold:
        msg = f"上传内容与选择学科不匹配：检测为 {detected}（置信度 {conf_f:.2f}），但选择了 {subject}。"
        if task_id:
            from backend.core.db.session import async_session_maker
            from backend.core.crud import crud_task
            from backend.core.db.models import TaskStatusEnum
            async with async_session_maker() as db:
                await crud_task.update_task_status(
                    db,
                    task_id,
                    TaskStatusEnum.FAILED,
                    progress=100.0,
                    current_step=msg[:200],
                    error_message=msg,
                    result_patch={
                        "status": "failed",
                        "error": "subject_mismatch",
                        "detected_subject": detected,
                        "confidence": conf_f,
                        "selected_subject": subject,
                        "used_model": used_model,
                        "raw_output_len": len(raw_text or ""),
                        "raw_output_preview": (raw_text or "")[:raw_preview_limit],
                        "raw_output_truncated": bool(raw_text and len(raw_text) > raw_preview_limit),
                    },
                    result_stage="reasoner",
                )
                await db.commit()
        out = {"errors": [msg], "parse_success": False, "fatal_error": True, "current_step": "reasoner_agent", "progress": 40.0}
        for k in ["user_id", "task_id", "subject", "difficulty", "input_type", "image_path", "grade", "original_input", "summarized_input"]:
            if state.get(k) is not None:
                out[k] = state.get(k)
        return out

    # Prepare base_items for coercion & later overlay
    if input_type == "image":
        base_items = list(state.get("ocr_items") or [])
    else:
        base_items = [
            {
                "question_content": prompt_items[0].get("question_content", ""),
                "student_answer": prompt_items[0].get("student_answer", ""),
                "correct_answer": prompt_items[0].get("correct_answer", ""),
            }
        ]

    results = _coerce_results_list(parsed, expected_len=len(base_items))
    if not isinstance(results, list) or not results:
        duration_ms = int((time.perf_counter() - t0) * 1000)
        msg = "深度解析失败：results 格式错误，已降级为 OCR 结果归一化"
        # Emit error details to logs for observability
        try:
            keys = list(parsed.keys()) if isinstance(parsed, dict) else None
        except Exception:
            keys = None
        logger.error(
            f"[reasoner_agent] {_ctx(state)} fallback_bad_results duration_ms={duration_ms} "
            f"parsed_type={type(parsed).__name__} parsed_keys={keys} "
            f"raw_output_preview={(raw_text or '')[:raw_preview_limit]}"
        )
        if task_id:
            from backend.core.db.session import async_session_maker
            from backend.core.crud import crud_task
            from backend.core.db.models import TaskStatusEnum
            async with async_session_maker() as db:
                await crud_task.update_task_status(
                    db,
                    task_id,
                    TaskStatusEnum.PROCESSING,
                    progress=45.0,
                    current_step=msg,
                    result_patch={
                        "status": "fallback",
                        "error": "bad_results",
                        "used_model": used_model,
                        "parsed_type": type(parsed).__name__,
                        "parsed_keys": keys,
                        "raw_output_len": len(raw_text or ""),
                        "raw_output_preview": (raw_text or "")[:raw_preview_limit],
                        "raw_output_truncated": bool(raw_text and len(raw_text) > raw_preview_limit),
                    },
                    result_stage="reasoner",
                )
                await db.commit()
        out = {**state, "reasoned_items": base_items, "current_step": "reasoner_agent", "progress": 45.0}
        out.setdefault("errors", [])
        out["errors"] = list(out.get("errors") or []) + [msg]
        return out

    for r in results:
        if not isinstance(r, dict):
            continue
        idx = r.get("index")
        if not isinstance(idx, int) or idx < 0 or idx >= len(base_items):
            continue
        for key in ["question_content", "student_answer", "correct_answer", "explanation", "error_analysis", "chapter"]:
            if isinstance(r.get(key), str) and r.get(key).strip():
                base_items[idx][key] = r.get(key).strip()
        # correctness / scoring
        if isinstance(r.get("is_correct"), bool):
            base_items[idx]["is_correct"] = r.get("is_correct")
        if isinstance(r.get("score"), (int, float)):
            base_items[idx]["score"] = float(r.get("score"))
        if isinstance(r.get("max_score"), (int, float)):
            base_items[idx]["max_score"] = float(r.get("max_score"))
        if isinstance(r.get("knowledge_points"), list):
            base_items[idx]["knowledge_points"] = [str(x).strip() for x in r["knowledge_points"] if str(x).strip()]
        if isinstance(r.get("suggested_questions"), list):
            base_items[idx]["suggested_questions"] = [str(x).strip() for x in r["suggested_questions"] if str(x).strip()]
        if isinstance(r.get("tags"), list):
            base_items[idx]["tags"] = [str(x).strip() for x in r["tags"] if str(x).strip()]

    duration_ms = int((time.perf_counter() - t0) * 1000)
    logger.info(
        f"[reasoner_agent] {_ctx(state)} done detected_subject={detected or None} confidence={conf_f:.2f} items_out={len(base_items)} duration_ms={duration_ms}"
    )

    if task_id:
        from backend.core.db.session import async_session_maker
        from backend.core.crud import crud_task
        from backend.core.db.models import TaskStatusEnum
        async with async_session_maker() as db:
            await crud_task.update_task_status(
                db,
                task_id,
                TaskStatusEnum.PROCESSING,
                progress=55.0,
                current_step="深度解析完成，正在归一化分类...",
                result_patch={
                    "text_models": get_text_reasoning_model_names(),
                    "used_model": used_model,
                    "detected_subject": detected,
                    "confidence": conf_f,
                    "items": [
                        {
                            "index": i,
                            "question_content": (it.get("question_content") or it.get("question_text") or "")[:500],
                            "chapter": (it.get("chapter") or "")[:50],
                            "knowledge_points": (it.get("knowledge_points") or [])[:5],
                            "error_analysis": (it.get("error_analysis") or "")[:600],
                            "suggested_questions": (it.get("suggested_questions") or [])[:5],
                        }
                        for i, it in enumerate(base_items[: int(os.getenv("WZY_DEEP_ENRICH_MAX_ITEMS") or "10")])
                    ],
                },
                result_stage="reasoner",
            )
            await db.commit()

    out = {"reasoned_items": base_items, "current_step": "reasoner_agent", "progress": 55.0}
    for k in ["user_id", "task_id", "subject", "difficulty", "input_type", "image_path", "grade", "original_input", "summarized_input"]:
        if state.get(k) is not None:
            out[k] = state.get(k)
    return out

async def normalizer_agent(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalizer Agent：
    - taxonomy 归一（候选优先）
    - NEW 门控
    - 同义合并（将 NEW 标签尽量映射到已存在候选）
    """
    task_id = state.get("task_id")
    if task_id and task_id in _initial_state_cache:
        state = {**_initial_state_cache[task_id], **state}

    t0 = time.perf_counter()
    items = state.get("reasoned_items") if isinstance(state.get("reasoned_items"), list) else None
    if items is None:
        items = state.get("ocr_items") if isinstance(state.get("ocr_items"), list) else []
    items_in = len(items or [])
    logger.info(f"[normalizer_agent] {_ctx(state)} start items_in={items_in}")

    subject = state.get("subject", "physics")  # 默认物理
    grade = state.get("grade", "")
    user_id = int(state.get("user_id") or 0)
    difficulty = state.get("difficulty", "medium")

    if not items:
        msg = "缺少 OCR/深度解析结果，无法归一化"
        logger.error(f"[normalizer_agent] {_ctx(state)} error: {msg}")
        if task_id:
            from backend.core.db.session import async_session_maker
            from backend.core.crud import crud_task
            from backend.core.db.models import TaskStatusEnum
            async with async_session_maker() as db:
                await crud_task.update_task_status(
                    db,
                    task_id,
                    TaskStatusEnum.FAILED,
                    progress=100.0,
                    current_step=msg,
                    error_message=msg,
                    result_patch={"status": "failed", "error": "missing_inputs"},
                    result_stage="normalizer",
                )
                await db.commit()
        out = {**state, "errors": list(state.get("errors") or []) + [msg], "parse_success": False, "current_step": "normalizer_agent", "progress": 60.0}
        return out

    candidates = await get_dynamic_taxonomy_candidates(
        user_id=user_id,
        subject=str(subject),
        grade=grade,
        max_chapters=30,
        max_kps=40,
    )
    allowed_chapters = set(candidates.get("chapters") or [])
    allowed_kps = set(candidates.get("knowledge_points") or [])

    max_new_chapters = int(os.getenv("WZY_MAX_NEW_CHAPTERS_PER_REQUEST") or "2")
    max_new_kps = int(os.getenv("WZY_MAX_NEW_KPS_PER_REQUEST") or "6")

    # 同义合并：对 NEW 标签尽量映射到候选
    async def merge_synonyms(kind: str, new_labels: List[str], cand: List[str]) -> Dict[str, str]:
        if not new_labels or not cand:
            return {}
        prompt = f"""你是教研员。将新标签尽量合并到已有候选（同义/近义/上位类）。

kind={kind}
候选（可合并目标）：
{json.dumps(cand[:40], ensure_ascii=False)}

新标签（需要映射）：
{json.dumps(new_labels, ensure_ascii=False)}

规则：
- 若能合并到某个候选，输出该候选
- 否则保留原标签（直接输出原标签字符串）
- 严格输出 JSON：{{"mapping": {{"新标签": "候选或原标签"}}}}"""
        parsed = await call_router_llm_json(
            prompt,
            log_ctx=_ctx(state),
            trace_id=str(task_id) if task_id else None,
            trace_stage="normalizer",
        )
        mapping = (parsed or {}).get("mapping")
        return mapping if isinstance(mapping, dict) else {}

    raw_new_chapters = []
    raw_new_kps = []
    for it in items:
        ch = str(it.get("chapter") or "").strip()
        if ch.lower().startswith("new:"):
            raw_new_chapters.append(_sanitize_label(ch))
        for kp in (it.get("knowledge_points") or []):
            s = str(kp).strip()
            if s.lower().startswith("new:"):
                raw_new_kps.append(_sanitize_label(s))

    raw_new_chapters = list(dict.fromkeys([x for x in raw_new_chapters if x]))
    raw_new_kps = list(dict.fromkeys([x for x in raw_new_kps if x]))

    chapter_mapping = await merge_synonyms("chapter", raw_new_chapters, list(allowed_chapters))
    kp_mapping = await merge_synonyms("knowledge_points", raw_new_kps, list(allowed_kps))

    accepted_new_chapters: List[str] = []
    accepted_new_kps: List[str] = []

    normalized_items: List[Dict[str, Any]] = []
    for it in items:
        q = dict(it)

        # chapter
        ch_raw = str(q.get("chapter") or "").strip()
        ch_final = "综合"
        if ch_raw in allowed_chapters:
            ch_final = ch_raw
        elif ch_raw.lower().startswith("new:"):
            new_label = _sanitize_label(ch_raw)
            mapped = chapter_mapping.get(new_label, new_label)
            if mapped in allowed_chapters:
                ch_final = mapped
            elif mapped and len(accepted_new_chapters) < max_new_chapters:
                ch_final = mapped
                if mapped not in accepted_new_chapters:
                    accepted_new_chapters.append(mapped)
        q["chapter"] = ch_final

        # knowledge points
        kp_list = q.get("knowledge_points") if isinstance(q.get("knowledge_points"), list) else []
        kp_final: List[str] = []
        for kp in kp_list:
            s = str(kp).strip()
            if not s:
                continue
            if s in allowed_kps and s not in kp_final:
                kp_final.append(s)
            elif s.lower().startswith("new:"):
                new_label = _sanitize_label(s)
                mapped = kp_mapping.get(new_label, new_label)
                if mapped in allowed_kps and mapped not in kp_final:
                    kp_final.append(mapped)
                elif mapped and len(accepted_new_kps) < max_new_kps and mapped not in kp_final:
                    kp_final.append(mapped)
                    if mapped not in accepted_new_kps:
                        accepted_new_kps.append(mapped)
            if len(kp_final) >= 3:
                break
        q["knowledge_points"] = kp_final or ["综合"]

        # tags
        if not isinstance(q.get("tags"), list):
            q["tags"] = []
        q["tags"] = [str(x).strip() for x in q.get("tags", []) if str(x).strip()][:6]

        normalized_items.append(q)

    structured_data_list: List[Dict[str, Any]] = []
    for it in normalized_items:
        structured_data_list.append(
            {
                "question_body": (it.get("question_content") or "").strip(),
                "student_answer": (it.get("student_answer") or "").strip(),
                "correct_answer": (it.get("correct_answer") or "").strip(),
                "is_correct": it.get("is_correct"),
                "score": it.get("score"),
                "max_score": it.get("max_score"),
                "explanation": (it.get("explanation") or "").strip() if isinstance(it.get("explanation"), str) else None,
                "error_analysis": (it.get("error_analysis") or "").strip(),
                "suggested_questions": it.get("suggested_questions") or [],
                "knowledge_points": it.get("knowledge_points") or [],
                "chapter": it.get("chapter") or None,
                "tags": it.get("tags") or [],
                # 保序字段（可选）：供 save_question 写入 upload_index
                "order": it.get("order"),
                "question_number": it.get("question_number"),
                "subject": subject,
                "difficulty": difficulty,
            }
        )

    if task_id:
        from backend.core.db.session import async_session_maker
        from backend.core.crud import crud_task
        from backend.core.db.models import TaskStatusEnum
        async with async_session_maker() as db:
            await crud_task.update_task_status(
                db,
                task_id,
                TaskStatusEnum.PROCESSING,
                progress=75.0,
                current_step="分类归一化完成，正在保存到数据库...",
                result_patch={
                    "new_chapters_accepted": accepted_new_chapters,
                    "new_kps_accepted": accepted_new_kps,
                    "items": [
                        {
                            "index": i,
                            "chapter": (it.get("chapter") or "")[:50],
                            "knowledge_points": (it.get("knowledge_points") or [])[:5],
                            "tags": (it.get("tags") or [])[:6],
                        }
                        for i, it in enumerate(normalized_items[: int(os.getenv("WZY_DEEP_ENRICH_MAX_ITEMS") or "10")])
                    ],
                },
                result_stage="normalizer",
            )
            await db.commit()

    duration_ms = int((time.perf_counter() - t0) * 1000)
    logger.info(
        f"[normalizer_agent] {_ctx(state)} done items_out={len(normalized_items)} "
        f"accepted_new_chapters={len(accepted_new_chapters)} accepted_new_kps={len(accepted_new_kps)} duration_ms={duration_ms}"
    )

    return {
        "structured_data_list": structured_data_list,
        "structured_data": structured_data_list[0] if structured_data_list else {},
        "parse_success": True,
        "current_step": "normalizer_agent",
        "progress": 75.0,
        "subject": subject,
        "difficulty": difficulty,
        "user_id": user_id,
        "task_id": task_id,
        "grade": grade,
    }

async def save_question(state: Dict[str, Any]) -> Dict[str, Any]:
    """保存错题节点"""
    t0 = time.perf_counter()
    logger.info(f"[save_question] {_ctx(state)} start")
    logger.debug(f"[save_question] Entry - State keys: {list(state.keys())}")
    logger.debug(f"[save_question] Cache keys: {list(_initial_state_cache.keys())}")
    
    # 从全局缓存获取初始状态，确保关键字段不丢失
    task_id = state.get("task_id")
    initial_state = None
    
    if task_id and task_id in _initial_state_cache:
        initial_state = _initial_state_cache[task_id]
        logger.debug(f"[save_question] Found cache by task_id: {task_id}, user_id={initial_state.get('user_id')}")
    else:
        # 如果 task_id 也是 None 或不在缓存中，尝试从缓存中找到匹配的初始状态
        subject_hint = state.get("subject") or state.get("structured_data", {}).get("subject", "physics")
        difficulty_hint = state.get("difficulty") or state.get("structured_data", {}).get("difficulty", "medium")
        
        logger.info(f"[save_question] Searching cache by subject={subject_hint}, difficulty={difficulty_hint}")
        
        # 尝试精确匹配
        for cached_task_id, cached_state in _initial_state_cache.items():
            cached_subject = cached_state.get("subject", "").lower()
            cached_difficulty = cached_state.get("difficulty", "").lower()
            if (cached_subject == subject_hint.lower() and 
                cached_difficulty == difficulty_hint.lower()):
                initial_state = cached_state
                task_id = cached_task_id
                logger.info(f"[save_question] Found matching cache entry: task_id={cached_task_id}, user_id={initial_state.get('user_id')}")
                break
        
        # 如果还是没找到，使用最后一个缓存条目（通常是最新的）
        if initial_state is None and _initial_state_cache:
            last_task_id = list(_initial_state_cache.keys())[-1]
            initial_state = _initial_state_cache[last_task_id]
            task_id = last_task_id
            logger.warning(f"[save_question] Using last cache entry as fallback: task_id={last_task_id}, user_id={initial_state.get('user_id')}")
    
    # 合并初始状态和当前状态（初始状态优先，确保关键字段不丢失）
    if initial_state:
        state = {**initial_state, **state}
        task_id = state.get("task_id")  # 重新获取 task_id
        logger.debug(f"[save_question] After merge - task_id={task_id}, user_id={state.get('user_id')}")
    else:
        logger.error(f"[save_question] No cache entry found! Cache is empty or task_id mismatch.")
    
    logger.info(f"[save_question] {_ctx(state)} saving_to_db")
    logger.debug(f"[save_question] Full state keys: {list(state.keys())}")
    logger.debug(f"[save_question] State values: user_id={state.get('user_id')}, task_id={state.get('task_id')}, subject={state.get('subject')}")

    from backend.core.db.session import async_session_maker
    from backend.core.crud import crud_question, crud_task
    from backend.core.db.models import SubjectEnum, DifficultyEnum, QuestionSourceEnum

    user_id = state.get("user_id")
    task_id = state.get("task_id")
    
    structured_data = state.get("structured_data", {})
    structured_data_list = state.get("structured_data_list") if isinstance(state.get("structured_data_list"), list) else None
    subject = state.get("subject", "physics")  # 默认物理
    difficulty = state.get("difficulty", "medium")
    grade = state.get("grade", "")

    # 验证必要字段
    if not user_id:
        logger.error(f"[save_question] user_id is missing in state. State keys: {list(state.keys())}, State: {state}")
        logger.error(f"[save_question] Cache contents: {list(_initial_state_cache.keys())}")
        for cached_task_id, cached_state in _initial_state_cache.items():
            logger.error(f"[save_question] Cache entry {cached_task_id}: user_id={cached_state.get('user_id')}")
        return {
            "errors": ["user_id 缺失，无法保存错题"],
            "success": False,
            "current_step": "save_question",
            "progress": 60.0,
        }

    # 如果前面节点已经产生错误（例如：学科不匹配），则不入库，直接失败任务
    if isinstance(state.get("errors"), list) and state.get("errors"):
        err_msg = "; ".join([str(e) for e in state.get("errors") if e])
        try:
            async with async_session_maker() as db:
                await crud_task.fail_task(db, task_id, err_msg or "任务失败")
                await db.commit()
        except Exception:
            pass
        return {
            "errors": state.get("errors"),
            "success": False,
            "current_step": "save_question",
            "progress": 60.0,
        }
    
    # 再次验证 user_id 不是 None（双重保险）
    if user_id is None:
        logger.error(f"[save_question] user_id is None after all attempts. State: {state}")
        return {
            "errors": ["user_id 缺失，无法保存错题"],
            "success": False,
            "current_step": "save_question",
            "progress": 60.0,
        }

    try:
        async with async_session_maker() as db:
            # 解析学科和难度
            try:
                subject_enum = SubjectEnum(subject)
            except ValueError:
                subject_enum = SubjectEnum.OTHER

            try:
                difficulty_enum = DifficultyEnum(difficulty)
            except ValueError:
                difficulty_enum = DifficultyEnum.MEDIUM

            items = structured_data_list or [structured_data]
            # 保证入库顺序与试卷顺序一致：优先按 order(1..n) 排序，否则保持原顺序
            try:
                indexed = []
                for i, it in enumerate(items):
                    v = it.get("order") if isinstance(it, dict) else None
                    try:
                        ov = int(v)
                    except Exception:
                        ov = None
                    indexed.append((ov if ov is not None else 10**9, i, it))
                items = [it for _, __, it in sorted(indexed, key=lambda x: (x[0], x[1]))]
            except Exception:
                pass

            created_ids: List[int] = []
            for idx, item in enumerate(items):
                # 确保 content 不为空（Pydantic 验证要求）
                question_content = (item.get("question_body") or "").strip()
                if not question_content:
                    question_content = "题目内容待补充"

                question_data = {
                    "user_id": int(user_id),
                    "content": question_content,
                    "student_answer": item.get("student_answer"),
                    "correct_answer": item.get("correct_answer") or None,
                    "is_correct": item.get("is_correct"),
                    "score": item.get("score"),
                    "max_score": item.get("max_score"),
                    "explanation": item.get("explanation"),
                    "subject": subject_enum,
                    "grade": grade,
                    "difficulty": difficulty_enum,
                    "knowledge_points": item.get("knowledge_points", []),
                    "error_analysis": item.get("error_analysis"),
                    "suggested_questions": item.get("suggested_questions") or [],
                    "chapter": item.get("chapter") or None,
                    "tags": item.get("tags") or [],
                    "source": QuestionSourceEnum.MANUAL,
                    "source_description": "录入错题功能",
                    # 保序：同一次上传的多题，按 OCR 输出顺序入库
                    "upload_group_id": task_id,
                    "upload_index": int(idx + 1),
                }

                # 图片：同一张图片可对应多道错题
                if state.get("input_type") == "image" and state.get("image_path"):
                    question_data["image_urls"] = [state.get("image_path")]
                    if state.get("source_image_id") is not None:
                        question_data["source_image_id"] = int(state.get("source_image_id"))

                # 原始输入/总结（图片/文字模式都支持）
                if state.get("original_input") is not None:
                    question_data["original_input"] = state.get("original_input")
                # summarized_input：为避免新增 DB 字段，用 JSON 存"答案来源/判定依据"
                try:
                    meta = {
                        "answer_sources": {
                            "student_answer_raw": item.get("student_answer") or "",
                            "teacher_marked_answer": item.get("teacher_marked_answer") or "",
                            "model_inferred_answer": item.get("model_inferred_answer") or "",
                        },
                        "grading": {
                            "decided_by": item.get("grading_basis") or "unknown",
                            "note": "是否错题优先按老师批改/自标答案判定；模型答案仅供参考",
                        },
                    }
                    # Teacher marking evidence (tick/cross/color)
                    tm = {
                        "is_correct": item.get("teacher_marked_is_correct"),
                        "mark": item.get("teacher_marked_mark") or "",
                        "color": item.get("teacher_marked_color") or "",
                        "evidence": item.get("teacher_marked_evidence") or "",
                    }
                    # Only keep if at least one signal exists
                    if (
                        tm.get("is_correct") is True
                        or tm.get("is_correct") is False
                        or tm.get("mark")
                        or tm.get("color")
                        or tm.get("evidence")
                    ):
                        meta["grading"]["teacher_mark"] = tm
                    # Keep the previous summarized_input (e.g. overall_analysis/text_summary) if available
                    if state.get("summarized_input") is not None:
                        meta["summary"] = state.get("summarized_input")
                    question_data["summarized_input"] = json.dumps(meta, ensure_ascii=False)
                except Exception:
                    if state.get("summarized_input") is not None:
                        question_data["summarized_input"] = state.get("summarized_input")

                if question_data.get("user_id") is None:
                    raise ValueError("user_id 缺失，无法保存错题")

                logger.info(
                    f"[save_question] Creating question {idx+1}/{len(items)} with user_id={question_data['user_id']}, "
                    f"subject={subject_enum}, difficulty={difficulty_enum}"
                )

                q = await crud_question.create_question(db, question_data=None, **question_data)
                created_ids.append(q.id)

            await db.commit()

            # 任务表仍保留单个 question_id（兼容），但在 result 里返回全部 question_ids
            first_id = created_ids[0]
            await crud_task.complete_task(
                db,
                task_id,
                first_id,
                result={
                    "stages": {
                        "saved": {
                            "question_ids": created_ids,
                            "created_count": len(created_ids),
                            "source_image_id": state.get("source_image_id"),
                            "upload_group_id": task_id,
                        }
                    }
                },
            )
            await db.commit()

            duration_ms = int((time.perf_counter() - t0) * 1000)
            logger.info(f"[save_question] {_ctx(state)} done created_count={len(created_ids)} ids={created_ids} duration_ms={duration_ms}")

            return {
                "question_id": first_id,
                "question_ids": created_ids,
                "created_count": len(created_ids),
                "success": True,
                "current_step": "save_question",
                "progress": 100.0,
            }

    except Exception as e:
        duration_ms = int((time.perf_counter() - t0) * 1000) if "t0" in locals() else -1
        logger.error(f"[save_question] {_ctx(state)} error duration_ms={duration_ms}: {e}", exc_info=True)
        return {
            "errors": [f"保存错题失败: {str(e)}"],
            "success": False,
            "current_step": "save_question",
            "progress": 60.0,
        }