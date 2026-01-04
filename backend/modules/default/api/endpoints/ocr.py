"""
OCR Image Access API - Default Module
图片访问API - 默认模块（统一处理所有学科的图片访问）
"""

import os
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from jose import jwt, JWTError

from backend.modules.default.api.deps import get_db, get_optional_user_id
from backend.modules.default.config import settings
from backend.core.crud import crud_exam_correction, crud_user
from backend.core.utils.file_utils import get_user_directory_name

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/images/corrections/{correction_id}/{image_type}")
async def get_correction_image(
    correction_id: int,
    image_type: str = Path(description="图片类型: 'original' 或 'corrected'"),
    token: Optional[str] = Query(None, description="JWT token (for image tag access)"),
    current_user_id: Optional[int] = Depends(get_optional_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    获取批注图片（通过correction_id和image_type）
    统一由 default 模块处理所有学科的图片访问

    路径格式: /api/v1/ocr/images/corrections/{correction_id}/{image_type}
    image_type: 'original' 或 'corrected'

    安全验证：
    - 通过correction_id查找ExamCorrection记录
    - 验证当前用户是否为批注记录的所有者
    - 根据image_type获取对应的图片ID并返回图片文件
    """
    # 验证image_type
    if image_type not in ["original", "corrected"]:
        raise HTTPException(
            status_code=400,
            detail="image_type必须是'original'或'corrected'"
        )

    # 如果从查询参数提供了token，尝试解析
    if token and current_user_id is None:
        try:
            payload = jwt.decode(
                token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
            )
            user_id_str: str = payload.get("sub")
            if user_id_str:
                current_user_id = int(user_id_str)
        except JWTError as e:
            logger.warning(f"Failed to parse token from query param: {e}")
        except Exception as e:
            logger.warning(f"Failed to parse token from query param: {e}")

    # 获取批注记录
    correction = await crud_exam_correction.get_exam_correction(db, correction_id, None)
    if not correction:
        raise HTTPException(status_code=404, detail="批注记录不存在")

    # 验证用户权限
    if current_user_id is not None:
        if correction.user_id != current_user_id:
            raise HTTPException(
                status_code=403,
                detail="无权访问该批注记录的图像资源"
            )
    else:
        # 没有token的情况
        if not settings.is_development:
            raise HTTPException(
                status_code=401,
                detail="需要认证才能访问图像资源",
                headers={"WWW-Authenticate": "Bearer"},
            )
        logger.warning(f"Correction image access without authentication: correction_id={correction_id}, image_type={image_type}")

    # 根据image_type获取对应的图片文件（直接使用已加载的关联对象）
    if image_type == "original":
        image_file = correction.original_image
        if not image_file:
            logger.error(f"Correction {correction_id} has no original_image (original_image_id={correction.original_image_id})")
            raise HTTPException(status_code=404, detail="原始图片不存在")
        logger.info(f"Getting original image: correction_id={correction_id}, image_id={image_file.id}, file_path={image_file.file_path}")
    else:  # corrected
        image_file = correction.corrected_image
        if not image_file:
            logger.error(f"Correction {correction_id} has no corrected_image (corrected_image_id={correction.corrected_image_id})")
            raise HTTPException(status_code=404, detail="批改后的图片不存在")
        logger.info(f"Getting corrected image: correction_id={correction_id}, image_id={image_file.id}, file_path={image_file.file_path}")

    logger.info(f"Found ImageFile: id={image_file.id}, file_path={image_file.file_path}, image_type={image_file.image_type}")

    # 检查文件是否存在（处理相对路径）
    file_path = image_file.file_path
    original_stored_path = file_path

    # 获取项目根目录
    current_file_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(current_file_dir, "../../../../../"))

    # 尝试多种路径解析方式
    possible_paths = []

    # 1. 如果是绝对路径，直接使用
    if os.path.isabs(file_path):
        possible_paths.append(file_path)
    else:
        # 2. 移除开头的 ./ 或 ./
        normalized = file_path.lstrip("./").lstrip("/")

        # 3. 基于项目根目录
        possible_paths.append(os.path.join(project_root, normalized))

        # 4. 基于当前工作目录
        possible_paths.append(os.path.join(os.getcwd(), normalized))

        # 5. 如果路径包含 data/uploads，尝试直接拼接
        if "data/uploads" in normalized:
            possible_paths.append(os.path.join(project_root, normalized))
            # 移除 data/uploads 前缀，重新拼接
            rel_part = normalized.split("data/uploads/", 1)[-1] if "data/uploads/" in normalized else normalized
            possible_paths.append(os.path.join(project_root, "data", "uploads", rel_part))

    # 尝试每个可能的路径
    found_path = None
    for path in possible_paths:
        if os.path.exists(path):
            found_path = path
            logger.info(f"Found file at: {path} (from stored path: {original_stored_path})")
            break

    if not found_path:
        # 备用方案：尝试根据hash值查找文件
        logger.warning(f"File not found at stored path, trying to find by hash: {image_file.file_hash[:32]}")
        upload_base = os.path.join(project_root, "data", "uploads")

        # 构建可能的目录路径（需要加载user关系）
        user = await crud_user.get_user(db, correction.user_id)
        if not user:
            logger.error(f"User not found: user_id={correction.user_id}")
            raise HTTPException(status_code=404, detail="用户不存在")
        user_dir_name = get_user_directory_name(user.username, user.email)
        possible_dirs = [
            os.path.join(upload_base, user_dir_name, "corrections", correction.subject.value if hasattr(correction.subject, 'value') else str(correction.subject)),
            os.path.join(upload_base, user_dir_name, "corrections", "math"),  # 尝试math目录
            os.path.join(upload_base, user_dir_name, "corrections"),  # 尝试corrections目录
        ]

        # 尝试查找包含hash值的文件
        hash_prefix = image_file.file_hash[:32]
        for search_dir in possible_dirs:
            if os.path.exists(search_dir):
                try:
                    for filename in os.listdir(search_dir):
                        if hash_prefix in filename:
                            candidate_path = os.path.join(search_dir, filename)
                            if os.path.exists(candidate_path):
                                found_path = candidate_path
                                logger.info(f"Found file by hash search: {found_path}")
                                break
                    if found_path:
                        break
                except Exception as e:
                    logger.warning(f"Error searching directory {search_dir}: {e}")

        if not found_path:
            logger.error(f"Image file not found. Stored path: {original_stored_path}, Tried paths: {possible_paths}, Hash search dirs: {possible_dirs}, image_id={image_file.id}, correction_id={correction_id}, image_type={image_type}, file_hash={image_file.file_hash[:32]}")
            raise HTTPException(status_code=404, detail=f"图片文件不存在: {original_stored_path}")

    file_path = found_path

    # 根据文件扩展名确定 MIME 类型
    ext = os.path.splitext(file_path)[1].lower().lstrip('.')
    mime_types = {
        'png': 'image/png',
        'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg',
        'webp': 'image/webp',
        'heic': 'image/heic',
    }
    media_type = mime_types.get(ext, 'image/png')

    return FileResponse(file_path, media_type=media_type)
