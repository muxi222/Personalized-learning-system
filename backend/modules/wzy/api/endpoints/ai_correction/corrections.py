"""
Exam Corrections API Endpoints
AI批注记录相关API
"""

import logging
from typing import Optional, List
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Path
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.modules.wzy.api.deps import get_current_user, get_db  # 修改：tony -> wzy
from backend.core.crud.crud_exam_correction import (
    get_exam_correction,
    get_exam_corrections,
    get_correction_statistics,
    delete_exam_correction,
)
from backend.core.db.models import User, SubjectEnum
from backend.core.utils.file_utils import get_user_directory_name
from backend.modules.wzy.config import settings  # 修改：tony -> wzy

logger = logging.getLogger(__name__)
router = APIRouter()


def image_to_url(correction_id: int, image_type: str) -> str:
    """
    生成图片URL路径（使用correction_id和image_type）
    返回完整的 URL 以便前端正确访问

    Args:
        correction_id: 批注记录ID
        image_type: 图片类型 ('original' 或 'corrected')

    Returns:
        完整的URL路径（包含协议、主机和端口）
    """
    # 获取主机和端口配置
    # 如果 HOST 是 0.0.0.0，则使用 localhost（0.0.0.0 不能用于 URL）
    host = settings.HOST if settings.HOST not in ['0.0.0.0', ''] else 'localhost'
    port = settings.PORT

    # 生成完整URL: http://localhost:6003/api/v1/ocr/images/corrections/{correction_id}/{image_type}
    return f"http://{host}:{port}/api/v1/ocr/images/corrections/{correction_id}/{image_type}"


# ============ Response Models ============

class CorrectionResponse(BaseModel):
    """批注记录响应"""
    id: int
    user_id: int
    subject: str
    grade: Optional[str]
    exam_title: Optional[str]
    original_image_url: str  # URL而不是路径
    corrected_image_url: Optional[str]  # URL而不是路径
    total_score: float
    max_score: float
    accuracy_rate: float
    question_count: int
    correct_count: int
    wrong_count: int
    overall_analysis: Optional[str]
    weak_points: List[str]
    improvement_suggestions: List[str]
    questions_detail: Optional[List[dict]] = None  # 题目详情（仅在详情接口返回）
    created_at: datetime


class CorrectionListResponse(BaseModel):
    """批注记录列表响应"""
    total: int
    page: int
    page_size: int
    items: List[CorrectionResponse]


class CorrectionStatisticsResponse(BaseModel):
    """批注统计响应"""
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
    获取AI批注记录列表
    支持分页、学科筛选、时间范围筛选
    """
    logger.info(f"list_corrections called: user_id={current_user.id}, user={current_user.username}, subject={subject}")
    
    skip = (page - 1) * page_size
    corrections, total = await get_exam_corrections(
        db,
        user_id=current_user.id,
        skip=skip,
        limit=page_size,
        subject=subject,
        start_date=start_date,
        end_date=end_date,
    )
    
    logger.info(f"list_corrections result: found {len(corrections)} items, total={total}")
    
    return CorrectionListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[
            CorrectionResponse(
                id=c.id,
                user_id=c.user_id,
                subject=c.subject.value,
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
            )
            for c in corrections
        ],
    )


@router.get("/{correction_id}", response_model=CorrectionResponse)
async def get_correction(
    correction_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取单个批注记录详情"""
    correction = await get_exam_correction(db, correction_id, current_user.id)
    if not correction:
        raise HTTPException(status_code=404, detail="批注记录不存在")
    
    return CorrectionResponse(
        id=correction.id,
        user_id=correction.user_id,
        subject=correction.subject.value,
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
        questions_detail=correction.questions_detail,  # 详情接口返回所有题目
        created_at=correction.created_at,
    )


@router.delete("/{correction_id}", status_code=204)
async def delete_correction(
    correction_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除批注记录"""
    success = await delete_exam_correction(db, correction_id, current_user.id)
    if not success:
        raise HTTPException(status_code=404, detail="批注记录不存在")
    await db.commit()


@router.get("/statistics/{period}", response_model=CorrectionStatisticsResponse)
async def get_statistics(
    period: str = Path(
        ...,
        pattern=r"^(week|month|quarter|year)$",  # 修复：regex -> pattern
        description="统计周期：week=周, month=月, quarter=季度, year=年"
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    获取批注统计数据
    
    支持周、月、季度、年度统计：
    - 总批改次数
    - 总题目数
    - 正确率趋势
    - 学科分布
    - 时间序列数据（用于图表）
    """
    stats = await get_correction_statistics(db, current_user.id, period)
    return CorrectionStatisticsResponse(**stats)