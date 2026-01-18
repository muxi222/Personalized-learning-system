"""WZY - Questions(Intake) API（学生实现版 / Stub）

仅保留主要入口 endpoints 的定义，删除具体实现。
参考：`backend/modules/tony/api/endpoints/intake/questions.py`
"""

import logging
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.db.session import get_db
from backend.core.schemas.question import (
    QuestionCreate,
    QuestionUpdate,
    QuestionResponse,
    QuestionDetail,
    QuestionListResponse,
    SimilarQuestionQuery,
)
from backend.core.schemas.task import TaskResponse
from backend.modules.wzy.api.deps import get_current_user_id

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/", response_model=TaskResponse, status_code=202)
async def create_question(
    question_data: QuestionCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """提交文字错题（异步任务入口）。"""
    raise HTTPException(status_code=501, detail="Not Implemented: create_question")


@router.post("/ocr", response_model=TaskResponse, status_code=202)
async def create_question_from_image(
    file: Optional[UploadFile] = File(None),
    text_data: Optional[str] = Form(None),
    input_type: str = Form(..., description="输入类型: 'image' 或 'text'"),
    subject: str = Form(""),
    difficulty: str = Form("medium"),
    background_tasks: BackgroundTasks = None,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """录入错题：图片OCR/文本两种入口。"""
    raise HTTPException(status_code=501, detail="Not Implemented: create_question_from_image")


@router.get("/", response_model=QuestionListResponse)
async def list_questions(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    subject: str = Query(""),
    difficulty: str = Query(""),
    search: str = Query(""),
    group_by: str = Query(""),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """错题列表入口（支持筛选/搜索/分组）。"""
    raise HTTPException(status_code=501, detail="Not Implemented: list_questions")


@router.get("/{question_id}", response_model=QuestionDetail)
async def get_question(
    question_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """错题详情入口。"""
    raise HTTPException(status_code=501, detail="Not Implemented: get_question")


@router.put("/{question_id}", response_model=QuestionResponse)
async def update_question(
    question_id: int,
    question_update: QuestionUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """更新错题入口。"""
    raise HTTPException(status_code=501, detail="Not Implemented: update_question")


@router.delete("/{question_id}")
async def delete_question(
    question_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """删除错题入口。"""
    raise HTTPException(status_code=501, detail="Not Implemented: delete_question")


@router.post("/similar", response_model=List[QuestionResponse])
async def find_similar_questions(
    query: SimilarQuestionQuery,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """相似题检索入口。"""
    raise HTTPException(status_code=501, detail="Not Implemented: find_similar_questions")

