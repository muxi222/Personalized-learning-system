"""
Image Files API Endpoints
错题图片管理API
"""

import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from backend.modules.tony.api.deps import get_current_user, get_db
from backend.core.crud import crud_image_file
from backend.core.db.models import User, ImageFile

logger = logging.getLogger(__name__)
router = APIRouter()


# ============ Response Models ============

class ImageFileResponse(BaseModel):
    """图片文件响应"""
    id: int
    file_hash: str
    user_id: int
    file_type: str
    image_type: str
    subject: Optional[str]
    original_image_id: Optional[int]
    file_path: str
    file_size: int
    mime_type: Optional[str]
    reference_count: int
    created_at: datetime
    updated_at: datetime
    
    # 关联信息
    related_corrections_count: int = 0  # 关联的批改记录数量
    has_derived_images: bool = False  # 是否有批改后的图片


class ImageFileListResponse(BaseModel):
    """图片文件列表响应"""
    total: int
    page: int
    page_size: int
    items: List[ImageFileResponse]


# ============ API Endpoints ============

@router.get("/", response_model=ImageFileListResponse)
async def list_image_files(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    file_type: Optional[str] = Query(None, description="文件类型: corrections 或 questions"),
    image_type: Optional[str] = Query(None, description="图片类型: original 或 corrected"),
    subject: Optional[str] = Query(None, description="学科筛选"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    获取用户的图片文件列表
    支持分页、文件类型、图片类型、学科筛选
    """
    skip = (page - 1) * page_size
    images, total = await crud_image_file.get_image_files(
        db,
        user_id=current_user.id,
        file_type=file_type,
        image_type=image_type,
        subject=subject,
        skip=skip,
        limit=page_size,
    )
    
    # 构建响应数据
    items = []
    for image in images:
        # 统计关联的批改记录数量
        from backend.core.db.models import ExamCorrection
        from sqlalchemy import select, func
        corrections_count_query = select(func.count(ExamCorrection.id)).where(
            (ExamCorrection.original_image_id == image.id) | 
            (ExamCorrection.corrected_image_id == image.id)
        )
        corrections_count_result = await db.execute(corrections_count_query)
        corrections_count = corrections_count_result.scalar_one() or 0
        
        # 检查是否有批改后的图片
        derived_images_query = select(func.count(ImageFile.id)).where(
            ImageFile.original_image_id == image.id
        )
        derived_images_result = await db.execute(derived_images_query)
        has_derived = (derived_images_result.scalar_one() or 0) > 0
        
        items.append(ImageFileResponse(
            id=image.id,
            file_hash=image.file_hash,
            user_id=image.user_id,
            file_type=image.file_type,
            image_type=image.image_type,
            subject=image.subject,
            original_image_id=image.original_image_id,
            file_path=image.file_path,
            file_size=image.file_size,
            mime_type=image.mime_type,
            reference_count=image.reference_count,
            created_at=image.created_at,
            updated_at=image.updated_at,
            related_corrections_count=corrections_count,
            has_derived_images=has_derived,
        ))
    
    return ImageFileListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=items,
    )


@router.get("/{image_id}", response_model=ImageFileResponse)
async def get_image_file_detail(
    image_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取图片文件详情"""
    image = await crud_image_file.get_image_file(db, image_id, current_user.id)
    if not image:
        raise HTTPException(status_code=404, detail="图片文件不存在")
    
    # 统计关联的批改记录数量
    from backend.core.db.models import ExamCorrection
    from sqlalchemy import select, func
    corrections_count_query = select(func.count(ExamCorrection.id)).where(
        (ExamCorrection.original_image_id == image.id) | 
        (ExamCorrection.corrected_image_id == image.id)
    )
    corrections_count_result = await db.execute(corrections_count_query)
    corrections_count = corrections_count_result.scalar_one() or 0
    
    # 检查是否有批改后的图片
    derived_images_query = select(func.count(ImageFile.id)).where(
        ImageFile.original_image_id == image.id
    )
    derived_images_result = await db.execute(derived_images_query)
    has_derived = (derived_images_result.scalar_one() or 0) > 0
    
    return ImageFileResponse(
        id=image.id,
        file_hash=image.file_hash,
        user_id=image.user_id,
        file_type=image.file_type,
        image_type=image.image_type,
        subject=image.subject,
        original_image_id=image.original_image_id,
        file_path=image.file_path,
        file_size=image.file_size,
        mime_type=image.mime_type,
        reference_count=image.reference_count,
        created_at=image.created_at,
        updated_at=image.updated_at,
        related_corrections_count=corrections_count,
        has_derived_images=has_derived,
    )


@router.delete("/{image_id}")
async def delete_image_file_endpoint(
    image_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    删除图片文件
    
    删除规则：
    1. 只能删除自己的图片文件
    2. 如果图片被批改记录引用，不能删除
    3. 删除原始图片时，会同时删除所有相关的批改记录和批改后图片
    """
    try:
        success = await crud_image_file.delete_image_file(db, image_id, current_user.id)
        if not success:
            raise HTTPException(status_code=404, detail="图片文件不存在")
        return {"success": True, "message": "图片文件已删除"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to delete image file: {e}")
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")

