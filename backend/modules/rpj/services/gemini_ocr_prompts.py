"""
RPJ - Gemini OCR Prompt Provider (students TODO)

说明：
- RPJ 属于学生模块，这里先提供“入口文件 + TODO”。
- 为了不影响当前系统运行，本模块默认 **透传** 到 tony 的 prompt provider。
- 学生可在实现 RPJ 的 OCR/批改能力时，将 prompt 文案与模块化配置迁移到本文件并替换透传逻辑。

参考实现：
- `backend/modules/tony/services/gemini_ocr_prompts.py`
"""

from typing import Optional, Dict, Any

from backend.modules.tony.services import gemini_ocr_prompts as _tony


def get_subject_prompt(subject: str) -> str:
    """TODO(student): RPJ 自定义学科提示词。当前透传 tony。"""
    return _tony.get_subject_prompt(subject)


def is_intake_mode(trace_stage: str, user_hint: Optional[str]) -> bool:
    """TODO(student): RPJ 自定义 intake_mode 规则。当前透传 tony。"""
    return _tony.is_intake_mode(trace_stage, user_hint)


def build_exam_analysis_prompt(*, subject: str, grade: str, user_hint: Optional[str], intake_mode: bool) -> str:
    """TODO(student): RPJ 自定义试卷分析 prompt。当前透传 tony。"""
    return _tony.build_exam_analysis_prompt(subject=subject, grade=grade, user_hint=user_hint, intake_mode=intake_mode)


def build_compact_retry_prompt(*, subject: str, grade: str, user_hint: Optional[str]) -> str:
    """TODO(student): RPJ 自定义短 prompt。当前透传 tony。"""
    return _tony.build_compact_retry_prompt(subject=subject, grade=grade, user_hint=user_hint)


def resolve_ocr_model(*, default_model: str) -> str:
    """TODO(student): RPJ 自定义 OCR 模型选择。当前透传 tony。"""
    return _tony.resolve_ocr_model(default_model=default_model)


def resolve_temperature(*, intake_mode: bool) -> float:
    """TODO(student): RPJ 自定义 temperature 策略。当前透传 tony。"""
    return _tony.resolve_temperature(intake_mode=intake_mode)


def resolve_max_tokens() -> int:
    """TODO(student): RPJ 自定义 max_tokens。当前透传 tony。"""
    return _tony.resolve_max_tokens()


def get_logging_config() -> Dict[str, Any]:
    """TODO(student): RPJ 自定义日志开关/截断长度。当前透传 tony。"""
    return _tony.get_logging_config()


