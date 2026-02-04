"""
Image Files API Endpoints
错题图片管理API
"""

import os
import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime

from backend.modules.wzm.api.deps import get_current_user, get_db
from backend.core.crud import crud_image_file
from backend.core.db.models import User, ImageFile, Question
from backend.modules.rpj.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


def _public_base() -> str:
    return (settings.PUBLIC_API_BASE_URL or "http://localhost:6100").rstrip("/")


def build_image_file_content_url(image_id: int) -> str:
    """
    Public URL for displaying an uploaded image in frontend.
    NOTE: image_id is ImageFile.id (NOT Question.id).
    """
    base = _public_base()
    return f"{base}/api/{settings.MODULE_NAME}/v1/image-files/{image_id}/content"

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


class ImageQuestionsStats(BaseModel):
    total: int
    correct: int
    wrong: int
    unknown: int


class ImageQuestionItem(BaseModel):
    id: int
    title: Optional[str] = None
    content: str
    subject: Optional[str] = None
    difficulty: Optional[str] = None
    upload_index: Optional[int] = None
    is_correct: Optional[bool] = None
    score: Optional[float] = None
    max_score: Optional[float] = None


class ImageQuestionsResponse(BaseModel):
    image: ImageFileResponse
    image_url: str
    stats: ImageQuestionsStats
    questions: List[ImageQuestionItem]

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


@router.get("/{image_id}/content")
async def get_image_file_content(
    image_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    获取图片二进制内容（用于前端 <img> 直接展示）。
    URL 中的 image_id 是 image_files.id（与 question.id 不同维度）。
    """
    import os
    from fastapi.responses import FileResponse

    image = await crud_image_file.get_image_file(db, image_id, current_user.id)
    if not image:
        raise HTTPException(status_code=404, detail="图片文件不存在")

    file_path = image.file_path
    if not os.path.isabs(file_path):
        # Align with default module path resolution
        current_file_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.abspath(os.path.join(current_file_dir, "../../../../.."))
        normalized = file_path.lstrip("./").lstrip("/")
        possible_paths = [
            os.path.join(project_root, normalized),
            os.path.join(os.getcwd(), normalized),
            os.path.join("./data/uploads", normalized),
        ]
        found_path = None
        for p in possible_paths:
            if os.path.exists(p):
                found_path = p
                break
        if not found_path:
            raise HTTPException(status_code=404, detail=f"Image file not found: {file_path}")
        file_path = found_path

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Image file not found")

    media_type = image.mime_type
    if not media_type:
        ext = os.path.splitext(file_path)[1].lower().lstrip(".")
        mime_types = {
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "webp": "image/webp",
            "heic": "image/heic",
        }
        media_type = mime_types.get(ext, "image/jpeg")

    return FileResponse(file_path, media_type=media_type, filename=os.path.basename(file_path))


@router.get("/{image_id}/questions", response_model=ImageQuestionsResponse)
async def list_questions_by_image(
    image_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    以“用户上传的图片”为维度，列出该图片中解析出的所有题目，并给出对/错统计。
    """
    from sqlalchemy import select, asc

    image = await crud_image_file.get_image_file(db, image_id, current_user.id)
    if not image:
        raise HTTPException(status_code=404, detail="图片文件不存在")

    # Query questions that were created from this uploaded image
    stmt = (
        select(Question)
        .where(Question.user_id == current_user.id, Question.source_image_id == image_id)
        # SQLite doesn't support "NULLS LAST" reliably; keep simple ordering.
        .order_by(asc(Question.upload_index), asc(Question.id))
    )
    rows = (await db.execute(stmt)).scalars().all()
    qs = list(rows)

    correct = sum(1 for q in qs if getattr(q, "is_correct", None) is True)
    wrong = sum(1 for q in qs if getattr(q, "is_correct", None) is False)
    unknown = sum(1 for q in qs if getattr(q, "is_correct", None) is None)

    image_url = build_image_file_content_url(image_id)

    image_resp = ImageFileResponse(
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
        related_corrections_count=0,
        has_derived_images=False,
    )

    return ImageQuestionsResponse(
        image=image_resp,
        image_url=image_url,
        stats=ImageQuestionsStats(total=len(qs), correct=correct, wrong=wrong, unknown=unknown),
        questions=[
            ImageQuestionItem(
                id=q.id,
                title=q.title,
                content=q.content,
                subject=str(q.subject.value) if getattr(q, "subject", None) is not None else None,
                difficulty=str(q.difficulty.value) if getattr(q, "difficulty", None) is not None else None,
                upload_index=getattr(q, "upload_index", None),
                is_correct=getattr(q, "is_correct", None),
                score=getattr(q, "score", None),
                max_score=getattr(q, "max_score", None),
            )
            for q in qs
        ],
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