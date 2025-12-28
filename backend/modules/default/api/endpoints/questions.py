"""
Questions API Endpoints - Default Module
错题相关API（通用模块，支持所有学科）
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.db.session import get_db
from backend.core.crud import crud_question
from backend.core.schemas.question import (
    QuestionResponse,
    QuestionDetail,
    QuestionListResponse,
)
from backend.modules.default.api.deps import get_current_user_id
from backend.modules.default.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/", response_model=QuestionListResponse)
async def list_questions(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    subject: Optional[str] = Query(None, description="学科筛选（可选，支持所有学科）"),
    difficulty: Optional[str] = Query(None, description="难度筛选"),
    search: Optional[str] = Query(None, description="关键词搜索"),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    获取错题列表（通用模块，支持所有学科）
    
    支持分页、筛选和搜索。可以通过 subject 参数筛选特定学科的错题。
    如果不提供 subject 参数，则返回所有学科的错题。
    """
    skip = (page - 1) * page_size
    
    # 如果提供了 subject 参数，验证是否在支持的学科列表中
    if subject:
        if subject not in settings.SUBJECTS:
            raise HTTPException(
                status_code=400,
                detail=f"Subject '{subject}' is not supported. "
                       f"Supported subjects: {settings.SUBJECTS}"
            )
    
    questions, total = await crud_question.get_questions(
        db,
        user_id=user_id,
        skip=skip,
        limit=page_size,
        subject=subject,
        difficulty=difficulty,
        search=search,
    )

    logger.info(
        f"[DEFAULT] 查询错题列表: user_id={user_id}, subject={subject}, "
        f"page={page}, page_size={page_size}, total={total}"
    )

    return QuestionListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[QuestionResponse.model_validate(q) for q in questions],
    )


@router.get("/{question_id}", response_model=QuestionDetail)
async def get_question(
    question_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    获取错题详情（通用模块，支持所有学科）
    """
    question = await crud_question.get_question(db, question_id, user_id)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")
    
    logger.info(f"[DEFAULT] 获取错题详情: question_id={question_id}, user_id={user_id}")
    
    return QuestionDetail.model_validate(question)

