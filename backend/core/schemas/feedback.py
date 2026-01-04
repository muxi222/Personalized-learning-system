"""
Feedback Schemas - Pydantic models for user feedback (RLHF data collection)
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, ConfigDict
from enum import Enum

class FeedbackType(str, Enum):
    """反馈类型"""
    HELPFUL = "helpful"
    NOT_HELPFUL = "not_helpful"
    INCORRECT = "incorrect"
    PARTIALLY_CORRECT = "partially_correct"

class FeedbackCreate(BaseModel):
    """创建反馈请求"""
    question_id: int = Field(..., description="错题ID")
    feedback_type: FeedbackType = Field(..., description="反馈类型")
    rating: Optional[int] = Field(None, ge=1, le=5, description="评分 1-5星")
    comment: Optional[str] = Field(None, max_length=1000, description="评论")

    # RLHF相关
    original_response: Optional[str] = Field(None, description="原始AI回复")
    preferred_response: Optional[str] = Field(None, description="用户期望的回复")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "question_id": 42,
                "feedback_type": "helpful",
                "rating": 5,
                "comment": "分析很准确，帮助我理解了错误原因"
            }
        }
    )

class FeedbackResponse(BaseModel):
    """反馈响应Schema"""
    id: int
    user_id: int
    question_id: int
    feedback_type: FeedbackType
    rating: Optional[int]
    comment: Optional[str]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class FeedbackStats(BaseModel):
    """反馈统计"""
    total_feedbacks: int
    helpful_count: int
    not_helpful_count: int
    average_rating: Optional[float]
    feedback_rate: float = Field(..., description="反馈率 (有反馈的题目/总题目)")
