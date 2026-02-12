"""
Feedback stats - RPJ module (学生实现)

TODO: 学生实现本模块的统计逻辑（参考 tony/default 模块的完整实现）。
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

logger = logging.getLogger(__name__)
router = APIRouter()

# 定义 RPJ 模块支持的学科
RPJ_SUBJECTS = ["chinese", "english", "morality"]


@router.get("/stats", response_model=FeedbackStats)
async def get_feedback_stats(
    subject: Optional[str] = Query(None, description="学科筛选（可选）"),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    统计 RPJ 模块（语文、英语、道法）的反馈情况
    """
    if subject and subject not in RPJ_SUBJECTS:
        raise HTTPException(
            status_code=400,
            detail=f"Subject '{subject}' is not supported by RPJ module. Supported: {RPJ_SUBJECTS}"
        )

    # subject 未传：默认统计 RPJ 模块支持的所有学科；subject 传了则只统计该学科
    subject_enums: Optional[List[SubjectEnum]] = None
    if subject:
        subject_enums = [SubjectEnum(subject)]
    else:
        subject_enums = [SubjectEnum(s) for s in RPJ_SUBJECTS]

    # 基础查询条件
    base_where = (
        (Feedback.user_id == user_id)
        & (Question.user_id == user_id)
        & (Question.subject.in_(subject_enums))
    )

    # 总反馈数
    total_feedbacks = (await db.execute(
        select(func.count(Feedback.id))
        .select_from(Feedback)
        .join(Question, Feedback.question_id == Question.id)
        .where(base_where)
    )).scalar() or 0

    # 有帮助的反馈数
    helpful_count = (await db.execute(
        select(func.count(Feedback.id))
        .select_from(Feedback)
        .join(Question, Feedback.question_id == Question.id)
        .where(base_where & (Feedback.feedback_type == "helpful"))
    )).scalar() or 0

    # 无帮助的反馈数
    not_helpful_count = (await db.execute(
        select(func.count(Feedback.id))
        .select_from(Feedback)
        .join(Question, Feedback.question_id == Question.id)
        .where(base_where & (Feedback.feedback_type == "not_helpful"))
    )).scalar() or 0

    # 平均评分
    average_rating = (await db.execute(
        select(func.avg(Feedback.rating))
        .select_from(Feedback)
        .join(Question, Feedback.question_id == Question.id)
        .where(base_where & (Feedback.rating.isnot(None)))
    )).scalar()

    # 有反馈的问题数
    questions_with_feedback = (await db.execute(
        select(func.count(func.distinct(Feedback.question_id)))
        .select_from(Feedback)
        .join(Question, Feedback.question_id == Question.id)
        .where(base_where)
    )).scalar() or 0

    # 总问题数
    total_questions = (await db.execute(
        select(func.count(Question.id))
        .where(Question.user_id == user_id, Question.subject.in_(subject_enums))
    )).scalar() or 0

    # 反馈率
    feedback_rate = questions_with_feedback / total_questions if total_questions > 0 else 0.0

    return FeedbackStats(
        total_feedbacks=total_feedbacks,
        helpful_count=helpful_count,
        not_helpful_count=not_helpful_count,
        average_rating=float(average_rating) if average_rating is not None else None,
        feedback_rate=feedback_rate,
    )