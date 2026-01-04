"""
Review API Endpoints (TONY Module)
复习相关API（基于艾宾浩斯遗忘曲线）
"""

import logging
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.db.session import get_db
from backend.core.schemas.question import QuestionResponse
from backend.modules.tony.api.deps import get_current_user_id
from backend.modules.tony.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/review/due", response_model=List[QuestionResponse])
async def get_due_for_review(
    limit: int = Query(10, ge=1, le=50),
    subject: Optional[str] = Query(None, description="学科筛选（可选）"),
    chapter: Optional[str] = Query(None, description="题目类型/章节筛选（可选）"),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    获取需要复习的错题
    基于艾宾浩斯遗忘曲线推荐
    """
    from datetime import datetime
    from sqlalchemy import select, or_
    from backend.core.db.models import Question, SubjectEnum

    if subject == "":
        subject = None
    if chapter == "":
        chapter = None

    # tony 支持的学科：history/geography/other
    if subject and subject not in settings.SUBJECTS:
        raise HTTPException(status_code=400, detail=f"Subject '{subject}' is not supported by tony. Supported subjects: {settings.SUBJECTS}")

    now = datetime.utcnow()
    q = (
        select(Question)
        .where(Question.user_id == user_id)
        .where((Question.next_review_at <= now) | (Question.next_review_at.is_(None)))
        .where(Question.mastery_level < 0.9)
        .order_by(Question.mastery_level.asc(), Question.next_review_at.asc())
        .limit(limit)
    )

    # 未传 subject：默认限定为本模块学科集合，避免跨模块数据混入
    if subject:
        q = q.where(Question.subject == SubjectEnum(subject))
    else:
        q = q.where(Question.subject.in_([SubjectEnum(s) for s in settings.SUBJECTS]))

    if chapter:
        if chapter == "未分类":
            q = q.where(or_(Question.chapter.is_(None), Question.chapter == ""))
        else:
            q = q.where(Question.chapter == chapter)

    result = await db.execute(q)
    questions = list(result.scalars().all())
    return [QuestionResponse.model_validate(qobj) for qobj in questions]


