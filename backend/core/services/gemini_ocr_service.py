"""
Gemini OCR Service - 智能试卷分析与批改服务

功能:
1. gemini-2.5-flash + thinking_config(16384):
   - 试卷照片 → 提取「题目 + 学生解答」
   - 自动纠错 + 解析 + 打分 (JSON 结构化输出)

2. gemini-2.5-flash (image generation):
   - 根据解析生成「黑板讲解图」
   - 在原卷面上进行「红笔批改、写评语」的图像编辑

实现方式:
- 通过统一的 LLM API 端点访问 Gemini 模型
- 使用 httpx 进行 HTTP 请求
- 支持多模态输入（文本 + 图像）
"""

import os
import json
import base64
import logging
import importlib
from typing import List, Optional, Dict, Any
from functools import lru_cache
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import httpx
import asyncio
import random
import time

from ..base_config import get_base_settings
from .llm_utils import get_llm_semaphore, parse_retry_after_seconds, compute_backoff_delay_seconds
from .llm_trace import write_llm_trace

settings = get_base_settings()

logger = logging.getLogger(__name__)


@lru_cache()
def _get_gemini_prompt_provider(module_name: str):
    """
    获取 Prompt Provider（按模块可插拔）。

    说明：
    - 该 Provider 负责“prompt构建 + 模块化日志/模型配置”等可拆分部分；
    - `GeminiOCRService` 保持公共：HTTP 调用、重试、JSON 解析、结果数据结构等不变。
    - 当前只在 tony 模块落地完整实现；其他模块可提供同名模块并逐步替换（先透传到 tony）。
    """
    candidates = []
    mod = (module_name or "").strip()
    if mod:
        candidates.append(f"backend.modules.{mod}.services.gemini_ocr_prompts")
    # Fallback: use Tony as the reference implementation
    candidates.append("backend.modules.tony.services.gemini_ocr_prompts")

    for dotted in candidates:
        try:
            return importlib.import_module(dotted)
        except ModuleNotFoundError:
            continue
        except Exception as e:  # pragma: no cover
            logger.warning(f"Failed to load gemini_ocr prompt provider '{dotted}': {type(e).__name__}: {e}")

    # Ultra-safe fallback provider: keep service callable even if provider missing.
    class _FallbackProvider:
        @staticmethod
        def get_subject_prompt(subject: str) -> str:
            return "你是一位经验丰富的老师。"

        @staticmethod
        def is_intake_mode(trace_stage: str, user_hint: Optional[str]) -> bool:
            return False

        @staticmethod
        def build_exam_analysis_prompt(*, subject: str, grade: str, user_hint: Optional[str], intake_mode: bool) -> str:
            # Minimal generic prompt; modules should override with proper prompts.
            return f"请对图片进行OCR识别并输出JSON，subject={subject}, grade={grade}。"

        @staticmethod
        def build_compact_retry_prompt(*, subject: str, grade: str, user_hint: Optional[str]) -> str:
            return f"请只输出 JSON（不要 code block），subject={subject}, grade={grade}。"

        @staticmethod
        def resolve_ocr_model(*, default_model: str) -> str:
            return os.getenv("OCR_VISION_MODEL") or default_model

        @staticmethod
        def resolve_temperature(*, intake_mode: bool) -> float:
            return float(os.getenv("OCR_TEMPERATURE") or "0.3")

        @staticmethod
        def resolve_max_tokens() -> int:
            return int(os.getenv("OCR_MAX_TOKENS") or "8192")

        @staticmethod
        def get_logging_config() -> Dict[str, Any]:
            return {
                "log_prompt": False,
                "log_response": False,
                "prompt_limit": 12000,
                "resp_limit": 12000,
            }

    return _FallbackProvider()

# 中文学科名称到英文的映射
SUBJECT_NAME_MAP = {
    "数学": "math",
    "英语": "english",
    "物理": "physics",
    "化学": "chemistry",
    "语文": "chinese",
    "生物": "biology",
    "政治": "politics",
    "经济学": "economics",
    "历史": "history",
    "地理": "geography",
    "其他": "other",
}

class SubjectType(str, Enum):
    """学科类型"""
    MATH = "math"
    ENGLISH = "english"
    PHYSICS = "physics"
    CHEMISTRY = "chemistry"
    CHINESE = "chinese"
    BIOLOGY = "biology"
    POLITICS = "politics"
    ECONOMICS = "economics"
    HISTORY = "history"
    GEOGRAPHY = "geography"
    OTHER = "other"

def parse_subject_type(subject: str) -> SubjectType:
    """
    解析学科类型，支持中文和英文输入

    Args:
        subject: 学科名称（中文或英文）

    Returns:
        SubjectType 枚举值
    """
    if not subject:
        return SubjectType.OTHER

    # 先尝试中文映射
    subject_en = SUBJECT_NAME_MAP.get(subject, subject.lower())

    # 然后尝试枚举解析
    try:
        return SubjectType(subject_en)
    except ValueError:
        return SubjectType.OTHER

@dataclass
class QuestionItem:
    """单道题目解析结果"""
    question_number: int
    question_type: str  # 选择题, 填空题, 解答题
    question_text: str
    student_answer: str
    # Raw student answer as seen on paper (may include crossed-out text, blanks, etc.)
    student_answer_raw: Optional[str] = None
    # Teacher-marked / student self-marked correct answer (if visible on paper)
    teacher_marked_answer: Optional[str] = None
    # Teacher marking (visual) correctness signal, derived from ticks/crosses on the paper.
    # If there is a colored tick (√/✓/✔/对) near this question/option, set True.
    # If there is a colored cross (×/✗/✘/错) near this question/option, set False.
    # If not visible/unclear, set None.
    teacher_marked_is_correct: Optional[bool] = None
    teacher_marked_mark: Optional[str] = None  # "tick" | "cross" | "none" | None
    teacher_marked_color: Optional[str] = None  # "red" | "blue" | "black" | "unknown" | None
    teacher_marked_evidence: Optional[str] = None  # short note like "红色√在B选项旁"
    # Model-inferred correct answer (computed from the question content)
    model_inferred_answer: Optional[str] = None
    correct_answer: Optional[str] = None
    score: float = 0.0
    max_score: float = 0.0
    is_correct: bool = False
    error_analysis: str = ""
    knowledge_points: List[str] = field(default_factory=list)
    solution_steps: List[str] = field(default_factory=list)
    difficulty: str = "medium"

@dataclass
class ExamAnalysisResult:
    """试卷分析结果"""
    subject: SubjectType
    grade: str
    total_score: float
    max_score: float
    accuracy_rate: float
    questions: List[QuestionItem]
    overall_analysis: str
    weak_points: List[str]
    improvement_suggestions: List[str]
    raw_response: Optional[str] = None

@dataclass
class CorrectionImageResult:
    """批改图像结果"""
    original_image_path: str
    corrected_image_base64: Optional[str] = None
    correction_notes: List[str] = field(default_factory=list)
    success: bool = False
    error_message: str = ""

class GeminiOCRService:
    """
    Gemini OCR 服务

    使用 Gemini 2.5 Flash 模型进行:
    1. 试卷图片 OCR + 结构化解析
    2. 自动批改 + 打分
    3. 生成讲解图 (黑板风格)
    4. 红笔批改效果
    """

    def __init__(self):
        self._http_client: Optional[httpx.AsyncClient] = None
        self._initialized = False
        self._api_endpoint = settings.LLM_API_ENDPOINT
        self._api_key = settings.LLM_API_KEY

    async def initialize(self) -> bool:
        """初始化 HTTP 客户端"""
        if self._initialized:
            return True

        try:
            if not self._api_endpoint:
                logger.error("LLM_API_ENDPOINT not configured")
                return False

            if not self._api_key:
                logger.error("LLM_API_KEY not configured")
                return False

            # 创建 HTTP 客户端
            self._http_client = httpx.AsyncClient(
                base_url=self._api_endpoint,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                timeout=120.0,
            )

            self._initialized = True
            logger.info(f"Gemini OCR service initialized with endpoint: {self._api_endpoint}")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize Gemini OCR service: {e}")
            return False

    async def close(self):
        """关闭 HTTP 客户端"""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
            self._initialized = False

    def _load_image_as_base64(self, image_path: str) -> Optional[str]:
        """将图片文件转换为 base64"""
        try:
            with open(image_path, 'rb') as f:
                return base64.b64encode(f.read()).decode('utf-8')
        except Exception as e:
            logger.error(f"Failed to load image: {e}")
            return None

    def _get_subject_prompt(self, subject: SubjectType) -> str:
        """
        获取学科专用的分析提示（可插拔）。

        说明：
        - prompt 文案已拆分到各模块的 `services/gemini_ocr_prompts.py` 中（当前以 tony 为准）。
        - 核心服务仅保留公共逻辑，不在此处维护具体学科 prompt 文案。
        """
        provider = _get_gemini_prompt_provider(getattr(settings, "MODULE_NAME", "tony"))
        try:
            return provider.get_subject_prompt(str(subject.value))
        except Exception:
            return "你是一位经验丰富的老师。"

    async def analyze_exam_image(
        self,
        image_path: str,
        subject: SubjectType = SubjectType.OTHER,
        grade: str = "",
        user_hint: Optional[str] = None,
        trace_id: Optional[str] = None,
        trace_stage: str = "ocr_vision",
    ) -> ExamAnalysisResult:
        """
        分析试卷图片

        使用 gemini-2.5-flash + thinking_config 进行深度分析:
        1. OCR 提取题目和学生解答
        2. 自动纠错
        3. 详细解析
        4. 打分

        Args:
            image_path: 图片路径
            subject: 学科类型
            grade: 年级
            user_hint: 用户提供的额外提示

        Returns:
            ExamAnalysisResult: 结构化分析结果
        """
        if not self._initialized:
            await self.initialize()

        try:
            # 加载图片
            image_data = self._load_image_as_base64(image_path)
            if not image_data:
                return self._create_error_result("无法加载图片")

            # 检测图片类型
            image_ext = Path(image_path).suffix.lower()
            mime_types = {
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.png': 'image/png',
                '.gif': 'image/gif',
                '.webp': 'image/webp',
            }
            mime_type = mime_types.get(image_ext, 'image/jpeg')

            provider = _get_gemini_prompt_provider(getattr(settings, "MODULE_NAME", "tony"))

            # 模块可插拔：intake_mode 识别规则放到模块 provider（当前以 tony 为准）
            try:
                intake_mode = bool(provider.is_intake_mode(str(trace_stage or ""), user_hint))
            except Exception:
                intake_mode = False

            # 模块可插拔：prompt 文案与结构（按学科/场景拆分到模块侧）
            prompt = provider.build_exam_analysis_prompt(
                subject=str(subject.value),
                grade=str(grade or ""),
                user_hint=user_hint,
                intake_mode=bool(intake_mode),
            )

            # 构建 API 请求（OpenAI Vision API 格式）
            ocr_model = provider.resolve_ocr_model(default_model=settings.GEMINI_MODEL)
            temperature = float(provider.resolve_temperature(intake_mode=bool(intake_mode)))
            max_tokens = int(provider.resolve_max_tokens())
            request_data = {
                "model": ocr_model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_data}"}},
                        ],
                    }
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
            }

            # 模块可插拔：日志配置（env var / 默认值等）
            log_cfg = provider.get_logging_config()
            log_prompt = bool(log_cfg.get("log_prompt", False))
            log_response = bool(log_cfg.get("log_response", False))
            prompt_limit = int(log_cfg.get("prompt_limit", 12000))
            resp_limit = int(log_cfg.get("resp_limit", 12000))

            # 构建 API 请求（OpenAI Vision API 格式）
            # OCR/图像识别模型：允许按环境变量覆盖（便于区分“快 OCR 多模态模型”与“强文本推理模型”）
            ocr_model = (
                os.getenv("OCR_VISION_MODEL")
                or os.getenv("TONY_OCR_VISION_MODEL")
                or settings.GEMINI_MODEL
            )
            request_data = {
                "model": ocr_model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": prompt
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{mime_type};base64,{image_data}"
                                }
                            }
                        ]
                    }
                ],
                # 录入错题场景：把 temperature 调低，显著降低“胡猜/不稳定”导致的字段错配
                "temperature": float(os.getenv("OCR_INTAKE_TEMPERATURE") or os.getenv("OCR_TEMPERATURE") or "0.1") if intake_mode else float(os.getenv("OCR_TEMPERATURE") or "0.3"),
                "max_tokens": int(os.getenv("OCR_MAX_TOKENS") or "8192"),
            }

            # Extra debugging logs (no base64): prompt + image path.
            log_prompt = str(os.getenv("TONY_LLM_LOG_PROMPT", "true")).lower() in ("1", "true", "yes", "y", "on")
            log_response = str(os.getenv("TONY_LLM_LOG_RESPONSE", "true")).lower() in ("1", "true", "yes", "y", "on")
            prompt_limit = int(os.getenv("TONY_LLM_LOG_PROMPT_CHARS") or "12000")
            resp_limit = int(os.getenv("TONY_LLM_LOG_RESPONSE_CHARS") or "12000")

            if log_prompt:
                logger.info(
                    f"[llm_ocr] trace_id={trace_id or '-'} stage={trace_stage} model={ocr_model} "
                    f"image_path={image_path} image_b64_len={len(image_data) if image_data else 0} "
                    f"prompt_len={len(prompt)} prompt={prompt[:prompt_limit]}"
                )

            # Tony-only: persist FULL request payload (includes base64) for debugging.
            if trace_id:
                req_trace_path = write_llm_trace(
                    trace_id=str(trace_id),
                    stage=str(trace_stage or "ocr_vision"),
                    kind="request",
                    payload={
                        "endpoint": f"{self._api_endpoint}/chat/completions",
                        "request": request_data,
                    },
                    suffix="json",
                    # Don't print the request by default (may include huge base64).
                    also_log_full=False,
                    log_prefix=f"trace_id={trace_id} ",
                )
                if req_trace_path:
                    logger.info(f"[llm_ocr] trace_id={trace_id} request_trace_file={req_trace_path}")

            # 调用 API（对 503/5xx/429 做短重试，提升可用性）
            logger.info(f"Sending request to {self._api_endpoint}/chat/completions")
            max_attempts = int(os.getenv("LLM_RETRY_MAX_ATTEMPTS") or getattr(settings, "LLM_RETRY_MAX_ATTEMPTS", 3) or 3)
            base_delay = float(os.getenv("LLM_RETRY_BASE_DELAY_SECONDS") or getattr(settings, "LLM_RETRY_BASE_DELAY_SECONDS", 0.6) or 0.6)
            max_delay = float(os.getenv("LLM_RETRY_MAX_DELAY_SECONDS") or getattr(settings, "LLM_RETRY_MAX_DELAY_SECONDS", 30.0) or 30.0)
            response = None
            last_exc: Optional[Exception] = None
            t_req0 = time.perf_counter()
            for attempt in range(max_attempts):
                try:
                    async with get_llm_semaphore():
                        response = await self._http_client.post(
                            "/chat/completions",
                            json=request_data,
                        )
                    if trace_id:
                        # Save FULL response payload for each attempt (even on 429/5xx)
                        try:
                            resp_text = response.text
                        except Exception:
                            resp_text = None
                        write_llm_trace(
                            trace_id=str(trace_id),
                            stage=str(trace_stage or "ocr_vision"),
                            kind=f"response_attempt_{attempt+1}_http_{response.status_code}",
                            payload={
                                "status_code": response.status_code,
                                "headers": dict(response.headers),
                                "text": resp_text,
                            },
                            suffix="json",
                            # response may still be big but usually manageable; keep print gated by env.
                            also_log_full=None,
                            log_prefix=f"trace_id={trace_id} ",
                        )
                    if response.status_code in (429, 500, 502, 503, 504) and attempt < max_attempts - 1:
                        retry_after_s = parse_retry_after_seconds(response.headers.get("retry-after"))
                        delay = compute_backoff_delay_seconds(
                            attempt=attempt,
                            base_delay=base_delay,
                            max_delay=max_delay,
                            retry_after_s=retry_after_s,
                            jitter=0.2,
                        )
                        logger.warning(
                            f"Retryable HTTP {response.status_code} from LLM endpoint; "
                            f"model={ocr_model}, attempt={attempt+1}/{max_attempts}, "
                            f"retry_after={retry_after_s if retry_after_s is not None else 'n/a'}s, sleep={delay:.2f}s"
                        )
                        await asyncio.sleep(delay)
                        continue
                    response.raise_for_status()
                    break
                except (httpx.TimeoutException, httpx.NetworkError, httpx.TransportError) as e:
                    last_exc = e
                    logger.warning(
                        f"[llm_ocr] trace_id={trace_id or '-'} stage={trace_stage} model={ocr_model} "
                        f"image_path={image_path} attempt={attempt+1}/{max_attempts} err={type(e).__name__}: {e}"
                    )
                    if trace_id:
                        write_llm_trace(
                            trace_id=str(trace_id),
                            stage=str(trace_stage or "ocr_vision"),
                            kind=f"exception_attempt_{attempt+1}",
                            payload={
                                "type": type(e).__name__,
                                "message": str(e),
                            },
                            suffix="json",
                            also_log_full=None,
                            log_prefix=f"trace_id={trace_id} ",
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
                            f"Network error talking to LLM endpoint; attempt={attempt+1}/{max_attempts}, "
                            f"sleep={delay:.2f}s, err={type(e).__name__}"
                        )
                        await asyncio.sleep(delay)
                        continue
                    raise
                except httpx.HTTPStatusError as e:
                    last_exc = e
                    raise

            if response is None:
                raise last_exc or RuntimeError("LLM response missing")

            elapsed_ms = int((time.perf_counter() - t_req0) * 1000)
            logger.info(
                f"LLM chat/completions OK model={ocr_model} subject={subject.value} "
                f"attempts_used<= {max_attempts} image_b64_len={len(image_data) if image_data else 0} duration_ms={elapsed_ms}"
            )
            response_data = response.json()
            finish_reason = None
            try:
                finish_reason = response_data.get("choices", [{}])[0].get("finish_reason")
            except Exception:
                finish_reason = None

            # 提取响应文本
            if "choices" not in response_data or not response_data["choices"]:
                return self._create_error_result("API 返回格式错误", str(response_data))

            response_text = response_data["choices"][0]["message"]["content"]
            logger.debug(f"Gemini response: {response_text[:500]}...")

            if log_response:
                logger.info(
                    f"[llm_ocr] trace_id={trace_id or '-'} stage={trace_stage} model={ocr_model} "
                    f"response_len={len(response_text or '')} response={response_text[:resp_limit]}"
                )

            if trace_id:
                # Save FULL parsed payload and extracted text (Tony-only)
                write_llm_trace(
                    trace_id=str(trace_id),
                    stage=str(trace_stage or "ocr_vision"),
                    kind="parsed_response",
                    payload={
                        "response_json": response_data,
                        "extracted_content": response_text,
                    },
                    suffix="json",
                    also_log_full=None,
                    log_prefix=f"trace_id={trace_id} ",
                )

            # 提取 JSON
            result_data = self._extract_json(response_text)
            if not result_data:
                # If the model output was truncated, retry once with a compact schema to avoid truncation.
                if str(finish_reason or "").lower() == "length":
                    logger.warning(
                        f"[llm_ocr] trace_id={trace_id or '-'} stage={trace_stage} model={ocr_model} "
                        f"finish_reason=length; retrying with compact schema"
                    )
                    retry_prompt = (
                        prompt
                        if intake_mode
                        else provider.build_compact_retry_prompt(
                            subject=str(subject.value),
                            grade=str(grade or ""),
                            user_hint=user_hint,
                        )
                    )
                    request_data_retry = {
                        **request_data,
                        "messages": [
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": retry_prompt},
                                    {
                                        "type": "image_url",
                                        "image_url": {"url": f"data:{mime_type};base64,{image_data}"},
                                    },
                                ],
                            }
                        ],
                        "temperature": 0.1,
                    }
                    async with get_llm_semaphore():
                        resp2 = await self._http_client.post("/chat/completions", json=request_data_retry)
                    resp2.raise_for_status()
                    resp2_data = resp2.json()
                    try:
                        response_text = resp2_data["choices"][0]["message"]["content"]
                    except Exception:
                        response_text = None
                    if response_text:
                        result_data = self._extract_json(response_text)

                if not result_data:
                    return self._create_error_result("无法解析分析结果", response_text)

            # 构建结果
            def _coerce_questions_list(obj: Any) -> List[Dict[str, Any]]:
                if obj is None:
                    return []
                if isinstance(obj, list):
                    return [x for x in obj if isinstance(x, dict)]
                if isinstance(obj, dict):
                    # Dict keyed by index -> values list
                    out = [v for v in obj.values() if isinstance(v, dict)]
                    return out
                if isinstance(obj, str):
                    s = obj.strip()
                    if not s:
                        return []
                    try:
                        j = json.loads(s)
                    except Exception:
                        return []
                    return _coerce_questions_list(j)
                return []

            raw_questions = (
                result_data.get("questions")
                or result_data.get("questions_detail")
                or result_data.get("items")
                or result_data.get("data")
            )
            q_list = _coerce_questions_list(raw_questions)

            # Another common truncation case: JSON partially parses, but only the first question survives.
            if str(finish_reason or "").lower() == "length" and len(q_list) <= 1:
                logger.warning(
                    f"[llm_ocr] trace_id={trace_id or '-'} stage={trace_stage} model={ocr_model} "
                    f"finish_reason=length and questions<=1; retrying with compact schema"
                )
                retry_prompt = (
                    prompt
                    if intake_mode
                    else provider.build_compact_retry_prompt(
                        subject=str(subject.value),
                        grade=str(grade or ""),
                        user_hint=user_hint,
                    )
                )
                request_data_retry = {
                    **request_data,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": retry_prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:{mime_type};base64,{image_data}"},
                                },
                            ],
                        }
                    ],
                    "temperature": 0.1,
                }
                async with get_llm_semaphore():
                    resp2 = await self._http_client.post("/chat/completions", json=request_data_retry)
                resp2.raise_for_status()
                resp2_data = resp2.json()
                try:
                    response_text = resp2_data["choices"][0]["message"]["content"]
                except Exception:
                    response_text = None
                if response_text:
                    result_data = self._extract_json(response_text) or result_data
                    raw_questions = (
                        result_data.get("questions")
                        or result_data.get("questions_detail")
                        or result_data.get("items")
                        or result_data.get("data")
                    )
                    q_list = _coerce_questions_list(raw_questions)

            questions: List[QuestionItem] = []
            for q in q_list:
                # tolerate alternative key names
                qn = q.get("question_number", q.get("number", q.get("index", 0)))
                qt = q.get("question_type", q.get("type", ""))
                qtext = q.get("question_text", q.get("question_content", q.get("content", q.get("question", ""))))
                sa_raw = q.get("student_answer_raw", q.get("student_answer", q.get("answer", "")))
                sa = q.get("student_answer", q.get("answer", sa_raw))
                teacher = q.get("teacher_marked_answer", q.get("marked_correct_answer", q.get("teacher_answer")))
                tm_ic = q.get("teacher_marked_is_correct", q.get("teacher_marked_correct"))
                tm_mark = q.get("teacher_marked_mark", q.get("teacher_mark"))
                tm_color = q.get("teacher_marked_color", q.get("mark_color"))
                tm_evi = q.get("teacher_marked_evidence", q.get("mark_evidence"))
                model_ans = q.get("model_inferred_answer", q.get("model_answer", q.get("inferred_answer")))
                ca = q.get(
                    "correct_answer",
                    q.get("correct", q.get("reference_answer", teacher or model_ans)),
                )
                kps = q.get("knowledge_points", q.get("knowledge_point", []))
                if isinstance(kps, str):
                    kps = [x.strip() for x in kps.split(",") if x.strip()]
                if not isinstance(kps, list):
                    kps = []
                # Coerce teacher_marked_is_correct
                if tm_ic is None:
                    tm_ic_b = None
                elif isinstance(tm_ic, bool):
                    tm_ic_b = tm_ic
                elif isinstance(tm_ic, (int, float)):
                    tm_ic_b = bool(int(tm_ic))
                elif isinstance(tm_ic, str):
                    s = tm_ic.strip().lower()
                    if s in ("true", "t", "1", "yes", "y", "right", "correct"):
                        tm_ic_b = True
                    elif s in ("false", "f", "0", "no", "n", "wrong", "incorrect"):
                        tm_ic_b = False
                    else:
                        tm_ic_b = None
                else:
                    tm_ic_b = None

                questions.append(
                    QuestionItem(
                        question_number=qn or 0,
                        question_type=qt or "",
                        question_text=qtext or "",
                        student_answer=sa or "",
                        student_answer_raw=sa_raw or "",
                        teacher_marked_answer=(teacher if isinstance(teacher, str) and teacher.strip() else None),
                        teacher_marked_is_correct=tm_ic_b,
                        teacher_marked_mark=(tm_mark if isinstance(tm_mark, str) and tm_mark.strip() else None),
                        teacher_marked_color=(tm_color if isinstance(tm_color, str) and tm_color.strip() else None),
                        teacher_marked_evidence=(tm_evi if isinstance(tm_evi, str) and tm_evi.strip() else None),
                        model_inferred_answer=(model_ans if isinstance(model_ans, str) and model_ans.strip() else None),
                        correct_answer=ca,
                        score=q.get("score", 0),
                        max_score=q.get("max_score", 0),
                        is_correct=bool(q.get("is_correct", False)),
                        error_analysis=q.get("error_analysis", ""),
                        knowledge_points=kps,
                        solution_steps=q.get("solution_steps", []),
                        difficulty=q.get("difficulty", "medium"),
                    )
                )

            # 始终使用用户传入的学科类型，不使用模型推断的
            # 这样可以确保入库的学科与用户选择的学科一致
            parsed_subject = subject
            logger.info(f"Using user-provided subject: {parsed_subject.value}")

            return ExamAnalysisResult(
                subject=parsed_subject,
                grade=result_data.get('grade', grade),
                total_score=result_data.get('total_score', 0),
                max_score=result_data.get('max_score', 0),
                accuracy_rate=result_data.get('accuracy_rate', 0),
                questions=questions,
                overall_analysis=result_data.get('overall_analysis', ''),
                weak_points=result_data.get('weak_points', []),
                improvement_suggestions=result_data.get('improvement_suggestions', []),
                raw_response=response_text,
            )

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error during exam analysis: {e.response.status_code} - {e.response.text}")
            code = e.response.status_code
            if code in (429, 500, 502, 503, 504):
                return self._create_error_result(f"模型服务暂时不可用（HTTP {code}），请稍后重试")
            return self._create_error_result(f"API 请求失败: {code}")
        except Exception as e:
            logger.error(f"Exam analysis error: {e}")
            return self._create_error_result(str(e))

    async def _analyze_image(
        self,
        *,
        image_path: str,
        prompt: str,
        model: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> str:
        """
        Backward-compatible low-level image+prompt call used by other modules (wzy/wzm/xmx/old tony endpoints).

        Returns:
            Raw model text (string). Callers may parse JSON from it.
        """
        if not self._initialized:
            await self.initialize()

        image_data = self._load_image_as_base64(image_path)
        if not image_data:
            raise RuntimeError("无法加载图片")

        image_ext = Path(image_path).suffix.lower()
        mime_types = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }
        mime_type = mime_types.get(image_ext, "image/jpeg")

        used_model = model or os.getenv("OCR_VISION_MODEL") or os.getenv("TONY_OCR_VISION_MODEL") or settings.GEMINI_MODEL
        request_data = {
            "model": used_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime_type};base64,{image_data}"},
                        },
                    ],
                }
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        max_attempts = int(os.getenv("LLM_RETRY_MAX_ATTEMPTS") or getattr(settings, "LLM_RETRY_MAX_ATTEMPTS", 3) or 3)
        base_delay = float(os.getenv("LLM_RETRY_BASE_DELAY_SECONDS") or getattr(settings, "LLM_RETRY_BASE_DELAY_SECONDS", 0.6) or 0.6)
        max_delay = float(os.getenv("LLM_RETRY_MAX_DELAY_SECONDS") or getattr(settings, "LLM_RETRY_MAX_DELAY_SECONDS", 30.0) or 30.0)

        resp: Optional[httpx.Response] = None
        last_exc: Optional[Exception] = None
        for attempt in range(max_attempts):
            try:
                async with get_llm_semaphore():
                    resp = await self._http_client.post("/chat/completions", json=request_data)
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
                        f"Retryable HTTP {resp.status_code} from LLM endpoint; "
                        f"model={used_model}, attempt={attempt+1}/{max_attempts}, "
                        f"retry_after={retry_after_s if retry_after_s is not None else 'n/a'}s, sleep={delay:.2f}s"
                    )
                    await asyncio.sleep(delay)
                    continue
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]
            except (httpx.TimeoutException, httpx.NetworkError, httpx.TransportError) as e:
                last_exc = e
                if attempt < max_attempts - 1:
                    delay = compute_backoff_delay_seconds(
                        attempt=attempt,
                        base_delay=base_delay,
                        max_delay=max_delay,
                        retry_after_s=None,
                        jitter=0.2,
                    )
                    logger.warning(
                        f"Network error talking to LLM endpoint; attempt={attempt+1}/{max_attempts}, "
                        f"sleep={delay:.2f}s, err={type(e).__name__}"
                    )
                    await asyncio.sleep(delay)
                    continue
                raise
            except Exception as e:
                last_exc = e
                break
        raise last_exc or RuntimeError("LLM call failed")

    async def generate_explanation_image(
        self,
        question: QuestionItem,
        style: str = "blackboard",
    ) -> Optional[str]:
        """
        生成讲解图

        使用 Gemini 图像生成能力创建黑板风格的讲解图

        Args:
            question: 题目信息
            style: 图像风格 (blackboard, whiteboard, notebook)

        Returns:
            base64 编码的图像数据
        """
        if not self._initialized:
            await self.initialize()

        try:
            style_prompts = {
                "blackboard": "Create a blackboard-style educational illustration with chalk writing",
                "whiteboard": "Create a whiteboard-style educational diagram with marker writing",
                "notebook": "Create a notebook-style handwritten explanation",
            }

            prompt = f"""
{style_prompts.get(style, style_prompts['blackboard'])}

题目: {question.question_text}

正确答案: {question.correct_answer}

解题步骤:
{chr(10).join(f'{i+1}. {step}' for i, step in enumerate(question.solution_steps))}

知识点: {', '.join(question.knowledge_points)}

请生成一张清晰、美观的讲解图，包含:
1. 题目简述
2. 关键解题步骤
3. 重要公式或概念
4. 答案标注

风格要求: 教学用途，清晰易懂，适合学生理解
"""

            # Note: Gemini 2.5 Flash 主要用于理解，图像生成能力有限
            # 这里提供一个框架，实际应用中可能需要结合其他服务
            logger.info("Explanation image generation requested (placeholder)")

            return None  # 返回 None 表示功能待实现

        except Exception as e:
            logger.error(f"Failed to generate explanation image: {e}")
            return None

    def _wrap_text(self, text: str, font: "ImageFont.FreeTypeFont", max_width: int) -> List[str]:
        """
        将文本按最大宽度换行

        Args:
            text: 要换行的文本
            font: 字体对象
            max_width: 最大宽度（像素）

        Returns:
            换行后的文本列表
        """
        from PIL import Image, ImageDraw

        # 创建一个临时图像用于测量文字宽度
        temp_img = Image.new('RGB', (100, 100))
        temp_draw = ImageDraw.Draw(temp_img)

        words = []
        current_line = ""

        # 按字符分割（支持中文）
        for char in text:
            # 测试添加当前字符后的宽度
            test_line = current_line + char
            bbox = temp_draw.textbbox((0, 0), test_line, font=font)
            text_width = bbox[2] - bbox[0]

            if text_width <= max_width:
                current_line = test_line
            else:
                # 当前行已满，开始新行
                if current_line:
                    words.append(current_line)
                current_line = char

        # 添加最后一行
        if current_line:
            words.append(current_line)

        return words if words else [text]

    def _load_chinese_font(self, size: int = 24) -> "ImageFont.FreeTypeFont":
        """
        加载支持中文的字体

        尝试多个系统字体路径，确保中文正确显示
        支持通过 FONT_PATH 环境变量指定字体路径
        """
        from PIL import ImageFont
        import subprocess

        # 1. 优先使用环境变量指定的字体路径
        font_path_env = os.getenv('FONT_PATH') or os.getenv('CHINESE_FONT_PATH')
        if font_path_env:
            try:
                font = ImageFont.truetype(font_path_env, size)
                logger.info(f"Loaded font from FONT_PATH: {font_path_env}")
                return font
            except Exception as e:
                logger.warning(f"Failed to load font from FONT_PATH {font_path_env}: {e}")

        # 2. 尝试使用 fontconfig 查找中文字体（Linux系统）
        try:
            # 查找支持中文的字体
            result = subprocess.run(
                ['fc-list', ':lang=zh', 'family'],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0 and result.stdout:
                # 提取字体名称
                font_names = set()
                for line in result.stdout.strip().split('\n'):
                    if line.strip():
                        font_names.add(line.strip().split(',')[0])

                # 尝试通过字体名称查找字体文件
                for font_name in font_names:
                    try:
                        result_path = subprocess.run(
                            ['fc-match', '-f', '%{file}', font_name],
                            capture_output=True,
                            text=True,
                            timeout=2
                        )
                        if result_path.returncode == 0 and result_path.stdout.strip():
                            font_file = result_path.stdout.strip()
                            if os.path.exists(font_file):
                                font = ImageFont.truetype(font_file, size)
                                logger.info(f"Loaded font via fontconfig: {font_file} (name: {font_name})")
                                return font
                    except Exception:
                        continue
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
            logger.debug(f"fontconfig not available or failed: {e}")

        # 3. 按优先级尝试不同操作系统的中文字体路径
        font_paths = [
            # macOS
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/STHeiti Medium.ttc",
            "/System/Library/Fonts/Hiragino Sans GB.ttc",
            "/Library/Fonts/Arial Unicode.ttf",
            # Linux - 常见中文字体路径
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/truetype/noto-cjk/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/TTF/wqy-microhei.ttc",
            "/usr/share/fonts/TTF/wqy-zenhei.ttc",
            # CentOS/RHEL
            "/usr/share/fonts/wqy-microhei/wqy-microhei.ttc",
            "/usr/share/fonts/wqy-zenhei/wqy-zenhei.ttc",
            # Windows
            "C:\\Windows\\Fonts\\simhei.ttf",
            "C:\\Windows\\Fonts\\msyh.ttc",
            "C:\\Windows\\Fonts\\msyhbd.ttc",
            "C:\\Windows\\Fonts\\simsun.ttc",
            "C:\\Windows\\Fonts\\simkai.ttf",
        ]

        for font_path in font_paths:
            try:
                if os.path.exists(font_path):
                    font = ImageFont.truetype(font_path, size)
                    logger.info(f"Loaded font: {font_path}")
                    return font
            except Exception as e:
                logger.debug(f"Failed to load font {font_path}: {e}")
                continue

        # 4. 如果所有字体都失败，记录严重警告
        logger.error(
            "Failed to load any Chinese font. Chinese text will display as boxes or squares. "
            "Please install a Chinese font package:\n"
            "  Ubuntu/Debian: sudo apt-get install fonts-wqy-microhei fonts-wqy-zenhei\n"
            "  CentOS/RHEL: sudo yum install wqy-microhei-fonts wqy-zenhei-fonts\n"
            "  Or set FONT_PATH environment variable to point to a Chinese font file."
        )
        return ImageFont.load_default()

    async def create_correction_overlay(
        self,
        image_path: str,
        analysis_result: ExamAnalysisResult,
        correction_style: str = "red_pen",
    ) -> CorrectionImageResult:
        """
        在原试卷上添加批改效果

        模拟「红笔批改」效果，在原图上添加:
        - 对勾/叉号
        - 分数标注
        - 评语

        Args:
            image_path: 原始试卷图片路径
            analysis_result: 分析结果
            correction_style: 批改风格 (red_pen, blue_pen, stamp)

        Returns:
            CorrectionImageResult: 包含批改后的图像
        """
        try:
            from PIL import Image, ImageDraw

            # 加载原图
            img = Image.open(image_path)
            draw = ImageDraw.Draw(img)

            # 加载中文字体
            font = self._load_chinese_font(size=24)
            small_font = self._load_chinese_font(size=16)

            # 颜色设置
            colors = {
                "red_pen": "#FF0000",
                "blue_pen": "#0000FF",
                "stamp": "#8B0000",
            }
            color = colors.get(correction_style, "#FF0000")

            correction_notes = []

            # 添加总分
            total_text = f"总分: {analysis_result.total_score}/{analysis_result.max_score}"
            # 确保文本是 Unicode 字符串
            if isinstance(total_text, bytes):
                total_text = total_text.decode('utf-8')
            draw.text((img.width - 200, 30), total_text, fill=color, font=font)
            correction_notes.append(total_text)

            # 添加评语
            if analysis_result.overall_analysis:
                # 确保评语是 Unicode 字符串
                analysis_text = analysis_result.overall_analysis
                if isinstance(analysis_text, bytes):
                    analysis_text = analysis_text.decode('utf-8')

                # 计算可用的文本宽度（留出左右边距）
                text_max_width = img.width - 60  # 左右各留30像素边距

                # 将评语换行
                comment_prefix = "评语: "
                full_comment = comment_prefix + analysis_text
                wrapped_lines = self._wrap_text(full_comment, small_font, text_max_width)

                # 计算行高
                bbox = draw.textbbox((0, 0), "测试", font=small_font)
                line_height = bbox[3] - bbox[1] + 4  # 行高 + 间距

                # 从底部向上绘制，最多显示5行
                max_lines = min(5, len(wrapped_lines))
                start_y = img.height - (max_lines * line_height + 30)

                # 绘制每一行
                for i, line in enumerate(wrapped_lines[:max_lines]):
                    y_pos = start_y + (i * line_height)
                    if y_pos >= 0:  # 确保不超出图片顶部
                        draw.text((30, y_pos), line, fill=color, font=small_font)

                correction_notes.append(f"评语: {analysis_text}")

            # 保存为 base64
            import io
            buffer = io.BytesIO()
            img.save(buffer, format='PNG')
            img_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')

            return CorrectionImageResult(
                original_image_path=image_path,
                corrected_image_base64=img_base64,
                correction_notes=correction_notes,
                success=True,
            )

        except Exception as e:
            logger.error(f"Failed to create correction overlay: {e}")
            return CorrectionImageResult(
                original_image_path=image_path,
                success=False,
                error_message=str(e),
            )

    def _extract_json(self, text: str) -> Optional[Dict]:
        """从文本中提取 JSON"""
        try:
            # 尝试直接解析
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 尝试从 markdown 代码块中提取
        import re
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # 尝试找到第一个 { 到最后一个 }
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1:
            try:
                return json.loads(text[start:end+1])
            except json.JSONDecodeError:
                pass

        return None

    def _create_error_result(
        self,
        error_message: str,
        raw_response: Optional[str] = None
    ) -> ExamAnalysisResult:
        """创建错误结果"""
        return ExamAnalysisResult(
            subject=SubjectType.OTHER,
            grade="",
            total_score=0,
            max_score=0,
            accuracy_rate=0,
            questions=[],
            overall_analysis=f"分析失败: {error_message}",
            weak_points=[],
            improvement_suggestions=[],
            raw_response=raw_response,
        )

# Singleton instance
_gemini_ocr_service: Optional[GeminiOCRService] = None

@lru_cache()
def get_gemini_ocr_service() -> GeminiOCRService:
    """Get singleton Gemini OCR service instance"""
    global _gemini_ocr_service
    if _gemini_ocr_service is None:
        _gemini_ocr_service = GeminiOCRService()
    return _gemini_ocr_service
