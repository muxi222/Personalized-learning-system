"""
Image File CRUD Operations
图片文件去重数据库操作
"""

import logging
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import InvalidRequestError

from ..db.models import ImageFile, ImageFileTypeEnum

logger = logging.getLogger(__name__)


def _resolve_possible_file_paths(file_path: str) -> list[str]:
    """
    Resolve stored file_path into possible filesystem paths.
    Stored paths may be absolute or relative (e.g. data/uploads/...).
    """
    import os

    if not file_path:
        return []
    if os.path.isabs(file_path):
        return [file_path]

    normalized = str(file_path).lstrip("./").lstrip("/")
    # repo root = backend/core/crud/ -> backend/core/ -> backend/ -> repo_root
    current_file_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(current_file_dir, "../../.."))
    return [
        os.path.join(project_root, normalized),
        os.path.join(os.getcwd(), normalized),
        os.path.join("./data/uploads", normalized),
    ]


def _safe_unlink(file_path: str) -> bool:
    """
    Best-effort unlink. Returns True if file was removed.
    Safety: only delete files under ./data/uploads (or resolved equivalents).
    """
    import os

    for p in _resolve_possible_file_paths(file_path):
        try:
            ap = os.path.abspath(p)
            # allow deleting only under data/uploads to avoid accidents
            if "/data/uploads/" not in ap.replace("\\", "/"):
                continue
            if os.path.exists(ap):
                os.remove(ap)
                return True
        except Exception:
            continue
    return False

async def get_image_by_hash(
    db: AsyncSession,
    file_hash: str,
) -> Optional[ImageFile]:
    """根据哈希值查找图片文件"""
    query = select(ImageFile).where(ImageFile.file_hash == file_hash)
    result = await db.execute(query)
    return result.scalar_one_or_none()

async def get_image_by_path(
    db: AsyncSession,
    file_path: str,
) -> Optional[ImageFile]:
    """根据文件路径查找图片文件记录"""
    query = select(ImageFile).where(ImageFile.file_path == file_path)
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
    """
    创建新的图片文件记录（幂等 + best-effort refresh）。

    Some legacy SQLite schemas may not have a proper PK on image_files.id, which makes
    ORM refresh() fail with InvalidRequestError("Could not refresh instance ...").
    We treat refresh as best-effort and fall back to querying by unique file_hash.
    """
    # NOTE:
    # - For "questions" uploads, product may want "no dedupe" semantics (same bytes, new image id per upload).
    # - Callers can enforce that by supplying a unique file_hash (e.g. salted by task_id/uuid).
    # Here we keep backward-compatible behavior: if file_hash already exists, return the existing record.
    existing = await get_image_by_hash(db, file_hash)
    if existing:
        return existing
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
    try:
        await db.refresh(db_image)
    except InvalidRequestError:
        logger.warning("[crud_image_file] refresh(ImageFile) failed; will fallback to query by file_hash", exc_info=True)

    img2 = await get_image_by_hash(db, file_hash)
    out = img2 or db_image
    logger.info(
        f"Created image file record: hash={file_hash[:16]}..., path={file_path}, id={getattr(out, 'id', None)}, "
        f"type={(image_type.value if isinstance(image_type, ImageFileTypeEnum) else image_type)}, original_image_id={original_image_id}"
    )
    return out

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

async def decrement_reference_count_by_path(
    db: AsyncSession,
    file_path: str,
) -> Optional[ImageFile]:
    """根据文件路径减少图片文件的引用计数（用于删除 questions/corrections 记录时）"""
    image_file = await get_image_by_path(db, file_path)
    if not image_file:
        return None
    return await decrement_reference_count(db, image_file.file_hash)

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


async def mark_delete_orphan_question_images(
    db: AsyncSession,
    *,
    user_id: int,
    image_ids: list[int],
) -> list[str]:
    """
    Mark image_files rows (file_type='questions') for deletion if they are no longer referenced
    by any Question.source_image_id for this user.

    Returns:
        A list of file_path strings that should be deleted from disk AFTER the DB commit succeeds.
    """
    if not image_ids:
        return []

    from sqlalchemy import func
    from ..db.models import Question

    file_paths: list[str] = []
    uniq_ids = []
    seen = set()
    for x in image_ids:
        try:
            ix = int(x)
        except Exception:
            continue
        if ix <= 0 or ix in seen:
            continue
        seen.add(ix)
        uniq_ids.append(ix)

    for image_id in uniq_ids:
        img = await get_image_file(db, image_id, user_id)
        if not img:
            continue
        if getattr(img, "file_type", None) != "questions":
            continue

        cnt = (
            await db.execute(
                select(func.count())
                .select_from(Question)
                .where(Question.user_id == int(user_id))
                .where(Question.source_image_id == int(image_id))
            )
        ).scalar_one()
        if int(cnt or 0) > 0:
            continue

        # Mark DB row for deletion; delete file after commit.
        file_paths.append(str(getattr(img, "file_path", "") or ""))
        await db.delete(img)

    await db.flush()
    # Return only non-empty paths
    return [p for p in file_paths if p]


def delete_files_best_effort(file_paths: list[str]) -> dict:
    """
    Delete physical files (best-effort). Intended to be used after a successful DB commit.
    """
    deleted = 0
    failed = 0
    for p in file_paths or []:
        ok = _safe_unlink(p)
        if ok:
            deleted += 1
        else:
            failed += 1
    return {"deleted": deleted, "failed": failed}
