"""
Pydantic Schemas for API Request/Response validation
"""

from .question import (
    QuestionBase,
    QuestionCreate,
    QuestionUpdate,
    QuestionResponse,
    QuestionDetail,
    QuestionListResponse,
    QuestionGroup,
    QuestionGroupedListResponse,
    ChapterCount,
    SubjectChapterStats,
    QuestionChaptersResponse,
    KnowledgePointCount,
    SubjectKnowledgePointStats,
    QuestionKnowledgePointsResponse,
)
from .task import (
    TaskCreate,
    TaskResponse,
    TaskStatusResponse,
)
from .user import (
    UserBase,
    UserCreate,
    UserResponse,
    UserLogin,
    Token,
)
from .feedback import (
    FeedbackCreate,
    FeedbackResponse,
)

__all__ = [
    # Question
    "QuestionBase",
    "QuestionCreate",
    "QuestionUpdate",
    "QuestionResponse",
    "QuestionDetail",
    "QuestionListResponse",
    "QuestionGroup",
    "QuestionGroupedListResponse",
    "ChapterCount",
    "SubjectChapterStats",
    "QuestionChaptersResponse",
    "KnowledgePointCount",
    "SubjectKnowledgePointStats",
    "QuestionKnowledgePointsResponse",
    # Task
    "TaskCreate",
    "TaskResponse",
    "TaskStatusResponse",
    # User
    "UserBase",
    "UserCreate",
    "UserResponse",
    "UserLogin",
    "Token",
    # Feedback
    "FeedbackCreate",
    "FeedbackResponse",
]
