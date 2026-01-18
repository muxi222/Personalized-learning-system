"""
批改历史API (XMX模块 - 学生实现版)
"""

import logging
from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Path
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

# --- 核心依赖与配置 ---
from backend.modules.xmx.api.deps import get_current_user, get_db
from backend.modules.xmx.config import settings
from backend.core.db.models import User, SubjectEnum

# --- 核心 CRUD 操作 ---
from backend.core.crud.crud_exam_correction import (
    get_exam_correction,
    get_exam_corrections,
    get_correction_statistics,
    delete_exam_correction,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# ============ Helper Functions ============

def validate_subject(subject: str) -> None:
    """
    验证学科是否属于 XMX 模块支持的范围
    """
    if subject not in settings.SUBJECTS:
        raise HTTPException(
            status_code=400,
            detail=f"Subject '{subject}' is not supported by XMX module. "
                   f"Supported subjects: {settings.SUBJECTS}"
        )
logger.debug(f"Validated subject: {object}")
def image_to_url(correction_id: int, image_type: str) -> str:
    """
    生成图片URL路径
    """
    # 处理 host 为 0.0.0.0 的情况
    host = settings.HOST if settings.HOST not in ['0.0.0.0', ''] else 'localhost'
    port = settings.PORT
    
    # 构建 XMX 模块的专用图片路径
    return f"http://{host}:{port}/api/xmx/v1/ocr/images/corrections/{correction_id}/{image_type}"

# ============ Response Models (与 Tony 模块保持一致) ============

class CorrectionResponse(BaseModel):
    """批注记录详情响应"""
    id: int
    user_id: int
    subject: str
    grade: Optional[str]
    exam_title: Optional[str]
    original_image_url: str
    corrected_image_url: Optional[str]
    total_score: float
    max_score: float
    accuracy_rate: float
    question_count: int
    correct_count: int
    wrong_count: int
    overall_analysis: Optional[str]
    weak_points: List[str]
    improvement_suggestions: List[str]
    questions_detail: Optional[List[dict]] = None
    created_at: datetime

class CorrectionListResponse(BaseModel):
    """列表分页响应"""
    total: int
    page: int
    page_size: int
    items: List[CorrectionResponse]

class CorrectionStatisticsResponse(BaseModel):
    """统计数据响应"""
    period: str
    start_date: str
    end_date: str
    total_corrections: int
    total_questions: int
    total_correct: int
    total_wrong: int
    avg_accuracy: float
    avg_score: float
    subject_stats: dict
    time_series: List[dict]

# ============ API Endpoints ============

@router.get("/", response_model=CorrectionListResponse)
async def list_corrections(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    subject: Optional[str] = Query(None, description="学科筛选"),
    start_date: Optional[datetime] = Query(None, description="开始日期"),
    end_date: Optional[datetime] = Query(None, description="结束日期"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    获取 AI 批注记录列表
    """
    # 1. 学科验证 (XMX 特有逻辑)
    if subject:
        validate_subject(subject)

    skip = (page - 1) * page_size
    
    # 2. 数据库查询
    corrections, total = await get_exam_corrections(
        db,
        user_id=current_user.id,
        skip=skip,
        limit=page_size,
        subject=subject,
        start_date=start_date,
        end_date=end_date,
    )

    # 3. 数据封装与 URL 转换
    return CorrectionListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[
            CorrectionResponse(
                id=c.id,
                user_id=c.user_id,
                subject=c.subject.value if hasattr(c.subject, 'value') else str(c.subject),
                grade=c.grade,
                exam_title=c.exam_title,
                original_image_url=image_to_url(c.id, "original"),
                corrected_image_url=image_to_url(c.id, "corrected") if c.corrected_image else None,
                total_score=c.total_score,
                max_score=c.max_score,
                accuracy_rate=c.accuracy_rate,
                question_count=c.question_count,
                correct_count=c.correct_count,
                wrong_count=c.wrong_count,
                overall_analysis=c.overall_analysis,
                weak_points=c.weak_points,
                improvement_suggestions=c.improvement_suggestions,
                created_at=c.created_at,
            ) for c in corrections
        ]
    )

@router.get("/{correction_id}", response_model=CorrectionResponse)
async def get_correction(
    correction_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    获取单个批注记录详情
    """
    correction = await get_exam_correction(db, correction_id, current_user.id)
    
    if not correction:
        raise HTTPException(status_code=404, detail="Correction not found or access denied")

    return CorrectionResponse(
        id=correction.id,
        user_id=correction.user_id,
        subject=correction.subject.value if hasattr(correction.subject, 'value') else str(correction.subject),
        grade=correction.grade,
        exam_title=correction.exam_title,
        original_image_url=image_to_url(correction.id, "original"),
        corrected_image_url=image_to_url(correction.id, "corrected") if correction.corrected_image else None,
        total_score=correction.total_score,
        max_score=correction.max_score,
        accuracy_rate=correction.accuracy_rate,
        question_count=correction.question_count,
        correct_count=correction.correct_count,
        wrong_count=correction.wrong_count,
        overall_analysis=correction.overall_analysis,
        weak_points=correction.weak_points,
        improvement_suggestions=correction.improvement_suggestions,
        questions_detail=correction.questions_detail, # 详情页包含题目列表
        created_at=correction.created_at,
    )

@router.delete("/{correction_id}", status_code=204)
async def delete_correction(
    correction_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    删除批注记录
    """
    success = await delete_exam_correction(db, correction_id, current_user.id)
    if not success:
        raise HTTPException(status_code=404, detail="Correction not found")
    
    await db.commit()
    return None

@router.get("/statistics/{period}", response_model=CorrectionStatisticsResponse)
async def get_statistics(
    period: str = Path(
        ...,
        regex="^(week|month|quarter|year)$",
        description="统计周期：week=周, month=月, quarter=季度, year=年"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    获取学习统计报告
    """
    stats = await get_correction_statistics(db, current_user.id, period)
    
    # 如果没有统计数据，返回空对象而不是报错，方便前端处理
    if not stats:
        return CorrectionStatisticsResponse(
            period=period,
            start_date="",
            end_date="",
            total_corrections=0,
            total_questions=0,
            total_correct=0,
            total_wrong=0,
            avg_accuracy=0.0,
            avg_score=0.0,
            subject_stats={},
            time_series=[]
        )
        
    return CorrectionStatisticsResponse(**stats)