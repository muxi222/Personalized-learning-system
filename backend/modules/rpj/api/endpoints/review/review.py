"""RPJ - Review API（学生实现版 / Stub）

仅保留主要入口 endpoints 的定义，删除具体实现。
参考：`backend/modules/tony/api/endpoints/review/review.py`
"""

import logging
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.db.session import get_db
from backend.core.schemas.question import QuestionResponse
from backend.modules.rpj.api.deps import get_current_user_id

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/review/due", response_model=List[QuestionResponse])
async def get_due_for_review(
    limit: int = Query(10, ge=1, le=50),
    subject: Optional[str] = Query(None),
    chapter: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """获取待复习错题入口。"""
    raise HTTPException(status_code=501, detail="Not Implemented: get_due_for_review")

