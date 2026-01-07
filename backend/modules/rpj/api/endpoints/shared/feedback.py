"""RPJ - Feedback API（学生实现版 / Stub）

仅保留主要入口 endpoints 的定义，删除具体实现。
参考：`backend/modules/tony/api/endpoints/shared/feedback.py`
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.db.session import get_db
from backend.core.schemas.feedback import FeedbackCreate, FeedbackResponse
from backend.modules.rpj.api.deps import get_current_user_id

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/", response_model=FeedbackResponse, status_code=201)
async def submit_feedback(payload: FeedbackCreate, db: AsyncSession = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    """TODO(student): 反馈入口。"""
    raise HTTPException(status_code=501, detail="Not Implemented: submit_feedback")

@router.get("/recent", response_model=FeedbackResponse)
async def list_recent_feedback(db: AsyncSession = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    """TODO(student): 反馈入口。"""
    raise HTTPException(status_code=501, detail="Not Implemented: list_recent_feedback")

