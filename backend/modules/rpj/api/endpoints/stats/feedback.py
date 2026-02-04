"""
Feedback stats - RPJ module (学生实现)

TODO: 学生实现本模块的统计逻辑（参考 tony/default 模块的完整实现）。
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.db.session import get_db
from backend.core.schemas.feedback import FeedbackStats
from backend.modules.rpj.api.deps import get_current_user_id

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
    raise HTTPException(status_code=501, detail="TODO: Implement feedback stats for RPJ module")