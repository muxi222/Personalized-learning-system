"""
WZM Agents - Tasks (Celery include module)

Celery is configured to include `backend.modules.wzm.agents.tasks`.
This file keeps that import path stable while organizing actual task implementations
into feature subpackages:
- ai_correction
- intake
- learning
- review (future)
"""

# Re-export tasks so existing Celery include path remains valid.
from backend.modules.wzm.agents.ai_correction.tasks import ocr_exam_task, batch_ocr_task  # noqa: F401
from backend.modules.wzm.agents.intake.tasks import process_question_task, reanalyze_question_task  # noqa: F401
from backend.modules.wzm.agents.learning.tasks import find_similar_questions_task  # noqa: F401

__all__ = [
    "process_question_task",
    "reanalyze_question_task",
    "find_similar_questions_task",
    "ocr_exam_task",
    "batch_ocr_task",
]


