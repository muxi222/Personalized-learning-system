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
    delete_exam_correction,
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
    生成图片URL路径（统一由 default 模块处理）

    Args:
        correction_id: 批注记录ID
        image_type: 图片类型 ('original' 或 'corrected')
        subject: 学科名称（不再使用，统一由 default 模块处理）

    Returns:
        完整的URL路径（包含协议、主机和端口）
    """
    from backend.modules.default.config import settings

    # 优先使用 PUBLIC_API_BASE_URL 配置
    if settings.PUBLIC_API_BASE_URL:
        base_url = settings.PUBLIC_API_BASE_URL.rstrip('/')
        return f"{base_url}/api/v1/ocr/images/corrections/{correction_id}/{image_type}"

    # 如果没有设置 PUBLIC_API_BASE_URL，使用 default 模块的地址（6100端口）
    host = settings.HOST if settings.HOST not in ['0.0.0.0', ''] else 'localhost'
    port = settings.PORT  # default 模块使用 6100 端口

    # 生成完整URL，统一由 default 模块处理
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

class BatchDeleteRequest(BaseModel):
    """批量删除请求"""
    correction_ids: List[int]

class BatchDeleteResponse(BaseModel):
    """批量删除响应"""
    deleted_count: int
    failed_count: int
    failed_ids: List[int]

@router.post("/batch-delete", response_model=BatchDeleteResponse)
async def batch_delete_corrections(
    request: BatchDeleteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    批量删除批改记录（跨学科）

    支持批量删除多个批改记录，无论它们属于哪个学科。
    统一由 default 模块处理，无需路由到各个学科模块。
    """
    logger.info(
        f"[Default Module] batch_delete_corrections: user_id={current_user.id}, "
        f"ids={request.correction_ids}"
    )

    deleted_count = 0
    failed_count = 0
    failed_ids = []

    for correction_id in request.correction_ids:
        try:
            success = await delete_exam_correction(
                db,
                correction_id=correction_id,
                user_id=current_user.id,
                delete_related_questions=True,
            )
            if success:
                deleted_count += 1
                logger.info(f"[Default Module] Deleted correction {correction_id}")
            else:
                failed_count += 1
                failed_ids.append(correction_id)
                logger.warning(f"[Default Module] Failed to delete correction {correction_id}: not found or no permission")
        except Exception as e:
            failed_count += 1
            failed_ids.append(correction_id)
            logger.error(f"[Default Module] Error deleting correction {correction_id}: {e}")

    # 提交所有删除操作
    try:
        await db.commit()
    except Exception as e:
        logger.error(f"[Default Module] Error committing batch delete: {e}")
        await db.rollback()
        raise HTTPException(status_code=500, detail="批量删除失败")

    logger.info(
        f"[Default Module] Batch delete completed: deleted={deleted_count}, "
        f"failed={failed_count}, failed_ids={failed_ids}"
    )

    return BatchDeleteResponse(
        deleted_count=deleted_count,
        failed_count=failed_count,
        failed_ids=failed_ids,
    )
