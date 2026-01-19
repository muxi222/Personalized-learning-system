"""
Feedback stats - WZY module

WZY 模块（math/physics）的反馈统计
该接口支持通过 query 参数 subject 进一步按学科统计（用于区分同模块内多个学科）。
"""

import logging
from typing import Optional, List

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.db.session import get_db
from backend.core.db.models import Feedback, Question
from backend.core.schemas.feedback import FeedbackStats
from backend.modules.wzy.api.deps import get_current_user_id
from backend.modules.wzy.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/stats", response_model=FeedbackStats)
async def get_feedback_stats(
    subject: Optional[str] = Query(None, description="学科筛选（可选）"),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    统计 WZY 模块（math/physics）的反馈情况
    - 需要按 subject 过滤（同模块多学科）
    - 需要 join Feedback -> Question 过滤题目学科
    """
    if subject == "":
        subject = None

    # WZY 只支持数学和物理学科
    wzy_subjects = ['数学', '物理']
    
    # 验证学科参数
    subject_list: Optional[List[str]] = None
    if subject:
        if subject not in wzy_subjects:
            raise HTTPException(
                status_code=400, 
                detail=f"Subject '{subject}' is not supported by wzy. Supported: {wzy_subjects}"
            )
        subject_list = [subject]
    else:
        # 未传subject参数时，统计WZY支持的所有学科（数学和物理）
        subject_list = wzy_subjects

    # 基础查询条件：过滤当前用户且学科在WZY支持范围内的题目
    base_where = (
        (Feedback.user_id == user_id)
        & (Question.user_id == user_id)
        & (Question.subject.in_(subject_list))
    )

    # 统计总反馈数
    total_feedbacks = (await db.execute(
        select(func.count(Feedback.id))
        .select_from(Feedback)
        .join(Question, Feedback.question_id == Question.id)
        .where(base_where)
    )).scalar() or 0

    # 统计有帮助的反馈数
    helpful_count = (await db.execute(
        select(func.count(Feedback.id))
        .select_from(Feedback)
        .join(Question, Feedback.question_id == Question.id)
        .where(base_where & (Feedback.feedback_type == "helpful"))
    )).scalar() or 0

    # 统计无帮助的反馈数
    not_helpful_count = (await db.execute(
        select(func.count(Feedback.id))
        .select_from(Feedback)
        .join(Question, Feedback.question_id == Question.id)
        .where(base_where & (Feedback.feedback_type == "not_helpful"))
    )).scalar() or 0

    # 计算平均评分
    average_rating = (await db.execute(
        select(func.avg(Feedback.rating))
        .select_from(Feedback)
        .join(Question, Feedback.question_id == Question.id)
        .where(base_where & (Feedback.rating.isnot(None)))
    )).scalar()

    # 统计有反馈的题目数
    questions_with_feedback = (await db.execute(
        select(func.count(func.distinct(Feedback.question_id)))
        .select_from(Feedback)
        .join(Question, Feedback.question_id == Question.id)
        .where(base_where)
    )).scalar() or 0

    # 统计总题目数（数学和物理）
    total_questions = (await db.execute(
        select(func.count(Question.id))
        .where(
            Question.user_id == user_id, 
            Question.subject.in_(subject_list)
        )
    )).scalar() or 0

    # 计算反馈率
    feedback_rate = questions_with_feedback / total_questions if total_questions > 0 else 0.0

    return FeedbackStats(
        total_feedbacks=total_feedbacks,
        helpful_count=helpful_count,
        not_helpful_count=not_helpful_count,
        average_rating=float(average_rating) if average_rating is not None else None,
        feedback_rate=feedback_rate,
    )