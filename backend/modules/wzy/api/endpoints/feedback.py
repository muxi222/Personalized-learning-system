"""
Feedback API Endpoints - WZY module (学生实现)

TODO: 学生实现本模块的反馈收集与统计逻辑（参考 tony 模块）。
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.db.session import get_db
from backend.core.schemas.feedback import FeedbackCreate, FeedbackResponse
from backend.modules.wzy.api.deps import get_current_user_id

router = APIRouter()


@router.post("/", response_model=FeedbackResponse, status_code=201)
async def create_feedback(
    feedback_data: FeedbackCreate,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    TODO: 学生实现 - 提交反馈（WZY模块）
    """
    raise HTTPException(status_code=501, detail="TODO: Implement feedback create in WZY module")

## 统计接口已移动到：backend/modules/wzy/api/endpoints/stats/feedback.py（学生实现）