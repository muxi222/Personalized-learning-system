"""
Corrections API - Default Module (Cross-Subject)
批改记录API - 默认模块（跨学科查询）
"""

import os
import logging
from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.modules.default.api.deps import get_current_user, get_db
from backend.core.crud.crud_exam_correction import (
    get_exam_corrections,
    get_correction_statistics,
)
from backend.core.db.models import User, SubjectEnum

logger = logging.getLogger(__name__)
router = APIRouter()

# 学科到模块的映射
SUBJECT_TO_MODULE = {
    # RPJ模块 (6001)
    "chinese": ("rpj", 6001),
    "english": ("rpj", 6001),
    "politics": ("rpj", 6001),
    # XMX模块 (6002)
    "economics": ("xmx", 6002),
    # WZY模块 (6003)
    "math": ("wzy", 6003),
    "physics": ("wzy", 6003),
    # WZM模块 (6004)
    "chemistry": ("wzm", 6004),
    # TONY模块 (6005)
    "history": ("tony", 6005),
    "geography": ("tony", 6005),
    "other": ("tony", 6005),
}


def image_to_url(correction_id: int, image_type: str, subject: str) -> str:
    """
    生成图片URL路径（根据学科路由到对应模块）

    Args:
        correction_id: 批注记录ID
        image_type: 图片类型 ('original' 或 'corrected')
        subject: 学科名称（用于确定模块和端口）

    Returns:
        完整的URL路径（包含协议、主机和端口）
    """
    # 获取学科对应的模块和端口
    module_info = SUBJECT_TO_MODULE.get(subject)
    if not module_info:
        # 未知学科，使用默认模块
        logger.warning(f"Unknown subject '{subject}', using default module (port 6100)")
        port = 6100
    else:
        _, port = module_info

    # 获取主机配置（支持环境变量）
    host = os.getenv('API_HOST', 'localhost')
    if host in ['0.0.0.0', '']:
        host = 'localhost'

    # 生成完整URL
    return f"http://{host}:{port}/api/v1/ocr/images/corrections/{correction_id}/{image_type}"


# ============ Response Models ============

class CorrectionResponse(BaseModel):
    """批注记录响应"""
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
    subject: Optional[str] = Query(None, description="学科筛选（可选）"),
    start_date: Optional[datetime] = Query(None, description="开始日期"),
    end_date: Optional[datetime] = Query(None, description="结束日期"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    获取AI批改记录列表（跨学科）

    支持:
    - 不指定学科：返回所有学科的批改记录
    - 指定学科：返回特定学科的批改记录
    - 分页、时间范围筛选
    """
    logger.info(
        f"[Default Module] list_corrections: user_id={current_user.id}, "
        f"subject={subject or 'ALL'}, page={page}"
    )

    skip = (page - 1) * page_size
    corrections, total = await get_exam_corrections(
        db,
        user_id=current_user.id,
        skip=skip,
        limit=page_size,
        subject=subject,  # None表示不筛选学科
        start_date=start_date,
        end_date=end_date,
    )

    logger.info(
        f"[Default Module] Found {len(corrections)} corrections, "
        f"total={total}, subject_filter={subject or 'none'}"
    )

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
                original_image_url=image_to_url(c.id, "original", c.subject.value),
                corrected_image_url=image_to_url(c.id, "corrected", c.subject.value) if c.corrected_image else None,
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


@router.get("/statistics/{period}", response_model=CorrectionStatisticsResponse)
async def get_statistics(
    period: str,
    subject: Optional[str] = Query(None, description="学科筛选（可选）"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    获取批改统计数据（跨学科）

    支持:
    - 不指定学科：返回所有学科的统计
    - 指定学科：返回特定学科的统计
    """
    logger.info(
        f"[Default Module] get_statistics: user_id={current_user.id}, "
        f"period={period}, subject={subject or 'ALL'}"
    )

    stats = await get_correction_statistics(
        db,
        user_id=current_user.id,
        period=period,
        subject=subject,  # None表示不筛选学科
    )

    return CorrectionStatisticsResponse(**stats)
