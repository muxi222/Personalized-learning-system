"""
Feedback stats - WZY module (学生实现)

TODO: 学生实现本模块的统计逻辑（参考 tony/default 模块的完整实现）。
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.db.session import get_db
from backend.core.schemas.feedback import FeedbackStats
from backend.modules.wzy.api.deps import get_current_user_id
from backend.modules.wzy.config import settings

router = APIRouter()


@router.get("/stats", response_model=FeedbackStats)
async def get_feedback_stats(
    subject: Optional[str] = Query(None, description="学科筛选（可选）"),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    TODO: 统计 WZY 模块（math/physics）的反馈情况
    - 需要按 subject 过滤（同模块多学科）
    - 需要 join Feedback -> Question 过滤题目学科
    """
    if subject and subject not in settings.SUBJECTS:
        raise HTTPException(status_code=400, detail=f"Subject '{subject}' is not supported by wzy. Supported: {settings.SUBJECTS}")
    raise HTTPException(status_code=501, detail="TODO: Implement feedback stats in WZY module")


