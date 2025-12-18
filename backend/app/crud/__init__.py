"""
CRUD Operations - Database access layer
"""

from .crud_question import (
    create_question,
    get_question,
    get_questions,
    update_question,
    delete_question,
    update_question_analysis,
)
from .crud_task import (
    create_task,
    get_task,
    get_task_by_task_id,
    update_task_status,
)
from .crud_user import (
    create_user,
    get_user,
    get_user_by_username,
    get_user_by_email,
    authenticate_user,
)
from .crud_exam_correction import (
    create_exam_correction,
    get_exam_correction,
    get_exam_corrections,
    get_correction_statistics,
    delete_exam_correction,
    update_exam_correction,
)
from .crud_image_file import (
    get_image_by_hash,
    get_image_file,
    get_image_files,
    create_image_file,
    increment_reference_count,
    decrement_reference_count,
    delete_image_file,
)

__all__ = [
    # Question
    "create_question",
    "get_question",
    "get_questions",
    "update_question",
    "delete_question",
    "update_question_analysis",
    # Task
    "create_task",
    "get_task",
    "get_task_by_task_id",
    "update_task_status",
    # User
    "create_user",
    "get_user",
    "get_user_by_username",
    "get_user_by_email",
    "authenticate_user",
    # Exam Correction
    "create_exam_correction",
    "get_exam_correction",
    "get_exam_corrections",
    "get_correction_statistics",
    "delete_exam_correction",
    "update_exam_correction",
    # Image File
    "get_image_by_hash",
    "get_image_file",
    "get_image_files",
    "create_image_file",
    "increment_reference_count",
    "decrement_reference_count",
    "delete_image_file",
]

