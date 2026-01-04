"""
图片文件服务API (RPJ模块 - 学生实现版本)

本文件为框架代码，需要学生完成核心业务逻辑的实现。
完整实现请参考: backend/modules/tony/api/endpoints/image_files.py

RPJ模块支持的学科: chinese, english, morality
"""

import logging
import os
import json
import shutil
import hashlib
from typing import Optional, List
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Path, UploadFile, File, Form
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from backend.modules.rpj.api.deps import get_current_user_id
from backend.modules.rpj.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

# RPJ模块支持的学科
RPJ_SUBJECTS = ["chinese", "english", "morality"]

def validate_rpj_subject(subject: str) -> None:
    """验证学科是否属于RPJ模块"""
    if subject.lower() not in RPJ_SUBJECTS:
        raise HTTPException(
            status_code=400,
            detail=f"学科 '{subject}' 不支持RPJ模块。支持的学科: {RPJ_SUBJECTS}"
        )

def get_user_images_dir(user_id: int) -> str:
    """获取用户图片目录"""
    images_dir = f"data/rpj/images/user_{user_id}"
    os.makedirs(images_dir, exist_ok=True)
    return images_dir

def get_image_metadata_path(user_id: int, image_id: int) -> str:
    """获取图片元数据文件路径"""
    images_dir = get_user_images_dir(user_id)
    return os.path.join(images_dir, f"image_{image_id}.json")

def load_image_metadata(user_id: int, image_id: int) -> Optional[dict]:
    """加载图片元数据"""
    metadata_path = get_image_metadata_path(user_id, image_id)

    if os.path.exists(metadata_path):
        with open(metadata_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None

def save_image_metadata(user_id: int, image_id: int, metadata: dict) -> str:
    """保存图片元数据"""
    metadata_path = get_image_metadata_path(user_id, image_id)

    with open(metadata_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    return metadata_path

def get_image_file_path(user_id: int, image_id: int, image_type: str = "original") -> str:
    """获取图片文件路径"""
    images_dir = get_user_images_dir(user_id)
    filename = f"image_{image_id}_{image_type}.jpg"
    return os.path.join(images_dir, filename)

def generate_image_id(user_id: int) -> int:
    """生成图片ID"""
    import time
    timestamp = int(time.time() * 1000)
    return (timestamp % 1000000 + user_id % 1000) % 10000

def get_image_url(image_id: int, image_type: str = "original") -> str:
    """生成图片访问URL"""
    return f"/api/v1/rpj/images/{image_id}?type={image_type}"

# ============ Response Models ============

class ImageFileResponse(BaseModel):
    """图片文件响应"""
    id: int
    user_id: int
    subject: str
    image_type: str = "original"  # original, corrected
    file_type: str = "corrections"  # corrections, questions
    file_path: str
    file_size: int
    mime_type: str = "image/jpeg"
    reference_count: int = 0
    created_at: str
    updated_at: str

    # 关联信息
    related_corrections_count: int = 0
    has_derived_images: bool = False
    image_url: Optional[str] = None

class ImageFileListResponse(BaseModel):
    """图片文件列表响应"""
    total: int
    items: List[ImageFileResponse]

class UploadImageResponse(BaseModel):
    """上传图片响应"""
    id: int
    subject: str
    image_type: str
    file_type: str
    file_path: str
    file_size: int
    mime_type: str
    created_at: str
    image_url: str

class ImageUsageStats(BaseModel):
    """图片使用统计"""
    total_images: int
    total_size_mb: float
    by_subject: dict
    by_image_type: dict
    by_file_type: dict
    recent_uploads: List[dict]

# ============ Core API Endpoints ============

@router.get("/", response_model=ImageFileListResponse)
async def list_image_files(
    subject: Optional[str] = Query(None, description="学科筛选: chinese, english, morality"),
    image_type: Optional[str] = Query(None, description="图片类型: original, corrected"),
    file_type: Optional[str] = Query(None, description="文件类型: corrections, questions"),
    user_id: int = Depends(get_current_user_id),
):
    """
    获取用户的图片文件列表

    仅支持语文、英语、道法学科的图片
    """
    try:
        # 验证学科
        if subject:
            validate_rpj_subject(subject)

        # 获取用户图片目录
        images_dir = get_user_images_dir(user_id)
        if not os.path.exists(images_dir):
            return ImageFileListResponse(total=0, items=[])

        # 加载所有图片元数据
        all_images = []

        for filename in os.listdir(images_dir):
            if filename.endswith(".json") and filename.startswith("image_"):
                filepath = os.path.join(images_dir, filename)

                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        image_data = json.load(f)

                    # 学科筛选
                    if subject and image_data.get("subject") != subject.lower():
                        continue

                    # 图片类型筛选
                    if image_type and image_data.get("image_type") != image_type:
                        continue

                    # 文件类型筛选
                    if file_type and image_data.get("file_type") != file_type:
                        continue

                    # 检查图片文件是否存在
                    img_path = image_data.get("file_path", "")
                    if not os.path.exists(img_path):
                        continue

                    # 获取文件大小
                    if "file_size" not in image_data:
                        try:
                            image_data["file_size"] = os.path.getsize(img_path)
                        except:
                            image_data["file_size"] = 0

                    # 生成图片URL
                    image_data["image_url"] = get_image_url(
                        image_data.get("id"),
                        image_data.get("image_type", "original")
                    )

                    # 统计关联的批注记录（从批注数据中查找）
                    corrections_dir = f"data/rpj/corrections/user_{user_id}"
                    related_corrections = 0
                    has_derived = False

                    if os.path.exists(corrections_dir):
                        for correction_file in os.listdir(corrections_dir):
                            if correction_file.endswith(".json") and correction_file.startswith("correction_"):
                                correction_path = os.path.join(corrections_dir, correction_file)
                                try:
                                    with open(correction_path, 'r', encoding='utf-8') as cf:
                                        correction_data = json.load(cf)

                                    # 检查是否关联
                                    original_image = correction_data.get("original_image", "")
                                    if f"image_{image_data.get('id')}_original.jpg" in original_image:
                                        related_corrections += 1

                                    # 检查是否有派生图片
                                    corrected_image = correction_data.get("corrected_image", "")
                                    if corrected_image:
                                        has_derived = True

                                except Exception as e:
                                    logger.warning(f"加载批注文件失败 {correction_path}: {e}")

                    image_data["related_corrections_count"] = related_corrections
                    image_data["has_derived_images"] = has_derived

                    all_images.append(image_data)

                except Exception as e:
                    logger.warning(f"加载图片元数据失败 {filepath}: {e}")

        # 按创建时间倒序排序
        all_images.sort(key=lambda x: x.get("created_at", ""), reverse=True)

        # 构建响应
        items = []
        for image_data in all_images:
            items.append(ImageFileResponse(
                id=image_data.get("id"),
                user_id=image_data.get("user_id", user_id),
                subject=image_data.get("subject", ""),
                image_type=image_data.get("image_type", "original"),
                file_type=image_data.get("file_type", "corrections"),
                file_path=image_data.get("file_path", ""),
                file_size=image_data.get("file_size", 0),
                mime_type=image_data.get("mime_type", "image/jpeg"),
                reference_count=image_data.get("reference_count", 0),
                created_at=image_data.get("created_at", ""),
                updated_at=image_data.get("updated_at", ""),
                related_corrections_count=image_data.get("related_corrections_count", 0),
                has_derived_images=image_data.get("has_derived_images", False),
                image_url=image_data.get("image_url"),
            ))

        return ImageFileListResponse(total=len(items), items=items)

    except Exception as e:
        logger.error(f"获取图片列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取图片列表失败: {str(e)}")

@router.get("/{image_id}", response_model=ImageFileResponse)
async def get_image_file_detail(
    image_id: int = Path(..., description="图片ID"),
    user_id: int = Depends(get_current_user_id),
):
    """获取图片文件详情"""
    try:
        image_data = load_image_metadata(user_id, image_id)

        if not image_data:
            raise HTTPException(status_code=404, detail="图片文件不存在")

        # 验证学科
        subject = image_data.get("subject", "")
        if subject:
            validate_rpj_subject(subject)

        # 检查图片文件是否存在
        img_path = image_data.get("file_path", "")
        if not os.path.exists(img_path):
            raise HTTPException(status_code=404, detail="图片文件已丢失")

        # 更新文件大小
        try:
            image_data["file_size"] = os.path.getsize(img_path)
        except:
            image_data["file_size"] = 0

        # 生成图片URL
        image_data["image_url"] = get_image_url(
            image_data.get("id"),
            image_data.get("image_type", "original")
        )

        # 统计关联的批注记录
        corrections_dir = f"data/rpj/corrections/user_{user_id}"
        related_corrections = 0
        has_derived = False

        if os.path.exists(corrections_dir):
            for correction_file in os.listdir(corrections_dir):
                if correction_file.endswith(".json") and correction_file.startswith("correction_"):
                    correction_path = os.path.join(corrections_dir, correction_file)
                    try:
                        with open(correction_path, 'r', encoding='utf-8') as cf:
                            correction_data = json.load(cf)

                        # 检查是否关联
                        original_image = correction_data.get("original_image", "")
                        if f"image_{image_id}_original.jpg" in original_image:
                            related_corrections += 1

                        # 检查是否有派生图片
                        corrected_image = correction_data.get("corrected_image", "")
                        if corrected_image:
                            has_derived = True

                    except Exception as e:
                        logger.warning(f"加载批注文件失败 {correction_path}: {e}")

        return ImageFileResponse(
            id=image_data.get("id"),
            user_id=image_data.get("user_id", user_id),
            subject=image_data.get("subject", ""),
            image_type=image_data.get("image_type", "original"),
            file_type=image_data.get("file_type", "corrections"),
            file_path=image_data.get("file_path", ""),
            file_size=image_data.get("file_size", 0),
            mime_type=image_data.get("mime_type", "image/jpeg"),
            reference_count=image_data.get("reference_count", 0),
            created_at=image_data.get("created_at", ""),
            updated_at=image_data.get("updated_at", ""),
            related_corrections_count=related_corrections,
            has_derived_images=has_derived,
            image_url=image_data.get("image_url"),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取图片详情失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取图片详情失败: {str(e)}")

@router.delete("/{image_id}", status_code=204)
async def delete_image_file(
    image_id: int = Path(..., description="图片ID"),
    user_id: int = Depends(get_current_user_id),
):
    """删除图片文件"""
    try:
        # 加载图片元数据
        image_data = load_image_metadata(user_id, image_id)

        if not image_data:
            raise HTTPException(status_code=404, detail="图片文件不存在")

        # 验证学科
        subject = image_data.get("subject", "")
        if subject:
            validate_rpj_subject(subject)

        # 检查是否被批注记录引用
        corrections_dir = f"data/rpj/corrections/user_{user_id}"
        referenced_count = 0

        if os.path.exists(corrections_dir):
            for correction_file in os.listdir(corrections_dir):
                if correction_file.endswith(".json") and correction_file.startswith("correction_"):
                    correction_path = os.path.join(corrections_dir, correction_file)
                    try:
                        with open(correction_path, 'r', encoding='utf-8') as cf:
                            correction_data = json.load(cf)

                        # 检查是否引用
                        original_image = correction_data.get("original_image", "")
                        corrected_image = correction_data.get("corrected_image", "")

                        if f"image_{image_id}_original.jpg" in original_image:
                            referenced_count += 1
                        if f"image_{image_id}_corrected.jpg" in corrected_image:
                            referenced_count += 1

                    except Exception as e:
                        logger.warning(f"检查批注引用失败 {correction_path}: {e}")

        if referenced_count > 0:
            raise HTTPException(
                status_code=400,
                detail=f"图片被{referenced_count}条批注记录引用，无法删除"
            )

        # 删除图片文件
        img_path = image_data.get("file_path", "")
        if img_path and os.path.exists(img_path):
            os.remove(img_path)

        # 删除元数据文件
        metadata_path = get_image_metadata_path(user_id, image_id)
        if os.path.exists(metadata_path):
            os.remove(metadata_path)

        # 如果删除的是原始图片，尝试删除对应的批改后图片
        if image_data.get("image_type") == "original":
            corrected_path = get_image_file_path(user_id, image_id, "corrected")
            if os.path.exists(corrected_path):
                os.remove(corrected_path)

            corrected_metadata = get_image_metadata_path(user_id, image_id)  # 假设批改后图片使用相同ID
            if os.path.exists(corrected_metadata):
                os.remove(corrected_metadata)

        logger.info(f"用户 {user_id} 删除了图片文件 {image_id}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"删除图片文件失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除图片失败: {str(e)}")

@router.get("/{image_id}/download")
async def download_image_file(
    image_id: int = Path(..., description="图片ID"),
    image_type: str = Query("original", description="图片类型: original, corrected"),
    user_id: int = Depends(get_current_user_id),
):
    """下载图片文件"""
    try:
        # 加载图片元数据
        image_data = load_image_metadata(user_id, image_id)

        if not image_data:
            raise HTTPException(status_code=404, detail="图片文件不存在")

        # 验证学科
        subject = image_data.get("subject", "")
        if subject:
            validate_rpj_subject(subject)

        # 获取图片文件路径
        img_path = get_image_file_path(user_id, image_id, image_type)

        if not os.path.exists(img_path):
            raise HTTPException(status_code=404, detail="图片文件不存在")

        # 返回文件
        filename = os.path.basename(img_path)

        return FileResponse(
            path=img_path,
            filename=filename,
            media_type=image_data.get("mime_type", "image/jpeg")
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"下载图片文件失败: {e}")
        raise HTTPException(status_code=500, detail=f"下载图片失败: {str(e)}")

@router.post("/upload", response_model=UploadImageResponse)
async def upload_image_file(
    subject: str = Form(..., description="学科: chinese, english, morality"),
    file_type: str = Form("corrections", description="文件类型: corrections, questions"),
    image_type: str = Form("original", description="图片类型: original, corrected"),
    original_image_id: Optional[int] = Form(None, description="原始图片ID（仅当image_type=corrected时）"),
    file: UploadFile = File(..., description="图片文件"),
    user_id: int = Depends(get_current_user_id),
):
    """
    上传图片文件

    支持上传原始图片和批改后的图片
    仅支持语文、英语、道法学科
    """
    try:
        # 验证学科
        validate_rpj_subject(subject)

        # 验证文件类型
        if file_type not in ["corrections", "questions"]:
            raise HTTPException(status_code=400, detail="文件类型必须是corrections或questions")

        # 验证图片类型
        if image_type not in ["original", "corrected"]:
            raise HTTPException(status_code=400, detail="图片类型必须是original或corrected")

        # 如果是批改后的图片，验证原始图片
        if image_type == "corrected" and original_image_id:
            original_data = load_image_metadata(user_id, original_image_id)
            if not original_data:
                raise HTTPException(status_code=404, detail="原始图片不存在")

            if original_data.get("subject") != subject:
                raise HTTPException(status_code=400, detail="原始图片学科不匹配")

        # 验证文件类型
        allowed_types = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif']
        if file.content_type not in allowed_types:
            raise HTTPException(
                status_code=400,
                detail=f"不支持的文件类型。支持: JPEG, PNG, GIF"
            )

        # 读取文件内容
        content = await file.read()
        file_size = len(content)

        # 生成文件哈希
        file_hash = hashlib.md5(content).hexdigest()

        # 检查是否已存在相同文件（通过哈希）
        images_dir = get_user_images_dir(user_id)
        existing_image_id = None

        for filename in os.listdir(images_dir):
            if filename.endswith(".json") and filename.startswith("image_"):
                filepath = os.path.join(images_dir, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        img_data = json.load(f)

                    if img_data.get("file_hash") == file_hash:
                        existing_image_id = img_data.get("id")
                        break
                except:
                    pass

        # 如果文件已存在，增加引用计数
        if existing_image_id:
            existing_data = load_image_metadata(user_id, existing_image_id)
            if existing_data:
                existing_data["reference_count"] = existing_data.get("reference_count", 0) + 1
                existing_data["updated_at"] = datetime.now().isoformat()
                save_image_metadata(user_id, existing_image_id, existing_data)

                return UploadImageResponse(
                    id=existing_image_id,
                    subject=existing_data.get("subject", subject),
                    image_type=existing_data.get("image_type", image_type),
                    file_type=existing_data.get("file_type", file_type),
                    file_path=existing_data.get("file_path", ""),
                    file_size=existing_data.get("file_size", file_size),
                    mime_type=existing_data.get("mime_type", file.content_type),
                    created_at=existing_data.get("created_at", ""),
                    image_url=get_image_url(existing_image_id, image_type),
                )

        # 生成新的图片ID
        image_id = generate_image_id(user_id)

        # 保存图片文件
        img_path = get_image_file_path(user_id, image_id, image_type)
        with open(img_path, 'wb') as f:
            f.write(content)

        # 创建元数据
        metadata = {
            "id": image_id,
            "user_id": user_id,
            "subject": subject.lower(),
            "image_type": image_type,
            "file_type": file_type,
            "file_hash": file_hash,
            "file_path": img_path,
            "file_size": file_size,
            "mime_type": file.content_type,
            "reference_count": 1,
            "original_image_id": original_image_id,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }

        save_image_metadata(user_id, image_id, metadata)

        logger.info(f"用户 {user_id} 上传了 {subject} 图片，ID: {image_id}, 大小: {file_size}字节")

        return UploadImageResponse(
            id=image_id,
            subject=subject,
            image_type=image_type,
            file_type=file_type,
            file_path=img_path,
            file_size=file_size,
            mime_type=file.content_type,
            created_at=metadata["created_at"],
            image_url=get_image_url(image_id, image_type),
        )

    except Exception as e:
        logger.error(f"上传图片文件失败: {e}")
        raise HTTPException(status_code=500, detail=f"上传图片失败: {str(e)}")

@router.get("/stats/usage", response_model=ImageUsageStats)
async def get_image_usage_stats(
    subject: Optional[str] = Query(None, description="学科筛选: chinese, english, morality"),
    days: int = Query(30, ge=1, le=365, description="统计天数"),
    user_id: int = Depends(get_current_user_id),
):
    """
    获取图片使用统计

    统计用户的图片使用情况
    仅统计语文、英语、道法学科的图片
    """
    try:
        # 验证学科
        if subject:
            validate_rpj_subject(subject)

        # 获取用户图片目录
        images_dir = get_user_images_dir(user_id)
        if not os.path.exists(images_dir):
            return ImageUsageStats(
                total_images=0,
                total_size_mb=0.0,
                by_subject={},
                by_image_type={},
                by_file_type={},
                recent_uploads=[]
            )

        # 初始化统计
        total_images = 0
        total_size = 0
        by_subject = {"chinese": 0, "english": 0, "morality": 0}
        by_image_type = {"original": 0, "corrected": 0}
        by_file_type = {"corrections": 0, "questions": 0}
        recent_uploads = []

        # 计算截止日期
        cutoff_date = datetime.now() - timedelta(days=days)

        # 遍历所有图片元数据
        for filename in os.listdir(images_dir):
            if filename.endswith(".json") and filename.startswith("image_"):
                filepath = os.path.join(images_dir, filename)

                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        image_data = json.load(f)

                    # 学科筛选
                    img_subject = image_data.get("subject", "")
                    if subject and img_subject != subject:
                        continue

                    # 日期筛选
                    created_at = image_data.get("created_at", "")
                    if created_at:
                        try:
                            img_date = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                            if img_date < cutoff_date:
                                continue
                        except:
                            pass

                    total_images += 1

                    # 文件大小
                    file_size = image_data.get("file_size", 0)
                    total_size += file_size

                    # 学科统计
                    if img_subject in by_subject:
                        by_subject[img_subject] += 1

                    # 图片类型统计
                    img_type = image_data.get("image_type", "original")
                    by_image_type[img_type] = by_image_type.get(img_type, 0) + 1

                    # 文件类型统计
                    file_type = image_data.get("file_type", "corrections")
                    by_file_type[file_type] = by_file_type.get(file_type, 0) + 1

                    # 最近上传
                    recent_uploads.append({
                        "id": image_data.get("id"),
                        "subject": img_subject,
                        "image_type": img_type,
                        "file_type": file_type,
                        "file_size_mb": round(file_size / (1024 * 1024), 2),
                        "created_at": created_at,
                        "image_url": get_image_url(image_data.get("id"), img_type),
                    })

                except Exception as e:
                    logger.warning(f"处理图片统计失败 {filepath}: {e}")

        # 按上传时间排序
        recent_uploads.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        recent_uploads = recent_uploads[:10]  # 只保留最近10条

        return ImageUsageStats(
            total_images=total_images,
            total_size_mb=round(total_size / (1024 * 1024), 2),
            by_subject=by_subject,
            by_image_type=by_image_type,
            by_file_type=by_file_type,
            recent_uploads=recent_uploads
        )

    except Exception as e:
        logger.error(f"获取图片统计失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取图片统计失败: {str(e)}")
