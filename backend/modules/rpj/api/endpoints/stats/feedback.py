"""
Feedback stats - RPJ module (学生实现)

TODO: 学生实现本模块的统计逻辑（参考 tony/default 模块的完整实现）。

注意：该接口需要返回 backend/core/schemas/feedback.py 中的 FeedbackStats 结构，
以便 default 模块可以通过 /api/v1/feedback/stats?subject=xxx 转发并保持响应一致性。
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.db.session import get_db
from backend.core.schemas.feedback import FeedbackStats
from backend.modules.rpj.api.deps import get_current_user_id
from backend.modules.rpj.config import settings

router = APIRouter()


@router.get("/stats", response_model=FeedbackStats)
async def get_feedback_stats(
    subject: Optional[str] = Query(None, description="学科筛选（可选）"),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    if subject and subject not in settings.SUBJECTS:
        raise HTTPException(status_code=400, detail=f"Subject '{subject}' is not supported by rpj. Supported: {settings.SUBJECTS}")
    raise HTTPException(status_code=501, detail="TODO: Implement feedback stats in RPJ module")


