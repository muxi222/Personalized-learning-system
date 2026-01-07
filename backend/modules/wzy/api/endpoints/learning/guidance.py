"""WZY - Guidance API（学生实现版 / Stub）

仅保留主要入口 endpoints 的定义，删除具体实现。
参考：`backend/modules/tony/api/endpoints/learning/guidance.py`
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.db.session import get_db
from backend.modules.wzy.api.deps import get_current_user_id

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/similar-questions")
async def similar_questions(subject: Optional[str] = Query(None), db: AsyncSession = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    """TODO(student): 学习指导入口。"""
    raise HTTPException(status_code=501, detail="Not Implemented: similar_questions")

@router.get("/learning-plan")
async def learning_plan(subject: Optional[str] = Query(None), db: AsyncSession = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    """TODO(student): 学习指导入口。"""
    raise HTTPException(status_code=501, detail="Not Implemented: learning_plan")

@router.get("/student-profile")
async def student_profile(subject: Optional[str] = Query(None), db: AsyncSession = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    """TODO(student): 学习指导入口。"""
    raise HTTPException(status_code=501, detail="Not Implemented: student_profile")

