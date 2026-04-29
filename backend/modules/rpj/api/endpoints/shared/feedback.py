"""
Feedback API Endpoints
用户反馈收集API (用于RLHF)
"""

import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.db.session import get_db
from backend.core.db.models import Feedback, Question
from backend.core.schemas.feedback import FeedbackCreate, FeedbackResponse, FeedbackStats
from backend.modules.tony.api.deps import get_current_user_id

logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/", response_model=FeedbackResponse, status_code=201)
async def create_feedback(
    feedback_data: FeedbackCreate,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    提交反馈

    用于收集用户对AI分析结果的评价，支持:
    - 评分 (1-5星)
    - 评价类型 (helpful/not_helpful/incorrect)
    - 文字评论
    - RLHF数据 (原始回复 vs 期望回复)
    """
    # Verify question exists and belongs to user
    question = await db.execute(
        select(Question).where(
            Question.id == feedback_data.question_id,
            Question.user_id == user_id,
        )
    )
    question = question.scalar_one_or_none()
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    # Create feedback
    db_feedback = Feedback(
        user_id=user_id,
        question_id=feedback_data.question_id,
        feedback_type=feedback_data.feedback_type.value,
        rating=feedback_data.rating,
        comment=feedback_data.comment,
        original_response=feedback_data.original_response,
        preferred_response=feedback_data.preferred_response,
    )
    db.add(db_feedback)
    await db.flush()
    await db.refresh(db_feedback)
    await db.commit()

    logger.info(f"Feedback created: {db_feedback.id} for question {feedback_data.question_id}")

    return FeedbackResponse.model_validate(db_feedback)

## 统计接口已移动到：backend/modules/tony/api/endpoints/stats/feedback.py
