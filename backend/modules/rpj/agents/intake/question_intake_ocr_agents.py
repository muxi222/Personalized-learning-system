"""
错题录入OCR Agent - Question Intake OCR Agent (RPJ模块版本)
专门用于"录入错题"功能，支持语文、英语、政治学科

RPJ模块支持的学科: chinese, english, politics
"""

import os
import uuid
import json
import logging
import time
from typing import Dict, Any, Optional, List, Tuple
from collections import Counter

from langgraph.graph import StateGraph, END

from backend.core.agents.base_agent import BaseAgent
from backend.modules.rpj.config import settings

logger = logging.getLogger(__name__)

# -------------------------
# Logging helpers
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

    # If code fences exist, try each fenced segment first
    if "```" in s:
        s2 = s.replace("```json", "```").replace("```JSON", "```")
        parts = [p.strip() for p in s2.split("```") if p.strip()]
        for part in sorted(parts, key=len, reverse=True)[:12]:
            got = _parse_any(part)
            if got is not None:
                return got

    return _parse_any(s)

# 全局变量：保存初始状态
_initial_state_cache: Dict[str, Dict[str, Any]] = {}

# =========================
# 学科分类（chapter/tags） - RPJ模块版本
# =========================
CATEGORY_TAXONOMY: Dict[str, Dict[str, List[str]]] = {
    # 语文
    "chinese": {
        "junior": ["现代文阅读", "古诗文阅读", "语言文字运用", "写作", "名著导读", "综合"],
        "senior": ["现代文阅读", "古诗文阅读", "语言文字运用", "写作", "名著导读", "综合"],
    },
    # 英语
    "english": {
        "junior": ["听力", "阅读", "完形填空", "语法填空", "写作", "口语", "综合"],
        "senior": ["听力", "阅读", "完形填空", "语法填空", "写作", "口语", "综合"],
    },
    # 政治
    "politics": {
        "junior": ["心理健康", "道德与法治", "国情教育", "综合"],
        "senior": ["经济生活", "政治生活", "文化生活", "生活与哲学", "综合"],
    },
    "other": {
        "junior": ["综合"],
        "senior": ["综合"],
    },
}

KNOWLEDGE_POINT_TAXONOMY: Dict[str, Dict[str, List[str]]] = {
    # 语文
    "chinese": {
        "junior": [
            "字音字形", "词语理解", "句子运用", "修辞手法", "文学常识",
            "古诗词鉴赏", "文言文阅读", "现代文阅读", "写作技巧", "综合"
        ],
        "senior": [
            "语言文字运用", "现代文阅读", "古诗词鉴赏", "文言文阅读",
            "名著阅读", "写作技巧", "综合"
        ],
    },
    # 英语
    "english": {
        "junior": [
            "词汇", "语法", "阅读理解", "完形填空", "听力",
            "口语表达", "写作技巧", "综合"
        ],
        "senior": [
            "词汇", "语法", "阅读理解", "完形填空", "听力",
            "口语表达", "写作技巧", "综合"
        ],
    },
    # 政治
    "politics": {
        "junior": [
            "个人成长", "人际交往", "社会公德", "法律常识",
            "国情教育", "综合"
        ],
        "senior": [
            "经济学原理", "政治制度", "文化传承", "哲学思想",
            "时事政治", "综合"
        ],
    },
    "other": {
        "junior": ["综合"],
        "senior": ["综合"],
    },
}

def normalize_grade_bucket(grade: Optional[str]) -> str:
    """
    将前端输入的年级/学段归一化为 junior/senior。
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
    """获取章节分类候选列表"""
    bucket = normalize_grade_bucket(grade)
    return CATEGORY_TAXONOMY.get(subject, CATEGORY_TAXONOMY.get("other", {})).get(bucket, ["综合"])

def get_knowledge_point_candidates(subject: str, grade: Optional[str]) -> List[str]:
    """获取知识点候选列表"""
    bucket = normalize_grade_bucket(grade)
    return KNOWLEDGE_POINT_TAXONOMY.get(subject, KNOWLEDGE_POINT_TAXONOMY.get("other", {})).get(bucket, ["综合"])

def get_text_reasoning_model_names() -> List[str]:
    """
    文本深度推理模型列表
    """
    raw = (os.getenv("RPJ_TEXT_REASONING_MODELS") or "").strip()
    if raw:
        models = [m.strip() for m in raw.split(",") if m.strip()]
        return models
    return [settings.GEMINI_MODEL or "gemini-2.5-flash"]

def _sanitize_label(label: str, *, max_len: int = 30) -> str:
    """清理标签"""
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
    Coerce various model output shapes into the canonical format
    """
    if parsed is None:
        return None

    # Top-level list -> treat as results
    if isinstance(parsed, list):
        out = [x for x in parsed if isinstance(x, dict)]
        if not out:
            return None
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
            for k in ("results", "items", "data"):
                inner = obj.get(k)
                got = _from_any(inner)
                if got is not None:
                    return got

            out: List[Dict[str, Any]] = []
            for k, v in obj.items():
                if not isinstance(v, dict):
                    continue
                if not isinstance(v.get("index"), int):
                    try:
                        v["index"] = int(k)
                    except Exception:
                        pass
                out.append(v)
            if not out:
                return None
            def _key(r: Dict[str, Any]) -> tuple[int, int]:
                idx = r.get("index")
                if not isinstance(idx, int):
                    idx = 10**9
                return (idx, id(r))
            out.sort(key=_key)
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
        处理1-based索引
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
        if min_idx == 1 and expected_len > 0 and (max_idx == expected_len or max_idx == len(got)):
            for r in got:
                if isinstance(r.get("index"), int):
                    r["index"] = int(r["index"]) - 1
        return got

    for c in candidates:
        got = _from_any(c)
        if got is not None:
            got = _maybe_shift_one_based_indices(got)
            if expected_len > 0:
                got = [r for r in got if isinstance(r.get("index"), int)]
                got = [r for r in got if 0 <= int(r["index"]) < expected_len]
            return got
    return None

async def get_dynamic_taxonomy_candidates(
    *,
    user_id: int,
    subject: str,
    grade: Optional[str],
    max_chapters: int = 20,
    max_kps: int = 50,
) -> Dict[str, List[str]]:
    """
    从数据库中动态提取分类候选
    """
    from sqlalchemy import select, func
    from backend.core.db.session import async_session_maker
    from backend.core.db.models import Question, SubjectEnum

    # 基础候选
    seed_chapters = get_category_candidates(subject, grade) or ["综合"]
    seed_kps = get_knowledge_point_candidates(subject, grade) or ["综合"]

    try:
        subject_enum = SubjectEnum(subject)
    except Exception:
        subject_enum = SubjectEnum.OTHER

    chapters: List[str] = []
    kps: List[str] = []

    async with async_session_maker() as db:
        # 获取章节
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

        # 获取知识点
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

    # 合并去重
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
    深度解析：在OCR基础上进行二次推理
    """
    if not items:
        return items

    max_items = int(os.getenv("RPJ_DEEP_ENRICH_MAX_ITEMS") or "10")
    max_new_chapters = int(os.getenv("RPJ_MAX_NEW_CHAPTERS_PER_REQUEST") or "2")
    max_new_kps = int(os.getenv("RPJ_MAX_NEW_KPS_PER_REQUEST") or "6")

    # 根据学科构建提示词
    subject_prompts = {
        "chinese": "你是资深语文教研员与讲题老师。",
        "english": "你是资深英语教研员与讲题老师。",
        "politics": "你是资深政治教研员与讲题老师。",
    }
    subject_desc = subject_prompts.get(user_selected_subject, "你是资深教研员与讲题老师。")

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

    prompt = f"""{subject_desc}现在给你 OCR(浅层) 提取出的多道错题，请你做"深度解析 + 分类归一化"。

用户选择学科：{user_selected_subject}
年级/学段：{grade or "未知"}

请输出：
1) detected_subject（必须是 ["{user_selected_subject}", "other"] 之一）与 confidence(0~1)
2) 对每道题输出 results：
   - question_content：更清晰、更完整的题干（修正OCR错误）
   - student_answer / correct_answer：若能从上下文推断则补全，否则保留原样
   - explanation：简要解题思路（可为空）
   - error_analysis：错因分析（要具体）
   - suggested_questions：3~5 个"同类型训练点"或"举一反三方向"（短句）
   - chapter：优先从候选 chapters 选择；如需新增用 "NEW:xxx"（新增总数不超过 {max_new_chapters}）
   - knowledge_points：优先从候选 knowledge_points 选择 1~3 个；如需新增用 "NEW:xxx"（新增总数不超过 {max_new_kps}）
   - tags：2~6 个短标签

候选分类（优先从候选中选择；语义接近必须选候选，避免发散）：
{json.dumps(taxonomy, ensure_ascii=False)}

题目列表：
{json.dumps(prompt_items, ensure_ascii=False)}

严格输出 JSON：
{{
  "detected_subject": "{user_selected_subject}|other",
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

    # NEW门控
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

        # 分类归一化
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
    调用LLM
    """
    content, _ = await _call_router_llm_internal(
        prompt=prompt,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        log_ctx=log_ctx,
        trace_id=trace_id,
        trace_stage=trace_stage,
        return_meta=False
    )
    return content

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
    调用LLM（带元数据返回）
    """
    return await _call_router_llm_internal(
        prompt=prompt,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        log_ctx=log_ctx,
        trace_id=trace_id,
        trace_stage=trace_stage,
        return_meta=True
    )

async def _call_router_llm_internal(
    prompt: str,
    *,
    model: Optional[str] = None,
    temperature: float = 0.2,
    max_tokens: int = 4096,
    log_ctx: str = "",
    trace_id: Optional[str] = None,
    trace_stage: str = "llm",
    return_meta: bool = False
) -> Any:
    import httpx
    import asyncio
    import time
    from backend.core.services.llm_utils import get_llm_semaphore
    from backend.core.services.llm_trace import write_llm_trace

    if not settings.LLM_API_ENDPOINT:
        logger.error(f"[LLM_DEBUG] {log_ctx} ERROR: LLM_API_ENDPOINT not configured")
        raise RuntimeError("LLM_API_ENDPOINT not configured")

    endpoint = settings.LLM_API_ENDPOINT.rstrip("/")
    models_to_try = [model] if (model and model.strip()) else get_text_reasoning_model_names()
    
    headers = {}
    if getattr(settings, "LLM_API_KEY", None):
        headers["authorization"] = f"Bearer {settings.LLM_API_KEY}"

    timeout_s = float(os.getenv("RPJ_TEXT_REASONING_TIMEOUT_SECONDS") or "300")
    
    async with httpx.AsyncClient(base_url=endpoint, timeout=timeout_s, follow_redirects=True) as client:
        last_err: Optional[Exception] = None
        for m in models_to_try:
            max_attempts = int(os.getenv("LLM_RETRY_MAX_ATTEMPTS") or "3")
            
            for attempt in range(max_attempts):
                t_start = time.perf_counter()
                try:
                    req = {
                        "model": m,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    }
                    
                    if trace_id:
                        write_llm_trace(trace_id=str(trace_id), stage=str(trace_stage), kind=f"req_{attempt+1}", payload=req, suffix="json")

                    async with get_llm_semaphore():
                        resp = await client.post("/chat/completions", json=req, headers=headers)
                    
                    duration = (time.perf_counter() - t_start) * 1000

                    if trace_id:
                        try:
                            resp_text_preview = resp.text[:500]
                        except:
                            resp_text_preview = "error_reading_text"
                        write_llm_trace(
                            trace_id=str(trace_id), 
                            stage=str(trace_stage), 
                            kind=f"resp_{attempt+1}", 
                            payload={"status": resp.status_code, "text_preview": resp_text_preview}, 
                            suffix="json"
                        )

                    if resp.status_code in (429, 500, 502, 503, 504) and attempt < max_attempts - 1:
                        await asyncio.sleep(1)
                        continue
                        
                    resp.raise_for_status()
                    data = resp.json()
                    
                    content = data["choices"][0]["message"]["content"]
                    
                    if return_meta:
                        return content, m
                    return content

                except Exception as e:
                    duration = (time.perf_counter() - t_start) * 1000
                    last_err = e
                    if attempt < max_attempts - 1:
                        await asyncio.sleep(1)
                        continue
                    break

        if last_err:
            logger.error(f"[LLM_DEBUG] All attempts failed. Last error: {last_err}")
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
    调用 LLM 并尝试解析 JSON
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
    错题录入OCR Agent - RPJ模块版本
    支持语文、英语、政治学科
    """

    def __init__(self):
        super().__init__(subjects=settings.SUBJECTS)
        self._graph = None

    def get_graph(self, initial_state: Optional[Dict[str, Any]] = None):
        """获取图实例"""
        return create_intake_ocr_graph(initial_state)

    async def process(
        self,
        input_type: str,
        user_id: int,
        task_id: str,
        subject: str,
        difficulty: str = "medium",
        grade: str = "",
        source_image_id: Optional[int] = None,
        image_file: Optional[Any] = None,
        image_path: Optional[str] = None,
        text_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        处理错题录入
        """
        # Validate subject
        if not self.validate_subject(subject):
            logger.error(f"Subject '{subject}' not supported by RPJ module")
            return {
                "task_id": task_id,
                "question_id": None,
                "success": False,
                "errors": [f"Subject '{subject}' not supported by RPJ module. Supported: {settings.SUBJECTS}"],
            }

        # 构建初始状态
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
            "input_type": input_type,
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
            # 保存初始状态到全局缓存
            _initial_state_cache[task_id] = state_dict.copy()
            
            # 创建图实例
            graph = self.get_graph(initial_state=state_dict)
            
            # 执行图
            final_state = None
            async for state in graph.astream(state_dict):
                for node_name, node_output in state.items():
                    if isinstance(node_output, dict):
                        final_state = {**state_dict, **(final_state or {}), **node_output}
            
            if final_state is None:
                final_state = state_dict.copy()
            
            # 确保关键字段存在
            for key in ["user_id", "task_id", "subject", "difficulty", "input_type"]:
                if final_state.get(key) is None and state_dict.get(key) is not None:
                    final_state[key] = state_dict.get(key)
            
            # 清理缓存
            try:
                _initial_state_cache.pop(task_id, None)
            except Exception:
                pass
            
            # 构建返回结果
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
    from typing import Dict, Any
    
    # 如果提供了初始状态，使用闭包让节点能访问到初始状态
    if initial_state:
        def wrap_node(node_func):
            async def wrapped_node(state: Dict[str, Any]) -> Dict[str, Any]:
                merged_state = {**initial_state, **state}
                result = await node_func(merged_state)
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
    task_id = state.get("task_id")
    if task_id and task_id in _initial_state_cache:
        initial_state = _initial_state_cache[task_id]
        merged_state = {**initial_state, **state}
        return {
            **merged_state,
            "current_step": "process_input",
            "progress": 10.0,
        }
    return {
        "current_step": "process_input",
        "progress": 10.0,
    }

async def ocr_agent(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    OCR Agent - RPJ版本
    """
    task_id = state.get("task_id")
    if task_id and task_id in _initial_state_cache:
        state = {**_initial_state_cache[task_id], **state}

    t0 = time.perf_counter()
    image_path = state.get("image_path")
    logger.info(
        f"[ocr_agent] {_ctx(state)} start vision_model={os.getenv('RPJ_OCR_VISION_MODEL') or settings.GEMINI_MODEL} "
        f"image={os.path.basename(image_path) if image_path else None}"
    )

    image_path = state.get("image_path")
    subject = state.get("subject", "chinese")
    grade = state.get("grade", "")

    if not image_path:
        return {"errors": ["没有提供图片路径"], "current_step": "ocr_agent", "progress": 10.0}

    try:
        from backend.core.services.gemini_ocr_service import get_gemini_ocr_service, SubjectType

        ocr_service = get_gemini_ocr_service(settings)
        await ocr_service.initialize()

        # 学科映射
        subject_map = {
            "chinese": SubjectType.CHINESE,
            "english": SubjectType.ENGLISH,
            "politics": SubjectType.OTHER,  # 政治暂时使用OTHER
            "other": SubjectType.OTHER,
        }
        subject_type = subject_map.get(str(subject).lower(), SubjectType.CHINESE)

        # 根据不同学科构建提示词
        subject_hints = {
            "chinese": "这是语文错题识别场景：一张图片可能包含多道错题。请识别图片中的所有题目，特别注意文言文、古诗词、现代文阅读、作文等题型。",
            "english": "这是英语错题识别场景：一张图片可能包含多道错题。请识别图片中的所有题目，特别注意阅读理解、完形填空、语法填空、写作等题型。",
            "politics": "这是政治错题识别场景：一张图片可能包含多道错题。请识别图片中的所有题目，特别注意选择题、简答题、论述题等题型。",
        }
        user_hint = subject_hints.get(subject, "这是错题识别场景：一张图片可能包含多道错题。请识别图片中的所有题目。")
        user_hint += " 请务必返回每道题在图片中的边界框坐标 (box_2d)，格式为 [ymin, xmin, ymax, xmax] (0-1000归一化坐标)。"
        user_hint += " 请按试卷中题目出现的顺序组织 questions 数组。"

        analysis_result = await ocr_service.analyze_exam_image(
            image_path=image_path,
            subject=subject_type,
            grade=str(grade or ""),
            user_hint=user_hint,
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
                            "error_analysis": (getattr(qi, "error_analysis", "") or "").strip(),
                            "question_number": qn,
                        },
                    )
                )

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

        # 更新任务状态
        if task_id:
            from backend.core.db.session import async_session_maker
            from backend.core.crud import crud_task
            from backend.core.db.models import TaskStatusEnum
            async with async_session_maker() as db:
                compact_items = [
                    {
                        "index": i,
                        "question_content": (it.get("question_content") or "")[:400],
                        "student_answer": (it.get("student_answer") or "")[:200],
                        "correct_answer": (it.get("correct_answer") or "")[:200],
                        "question_type": (it.get("question_type") or "")[:50],
                        "knowledge_points": (it.get("knowledge_points") or [])[:5],
                    }
                    for i, it in enumerate(extracted_items[: int(os.getenv("RPJ_DEEP_ENRICH_MAX_ITEMS") or "10")])
                ]
                await crud_task.update_task_status(
                    db,
                    task_id,
                    TaskStatusEnum.PROCESSING,
                    progress=25.0,
                    current_step="OCR识别完成，正在进行深度解析...",
                    result_patch={
                        "ocr_model": os.getenv("RPJ_OCR_VISION_MODEL"),
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
    Reasoner Agent - RPJ版本
    """
    task_id = state.get("task_id")
    if task_id and task_id in _initial_state_cache:
        state = {**_initial_state_cache[task_id], **state}

    t0 = time.perf_counter()
    input_type = state.get("input_type", "image")
    subject = state.get("subject", "chinese")
    grade = state.get("grade", "")
    user_id = state.get("user_id")

    # 准备待处理项
    if input_type == "image":
        base_items = list(state.get("ocr_items") or [])
        if not base_items:
            return {"errors": ["缺少 OCR 结果"], "current_step": "reasoner_agent", "progress": 30.0}
    else:
        # 文字模式
        text_data = state.get("text_data") or {}
        base_items = [{
            "question_content": str(text_data.get("content") or text_data.get("question") or ""),
            "student_answer": str(text_data.get("student_answer") or ""),
            "correct_answer": str(text_data.get("correct_answer") or ""),
            "knowledge_points": text_data.get("knowledge_points", [])
        }]

    # 准备 Taxonomy
    taxonomy = {}
    try:
        # RPJ模块支持的学科
        rpj_subjects = ["chinese", "english", "politics", "other"]
        for s in rpj_subjects:
            taxonomy[s] = await get_dynamic_taxonomy_candidates(
                user_id=int(user_id or 0), subject=s, grade=grade, max_chapters=20, max_kps=30
            )
    except Exception:
        for s in ["chinese", "english", "politics", "other"]:
            taxonomy[s] = {"chapters": ["综合"], "knowledge_points": ["综合"]}

    # 分批处理配置
    BATCH_SIZE = 1
    total_items = len(base_items)
    
    logger.info(f"[reasoner_agent] {_ctx(state)} start serial processing. Total={total_items}, Batch={BATCH_SIZE}")

    all_results_buffer: List[Dict[str, Any]] = []
    detected_subjects = []
    
    for i in range(0, total_items, BATCH_SIZE):
        batch_slice = base_items[i : i + BATCH_SIZE]
        current_indices = range(i, i + len(batch_slice))
        
        prompt_items = []
        for local_idx, item in enumerate(batch_slice):
            global_idx = i + local_idx
            prompt_items.append({
                "index": global_idx,
                "question_content": (item.get("question_content") or "")[:1200],
                "student_answer": (item.get("student_answer") or "")[:400],
                "correct_answer": (item.get("correct_answer") or "")[:400],
                "ocr_knowledge_points": item.get("knowledge_points", []),
            })

        logger.info(f"[reasoner_agent] Processing batch {i//BATCH_SIZE + 1}: Items {list(current_indices)}")

        # 根据不同学科构建提示词
        subject_prompts = {
            "chinese": "你是资深语文教研员。请对以下题目做'深度解析 + 分类提议'。特别注意文言文、古诗词、现代文阅读、作文等题型。",
            "english": "你是资深英语教研员。请对以下题目做'深度解析 + 分类提议'。特别注意阅读理解、完形填空、语法填空、写作等题型。",
            "politics": "你是资深政治教研员。请对以下题目做'深度解析 + 分类提议'。特别注意选择题、简答题、论述题等题型。",
        }
        subject_prompt = subject_prompts.get(subject, "你是资深教研员。请对以下题目做'深度解析 + 分类提议'。")

        # 构造 Prompt
        prompt = f"""{subject_prompt}
当前处理第 {i+1} 到 {i+len(batch_slice)} 题（共 {total_items} 题）。

用户选择学科：{subject}
年级：{grade or "未知"}

请输出 JSON：
1) detected_subject ("{subject}"|"other")
2) results：数组，包含每道题的：
   - index: 必须与输入一致
   - question_content (修正OCR错误)
   - explanation (简要思路)
   - error_analysis (简要错因)
   - suggested_questions (3个短句)
   - chapter (从候选选)
   - knowledge_points (从候选选 1~3个)
   - tags (标签)

候选分类：
{json.dumps(taxonomy, ensure_ascii=False)}

题目列表：
{json.dumps(prompt_items, ensure_ascii=False)}

严格输出 JSON:
{{
  "detected_subject": "...",
  "results": [ {{ "index": {prompt_items[0]['index']}, ... }} ]
}}"""

        try:
            parsed = await call_router_llm_json(
                prompt,
                log_ctx=f"{_ctx(state)} batch_{i}",
                trace_id=str(task_id) if task_id else None,
                trace_stage=f"reasoner_batch_{i}",
            )
            
            if parsed:
                if parsed.get("detected_subject"):
                    detected_subjects.append(parsed.get("detected_subject"))
                
                batch_results = _coerce_results_list(parsed, expected_len=len(batch_slice)) or []
                all_results_buffer.extend(batch_results)
            else:
                logger.warning(f"[reasoner_agent] Batch {i} failed to parse JSON, skipping enrichment.")

        except Exception as e:
            logger.error(f"[reasoner_agent] Batch {i} error: {e}")
            continue

    # 合并结果到 base_items
    if not all_results_buffer:
        logger.warning("[reasoner_agent] No valid results from any batch. Returning OCR items as is.")
    else:
        for r in all_results_buffer:
            if not isinstance(r, dict): continue
            idx = r.get("index")
            if idx is None or not isinstance(idx, int): continue
            
            if 0 <= idx < len(base_items):
                target = base_items[idx]
                for key in ["question_content", "student_answer", "correct_answer", 
                            "explanation", "error_analysis", "chapter"]:
                    if r.get(key): 
                        target[key] = str(r[key]).strip()
                
                if r.get("knowledge_points"): target["knowledge_points"] = r["knowledge_points"]
                if r.get("tags"): target["tags"] = r["tags"]
                if r.get("suggested_questions"): target["suggested_questions"] = r["suggested_questions"]

    # 学科一致性检查
    final_detected = subject
    if detected_subjects:
        from collections import Counter
        final_detected = Counter(detected_subjects).most_common(1)[0][0]
        
    if final_detected not in (subject, "other") and len(detected_subjects) == total_items:
        logger.warning(f"[reasoner_agent] Subject mismatch: detected={final_detected}, selected={subject}")

    duration_ms = int((time.perf_counter() - t0) * 1000)
    logger.info(f"[reasoner_agent] {_ctx(state)} done. Updated {len(all_results_buffer)}/{total_items} items. Time={duration_ms}ms")

    # 更新任务状态进度
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
                    "items_processed": len(all_results_buffer),
                    "total_items": total_items
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
    Normalizer Agent - RPJ版本
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

    subject = state.get("subject", "chinese")
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

    max_new_chapters = int(os.getenv("RPJ_MAX_NEW_CHAPTERS_PER_REQUEST") or "2")
    max_new_kps = int(os.getenv("RPJ_MAX_NEW_KPS_PER_REQUEST") or "6")

    # 同义合并
    async def merge_synonyms(kind: str, new_labels: List[str], cand: List[str]) -> Dict[str, str]:
        if not new_labels or not cand:
            return {}
        prompt = f"""你是{subject}教研员。将新标签尽量合并到已有候选（同义/近义/上位类）。

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
                        for i, it in enumerate(normalized_items[: int(os.getenv("RPJ_DEEP_ENRICH_MAX_ITEMS") or "10")])
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
    """
    保存错题节点 - RPJ版本
    """
    t0 = time.perf_counter()
    logger.info(f"[save_question] {_ctx(state)} start")
    
    task_id = state.get("task_id")
    if task_id and task_id in _initial_state_cache:
        initial_state = _initial_state_cache[task_id]
        state = {**initial_state, **state}
        task_id = state.get("task_id")

    from backend.core.db.session import async_session_maker
    from backend.core.crud import crud_task
    from backend.core.db.models import Question, SubjectEnum, DifficultyEnum, QuestionSourceEnum

    user_id = state.get("user_id")
    subject = state.get("subject", "chinese")
    difficulty = state.get("difficulty", "medium")
    grade = state.get("grade", "")

    if not user_id:
        return {
            "errors": ["user_id 缺失，无法保存错题"],
            "success": False,
            "current_step": "save_question",
            "progress": 60.0,
        }

    if isinstance(state.get("errors"), list) and state.get("errors"):
        try:
            async with async_session_maker() as db:
                await crud_task.fail_task(db, task_id, "; ".join(state["errors"]))
                await db.commit()
        except Exception:
            pass
        return {
            "errors": state.get("errors"),
            "success": False,
            "current_step": "save_question",
            "progress": 60.0,
        }

    try:
        async with async_session_maker() as db:
            # 枚举值转换
            try:
                subject_enum = SubjectEnum(subject)
            except ValueError:
                subject_enum = SubjectEnum.OTHER
            
            try:
                difficulty_enum = DifficultyEnum(difficulty)
            except ValueError:
                difficulty_enum = DifficultyEnum.MEDIUM

            # 准备数据列表
            structured_data = state.get("structured_data", {})
            structured_data_list = state.get("structured_data_list")
            items = structured_data_list if isinstance(structured_data_list, list) else [structured_data]

            # 按 order 排序
            try:
                indexed = []
                for i, it in enumerate(items):
                    v = it.get("order") if isinstance(it, dict) else None
                    try:
                        ov = int(v) if v is not None else 10**9
                    except Exception:
                        ov = 10**9
                    indexed.append((ov, i, it))
                items = [it for _, __, it in sorted(indexed, key=lambda x: (x[0], x[1]))]
            except Exception:
                pass

            created_ids: List[int] = []

            # 循环创建题目
            for idx, item in enumerate(items):
                content = (item.get("question_body") or "").strip()
                if not content:
                    content = "题目内容待补充"

                # 元数据
                meta = {}
                try:
                    meta = {
                        "answer_sources": {
                            "student_answer_raw": item.get("student_answer") or "",
                            "teacher_marked_answer": item.get("teacher_marked_answer") or "",
                            "model_inferred_answer": item.get("model_inferred_answer") or "",
                        },
                        "grading": {
                            "decided_by": item.get("grading_basis") or "unknown",
                        }
                    }
                    if state.get("summarized_input"):
                        meta["summary"] = state.get("summarized_input")
                except Exception:
                    pass

                # 创建题目对象
                q = Question(
                    user_id=int(user_id),
                    content=content,
                    student_answer=item.get("student_answer"),
                    correct_answer=item.get("correct_answer") or None,
                    is_correct=item.get("is_correct"),
                    score=item.get("score"),
                    max_score=item.get("max_score"),
                    explanation=item.get("explanation"),
                    subject=subject_enum,
                    grade=grade,
                    difficulty=difficulty_enum,
                    knowledge_points=item.get("knowledge_points", []),
                    error_analysis=item.get("error_analysis"),
                    suggested_questions=item.get("suggested_questions") or [],
                    chapter=item.get("chapter") or None,
                    tags=item.get("tags") or [],
                    source=QuestionSourceEnum.MANUAL,
                    source_description="录入错题功能",
                    upload_group_id=task_id,
                    upload_index=int(idx + 1),
                    summarized_input=json.dumps(meta, ensure_ascii=False) if meta else None
                )

                # 图片关联
                if state.get("input_type") == "image" and state.get("image_path"):
                    q.image_urls = [state.get("image_path")]
                    if state.get("source_image_id"):
                        q.source_image_id = int(state.get("source_image_id"))
                
                if state.get("original_input"):
                    q.original_input = state.get("original_input")

                db.add(q)
                await db.flush()
                
                created_ids.append(q.id)
                logger.info(f"[save_question] Flushed question {idx+1}/{len(items)}, ID={q.id}")

            # 更新任务状态
            if created_ids:
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
            logger.info(f"[save_question] {_ctx(state)} success ids={created_ids} duration={duration_ms}ms")

            return {
                "question_id": created_ids[0] if created_ids else None,
                "question_ids": created_ids,
                "created_count": len(created_ids),
                "success": True,
                "current_step": "save_question",
                "progress": 100.0,
            }

    except Exception as e:
        duration_ms = int((time.perf_counter() - t0) * 1000)
        logger.error(f"[save_question] {_ctx(state)} error: {e}", exc_info=True)
        return {
            "errors": [f"保存错题失败: {str(e)}"],
            "success": False,
            "current_step": "save_question",
            "progress": 60.0,
        }