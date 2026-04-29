"""
TONY Module - Agents Package

Agent implementations for TONY module (History, Geography, Other subjects)
"""

# NOTE: For clarity, implementations live in feature subpackages:
# - ai_correction
# - intake
# - learning
# - review (future)
# Import from feature subpackages directly (wrappers removed).
from .intake.question_intake_agent import QuestionIntakeAgent  # noqa: F401
from .ai_correction.ocr_agent import OCRAgent  # noqa: F401
from .learning.similar_question_agent import SimilarQuestionAgent  # noqa: F401

__all__ = [
    "QuestionIntakeAgent",
    "OCRAgent",
    "SimilarQuestionAgent",
]
