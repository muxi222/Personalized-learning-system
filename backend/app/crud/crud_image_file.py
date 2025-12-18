"""
Image File CRUD Operations
图片文件去重数据库操作
"""

import logging
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import ImageFile, ImageFileTypeEnum

logger = logging.getLogger(__name__)


async def get_image_by_hash(
    db: AsyncSession,
    file_hash: str,
) -> Optional[ImageFile]:
    """根据哈希值查找图片文件"""
    query = select(ImageFile).where(ImageFile.file_hash == file_hash)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def create_image_file(
    db: AsyncSession,
    file_hash: str,
    user_id: int,
    file_type: str,
    subject: Optional[str],
    file_path: str,
    file_size: int,
    mime_type: Optional[str] = None,
    image_type: ImageFileTypeEnum = ImageFileTypeEnum.ORIGINAL,
    original_image_id: Optional[int] = None,
) -> ImageFile:
    """创建新的图片文件记录"""
    db_image = ImageFile(
        file_hash=file_hash,
        user_id=user_id,
        file_type=file_type,
        subject=subject,
        file_path=file_path,
        file_size=file_size,
        mime_type=mime_type,
        image_type=image_type.value if isinstance(image_type, ImageFileTypeEnum) else image_type,
        original_image_id=original_image_id,
        reference_count=1,
    )
    db.add(db_image)
    await db.flush()
    await db.refresh(db_image)
    logger.info(f"Created image file record: hash={file_hash[:16]}..., path={file_path}, id={db_image.id}, type={image_type.value}, original_image_id={original_image_id}")
    return db_image


async def increment_reference_count(
    db: AsyncSession,
    file_hash: str,
) -> Optional[ImageFile]:
    """增加图片文件的引用计数"""
    image_file = await get_image_by_hash(db, file_hash)
    if image_file:
        image_file.reference_count += 1
        await db.flush()
        logger.info(f"Incremented reference count for image: hash={file_hash[:16]}..., count={image_file.reference_count}")
    return image_file


async def decrement_reference_count(
    db: AsyncSession,
    file_hash: str,
) -> Optional[ImageFile]:
    """减少图片文件的引用计数"""
    image_file = await get_image_by_hash(db, file_hash)
    if image_file:
        image_file.reference_count = max(0, image_file.reference_count - 1)
        await db.flush()
        logger.info(f"Decremented reference count for image: hash={file_hash[:16]}..., count={image_file.reference_count}")
    return image_file


async def get_image_file(
    db: AsyncSession,
    image_id: int,
    user_id: Optional[int] = None,
) -> Optional[ImageFile]:
    """根据ID获取图片文件"""
    query = select(ImageFile).where(ImageFile.id == image_id)
    if user_id is not None:
        query = query.where(ImageFile.user_id == user_id)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_image_files(
    db: AsyncSession,
    user_id: int,
    file_type: Optional[str] = None,
    image_type: Optional[str] = None,
    subject: Optional[str] = None,
    skip: int = 0,
    limit: int = 20,
) -> tuple[list[ImageFile], int]:
    """获取用户的图片文件列表"""
    query = select(ImageFile).where(ImageFile.user_id == user_id)
    
    if file_type:
        query = query.where(ImageFile.file_type == file_type)
    if image_type:
        query = query.where(ImageFile.image_type == image_type)
    if subject:
        query = query.where(ImageFile.subject == subject)
    
    # 统计总数
    from sqlalchemy import func
    count_query = select(func.count()).select_from(query.subquery())
    count_result = await db.execute(count_query)
    total = count_result.scalar_one()
    
    # 应用分页和排序
    query = query.offset(skip).limit(limit).order_by(ImageFile.created_at.desc())
    
    result = await db.execute(query)
    images = result.scalars().all()
    
    return images, total


async def delete_image_file(
    db: AsyncSession,
    image_id: int,
    user_id: int,
) -> bool:
    """
    删除图片文件记录
    
    删除规则：
    1. 只能删除自己的图片文件
    2. 如果是原始图片，检查是否还有批改记录引用它
    3. 如果有批改记录引用，不能删除（需要先删除所有批改记录）
    4. 删除原始图片时，会同时删除所有相关的批改后图片（derived_images）
    5. 删除原始图片时，不会自动删除批改记录（批改记录由用户单独管理）
    
    Returns:
        是否删除成功
    """
    import os
    import logging
    
    logger = logging.getLogger(__name__)
    
    # 获取图片文件
    image_file = await get_image_file(db, image_id, user_id)
    if not image_file:
        return False
    
    # 如果是原始图片，需要删除所有相关的批改记录和批改后图片
    if image_file.image_type == ImageFileTypeEnum.ORIGINAL.value:
        # 查找所有引用此原始图片的批改记录
        from ..db.models import ExamCorrection
        corrections_query = select(ExamCorrection).where(
            ExamCorrection.original_image_id == image_id
        )
        corrections_result = await db.execute(corrections_query)
        related_corrections = corrections_result.scalars().all()
        
        # 删除所有相关的批改记录
        for correction in related_corrections:
            # 减少批改后图片的引用计数
            if correction.corrected_image:
                await decrement_reference_count(db, correction.corrected_image.file_hash)
            
            # 删除关联的错题记录
            from ..db.models import Question
            questions_query = select(Question).where(Question.exam_correction_id == correction.id)
            questions_result = await db.execute(questions_query)
            related_questions = questions_result.scalars().all()
            for question in related_questions:
                await db.delete(question)
            
            # 删除批改记录
            await db.delete(correction)
            logger.info(f"Deleted related correction record: {correction.id}")
        
        logger.info(f"Deleted {len(related_corrections)} related correction records")
        
        # 删除所有相关的批改后图片（derived_images）
        derived_images_query = select(ImageFile).where(ImageFile.original_image_id == image_id)
        derived_result = await db.execute(derived_images_query)
        derived_images = derived_result.scalars().all()
        
        # 删除所有批改后的图片
        for derived_image in derived_images:
            # 删除批改后图片文件
            try:
                # 处理相对路径
                derived_file_path = derived_image.file_path
                if not os.path.isabs(derived_file_path):
                    # 转换为绝对路径
                    current_file_dir = os.path.dirname(os.path.abspath(__file__))
                    project_root = os.path.abspath(os.path.join(current_file_dir, "../../../.."))
                    normalized = derived_file_path.lstrip("./").lstrip("/")
                    derived_file_path = os.path.join(project_root, normalized)
                
                if os.path.exists(derived_file_path):
                    os.remove(derived_file_path)
                    logger.info(f"Deleted derived image file: {derived_file_path}")
            except Exception as e:
                logger.warning(f"Failed to delete derived image file: {e}")
            
            await db.delete(derived_image)
            logger.info(f"Deleted derived image record: {derived_image.id}")
    else:
        # 如果是批改后的图片或其他类型，检查是否还有批改记录引用
        from ..db.models import ExamCorrection
        corrections_query = select(ExamCorrection).where(
            ExamCorrection.corrected_image_id == image_id
        )
        corrections_result = await db.execute(corrections_query)
        related_corrections = corrections_result.scalars().all()
        
        if related_corrections:
            logger.warning(f"Cannot delete image {image_id}: still referenced by {len(related_corrections)} correction records")
            raise ValueError(f"无法删除图片：仍有 {len(related_corrections)} 条批改记录引用此图片。请先删除所有相关的批改记录。")
    
    # 删除原始图片文件
    try:
        # 处理相对路径
        file_path = image_file.file_path
        if not os.path.isabs(file_path):
            # 转换为绝对路径
            current_file_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.abspath(os.path.join(current_file_dir, "../../../.."))
            normalized = file_path.lstrip("./").lstrip("/")
            file_path = os.path.join(project_root, normalized)
        
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"Deleted image file: {file_path}")
    except Exception as e:
        logger.warning(f"Failed to delete image file: {e}")
    
    # 删除图片文件记录
    await db.delete(image_file)
    logger.info(f"Deleted image file record: {image_id}")
    
    return True

