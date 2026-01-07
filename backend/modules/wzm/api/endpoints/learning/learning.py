"""WZM - Learning API（学生实现版 / Stub）

仅保留主要入口 endpoints 的定义，删除具体实现。
参考：`backend/modules/tony/api/endpoints/learning/learning.py`
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Path
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.db.session import get_db
from backend.modules.wzm.api.deps import get_current_user_id

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/profile")
async def get_learning_profile(subject: Optional[str] = Query(None), db: AsyncSession = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    """TODO(student): 学习建议/统计入口。"""
    raise HTTPException(status_code=501, detail="Not Implemented: get_learning_profile")

@router.get("/recommendations")
async def get_recommendations(subject: Optional[str] = Query(None), db: AsyncSession = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    """TODO(student): 学习建议/统计入口。"""
    raise HTTPException(status_code=501, detail="Not Implemented: get_recommendations")

@router.get("/study-plan")
async def get_study_plan(subject: Optional[str] = Query(None), db: AsyncSession = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    """TODO(student): 学习建议/统计入口。"""
    raise HTTPException(status_code=501, detail="Not Implemented: get_study_plan")

@router.get("/similar-questions/{question_id}")
async def get_similar_questions(question_id: int = Path(...), db: AsyncSession = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    """TODO(student): 学习建议/统计入口。"""
    raise HTTPException(status_code=501, detail="Not Implemented: get_similar_questions")

@router.get("/summary")
async def get_learning_summary(subject: Optional[str] = Query(None), db: AsyncSession = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    """TODO(student): 学习建议/统计入口。"""
    raise HTTPException(status_code=501, detail="Not Implemented: get_learning_summary")

@router.post("/feedback")
async def submit_learning_feedback(subject: Optional[str] = Query(None), db: AsyncSession = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    """TODO(student): 学习建议/统计入口。"""
    raise HTTPException(status_code=501, detail="Not Implemented: submit_learning_feedback")

