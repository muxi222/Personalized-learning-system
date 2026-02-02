"""
Feedback stats - RPJ module

当用户在前端选择 chinese/english/morality 等学科时，会路由到 rpj 模块。
该接口支持通过 query 参数 subject 进一步按学科统计（用于区分同模块内多个学科）。
"""

import logging
from typing import Optional, List

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.db.session import get_db
from backend.core.db.models import Feedback, Question, SubjectEnum
from backend.core.schemas.feedback import FeedbackStats
from backend.modules.rpj.api.deps import get_current_user_id
from backend.modules.rpj.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

# RPJ模块支持的学科
RPJ_SUBJECTS = ["chinese", "english", "morality"]


@router.get("/stats", response_model=FeedbackStats)
async def get_feedback_stats(
    subject: Optional[str] = Query(None, description="学科筛选（可选）：chinese/english/morality"),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    if subject == "":
        subject = None

    # subject 未传：默认统计 rpj 模块支持的所有学科；subject 传了则只统计该学科
    subject_enums: Optional[List[SubjectEnum]] = None
    if subject:
        if subject not in RPJ_SUBJECTS:
            raise HTTPException(
                status_code=400, 
                detail=f"Subject '{subject}' is not supported by rpj. Supported: {RPJ_SUBJECTS}"
            )
        subject_enums = [SubjectEnum(subject)]
    else:
        subject_enums = [SubjectEnum(s) for s in RPJ_SUBJECTS]

    base_where = (
        (Feedback.user_id == user_id)
        & (Question.user_id == user_id)
        & (Question.subject.in_(subject_enums))
    )

    total_feedbacks = (await db.execute(
        select(func.count(Feedback.id)).select_from(Feedback).join(Question, Feedback.question_id == Question.id).where(base_where)
    )).scalar() or 0

    helpful_count = (await db.execute(
        select(func.count(Feedback.id)).select_from(Feedback).join(Question, Feedback.question_id == Question.id).where(base_where & (Feedback.feedback_type == "helpful"))
    )).scalar() or 0

    not_helpful_count = (await db.execute(
        select(func.count(Feedback.id)).select_from(Feedback).join(Question, Feedback.question_id == Question.id).where(base_where & (Feedback.feedback_type == "not_helpful"))
    )).scalar() or 0

    average_rating = (await db.execute(
        select(func.avg(Feedback.rating)).select_from(Feedback).join(Question, Feedback.question_id == Question.id).where(base_where & (Feedback.rating.isnot(None)))
    )).scalar()

    questions_with_feedback = (await db.execute(
        select(func.count(func.distinct(Feedback.question_id))).select_from(Feedback).join(Question, Feedback.question_id == Question.id).where(base_where)
    )).scalar() or 0

    total_questions = (await db.execute(
        select(func.count(Question.id)).where(Question.user_id == user_id, Question.subject.in_(subject_enums))
    )).scalar() or 0

    feedback_rate = questions_with_feedback / total_questions if total_questions > 0 else 0.0

    return FeedbackStats(
        total_feedbacks=total_feedbacks,
        helpful_count=helpful_count,
        not_helpful_count=not_helpful_count,
        average_rating=float(average_rating) if average_rating is not None else None,
        feedback_rate=feedback_rate,
    )