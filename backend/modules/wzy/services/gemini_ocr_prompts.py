"""
WZY - Gemini OCR Prompt Provider (students TODO)

说明：
- WZY 属于学生模块：仅提供入口文件与 TODO。
- 为保持系统可运行，当前默认透传到 tony 的 prompt provider。

参考实现：
- `backend/modules/tony/services/gemini_ocr_prompts.py`
"""

from typing import Optional, Dict, Any

from backend.modules.tony.services import gemini_ocr_prompts as _tony


def get_subject_prompt(subject: str) -> str:
    return _tony.get_subject_prompt(subject)


def is_intake_mode(trace_stage: str, user_hint: Optional[str]) -> bool:
    return _tony.is_intake_mode(trace_stage, user_hint)


def build_exam_analysis_prompt(*, subject: str, grade: str, user_hint: Optional[str], intake_mode: bool) -> str:
    return _tony.build_exam_analysis_prompt(subject=subject, grade=grade, user_hint=user_hint, intake_mode=intake_mode)


def build_compact_retry_prompt(*, subject: str, grade: str, user_hint: Optional[str]) -> str:
    return _tony.build_compact_retry_prompt(subject=subject, grade=grade, user_hint=user_hint)


def resolve_ocr_model(*, default_model: str) -> str:
    return _tony.resolve_ocr_model(default_model=default_model)


def resolve_temperature(*, intake_mode: bool) -> float:
    return _tony.resolve_temperature(intake_mode=intake_mode)


def resolve_max_tokens() -> int:
    return _tony.resolve_max_tokens()


def get_logging_config() -> Dict[str, Any]:
    return _tony.get_logging_config()


