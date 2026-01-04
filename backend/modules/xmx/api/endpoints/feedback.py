"""
用户反馈API (XMX模块 - 学生实现版本)

本文件为框架代码，需要学生完成核心业务逻辑的实现。
完整实现请参考: backend/modules/tony/api/endpoints/feedback.py

XMX模块支持的学科: economics
"""

import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.db.session import get_db
from backend.core.db.models import Feedback, Question
from backend.core.schemas.feedback import FeedbackCreate, FeedbackResponse
from backend.modules.xmx.api.deps import get_current_user_id
from backend.modules.xmx.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()

def validate_subject(subject: str) -> None:
    """验证学科是否属于XMX模块"""
    if subject not in settings.SUBJECTS:
        raise HTTPException(
            status_code=400,
            detail=f"Subject '{subject}' is not supported by XMX module. "
                   f"Supported subjects: {settings.SUBJECTS}"
        )

@router.post("/", response_model=FeedbackResponse, status_code=201)
async def create_feedback(
    feedback_data: FeedbackCreate,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    TODO: 学生实现 - 提交反馈（XMX模块）
    """
    raise HTTPException(status_code=501, detail="TODO: Implement feedback create in XMX module")

## 统计接口已移动到：backend/modules/xmx/api/endpoints/stats/feedback.py
