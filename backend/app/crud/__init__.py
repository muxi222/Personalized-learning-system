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
]

