"""
Exam Corrections API Endpoints (RPJ模块 - 精简版)
AI批注记录相关API - 仅支持语文、英语、道法
"""

import logging
import json
import os
from typing import Optional, List
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, Path, UploadFile, File, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from backend.modules.rpj.api.deps import get_current_user_id

logger = logging.getLogger(__name__)
router = APIRouter()

# RPJ模块支持的学科
RPJ_SUBJECTS = ["chinese", "english", "morality"]

def validate_rpj_subject(subject: str) -> None:
    """验证学科是否属于RPJ模块支持的学科"""
    if subject.lower() not in RPJ_SUBJECTS:
        raise HTTPException(
            status_code=400,
            detail=f"学科 '{subject}' 不支持RPJ模块。支持的学科: {RPJ_SUBJECTS}"
        )

def get_user_corrections_dir(user_id: int) -> str:
    """获取用户批注记录目录"""
    corrections_dir = f"data/rpj/corrections/user_{user_id}"
    os.makedirs(corrections_dir, exist_ok=True)
    return corrections_dir

def save_correction_file(user_id: int, correction_id: int, filename: str, content: bytes) -> str:
    """保存批注文件"""
    corrections_dir = get_user_corrections_dir(user_id)
    filepath = os.path.join(corrections_dir, filename)

    with open(filepath, 'wb') as f:
        f.write(content)

    return filepath

def load_correction_data(user_id: int, correction_id: int) -> Optional[dict]:
    """加载批注记录数据"""
    corrections_dir = get_user_corrections_dir(user_id)
    data_file = os.path.join(corrections_dir, f"correction_{correction_id}.json")

    if os.path.exists(data_file):
        with open(data_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None

def save_correction_data(user_id: int, correction_id: int, data: dict) -> str:
    """保存批注记录数据"""
    corrections_dir = get_user_corrections_dir(user_id)
    data_file = os.path.join(corrections_dir, f"correction_{correction_id}.json")

    with open(data_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return data_file

# ============ Response Models ============

class CorrectionResponse(BaseModel):
    """批注记录响应"""
    id: int
    user_id: int
    subject: str
    grade: Optional[str]
    exam_title: Optional[str]
    original_image_url: str
    total_score: float
    max_score: float
    accuracy_rate: float
    question_count: int
    overall_analysis: Optional[str]
    created_at: str

class CorrectionListResponse(BaseModel):
    """批注记录列表响应"""
    total: int
    items: List[CorrectionResponse]

class UploadCorrectionResponse(BaseModel):
    """上传批注响应"""
    correction_id: int
    status: str
    message: str

# ============ Core API Endpoints ============

@router.post("/upload", response_model=UploadCorrectionResponse)
async def upload_correction(
    subject: str = Form(..., description="学科: chinese(语文), english(英语), morality(道法)"),
    grade: Optional[str] = Form(None, description="年级"),
    exam_title: Optional[str] = Form(None, description="试卷标题"),
    file: UploadFile = File(..., description="试卷图片"),
    user_id: int = Depends(get_current_user_id),
):
    """
    上传试卷图片进行批注
    支持语文、英语、道法三个学科
    """
    # 验证学科
    validate_rpj_subject(subject)

    # 验证文件类型
    allowed_types = ['image/jpeg', 'image/png', 'image/jpg']
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型。支持: JPEG, PNG"
        )

    try:
        # 生成批注ID
        import time
        correction_id = int(time.time() * 1000) % 10000

        # 保存上传的图片
        content = await file.read()
        image_filename = f"correction_{correction_id}_original.jpg"
        save_correction_file(user_id, correction_id, image_filename, content)

        # 创建批注记录
        correction_data = {
            "id": correction_id,
            "user_id": user_id,
            "subject": subject.lower(),
            "grade": grade,
            "exam_title": exam_title,
            "original_image": image_filename,
            "status": "uploaded",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }

        save_correction_data(user_id, correction_id, correction_data)

        logger.info(f"用户 {user_id} 上传了 {subject} 试卷，批注ID: {correction_id}")

        # 模拟处理结果（在实际应用中应调用Agent处理）
        await simulate_correction_processing(user_id, correction_id, subject)

        return UploadCorrectionResponse(
            correction_id=correction_id,
            status="completed",
            message="试卷批注完成",
        )

    except Exception as e:
        logger.error(f"上传批注失败: {e}")
        raise HTTPException(status_code=500, detail=f"上传失败: {str(e)}")

async def simulate_correction_processing(user_id: int, correction_id: int, subject: str):
    """模拟批注处理过程"""
    import random

    # 加载批注数据
    correction_data = load_correction_data(user_id, correction_id)
    if not correction_data:
        return

    # 模拟处理延迟
    import asyncio
    await asyncio.sleep(1)

    # 生成模拟结果
    subject_scores = {
        "chinese": (random.randint(70, 90), 100),
        "english": (random.randint(65, 85), 100),
        "morality": (random.randint(75, 95), 100),
    }

    total_score, max_score = subject_scores.get(subject.lower(), (80, 100))
    accuracy_rate = total_score / max_score * 100

    # 更新批注数据
    correction_data.update({
        "status": "completed",
        "total_score": total_score,
        "max_score": max_score,
        "accuracy_rate": round(accuracy_rate, 2),
        "question_count": random.randint(10, 20),
        "overall_analysis": f"本次{subject}试卷总体表现良好，建议加强薄弱环节。",
        "updated_at": datetime.now().isoformat(),
    })

    save_correction_data(user_id, correction_id, correction_data)

@router.get("/", response_model=CorrectionListResponse)
async def list_corrections(
    subject: Optional[str] = Query(None, description="学科筛选: chinese, english, morality"),
    user_id: int = Depends(get_current_user_id),
):
    """
    获取批注记录列表
    仅支持语文、英语、道法
    """
    try:
        # 验证学科
        if subject:
            validate_rpj_subject(subject)

        # 获取用户批注目录
        corrections_dir = get_user_corrections_dir(user_id)
        if not os.path.exists(corrections_dir):
            return CorrectionListResponse(total=0, items=[])

        # 加载所有批注记录
        items = []
        for filename in os.listdir(corrections_dir):
            if filename.endswith(".json") and filename.startswith("correction_"):
                filepath = os.path.join(corrections_dir, filename)

                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        correction_data = json.load(f)

                    # 学科筛选
                    if subject and correction_data.get("subject") != subject.lower():
                        continue

                    # 只返回已完成的记录
                    if correction_data.get("status") != "completed":
                        continue

                    # 构建响应
                    correction_id = correction_data.get("id")
                    original_image_url = f"/api/v1/rpj/corrections/{correction_id}/image/original"

                    items.append(CorrectionResponse(
                        id=correction_id,
                        user_id=correction_data.get("user_id"),
                        subject=correction_data.get("subject"),
                        grade=correction_data.get("grade"),
                        exam_title=correction_data.get("exam_title"),
                        original_image_url=original_image_url,
                        total_score=correction_data.get("total_score", 0.0),
                        max_score=correction_data.get("max_score", 100.0),
                        accuracy_rate=correction_data.get("accuracy_rate", 0.0),
                        question_count=correction_data.get("question_count", 0),
                        overall_analysis=correction_data.get("overall_analysis"),
                        created_at=correction_data.get("created_at", ""),
                    ))

                except Exception as e:
                    logger.warning(f"加载批注文件失败 {filepath}: {e}")

        # 按创建时间倒序排序
        items.sort(key=lambda x: x.created_at, reverse=True)

        return CorrectionListResponse(total=len(items), items=items)

    except Exception as e:
        logger.error(f"获取批注列表失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取批注列表失败: {str(e)}")

@router.get("/{correction_id}", response_model=CorrectionResponse)
async def get_correction(
    correction_id: int = Path(..., description="批注记录ID"),
    user_id: int = Depends(get_current_user_id),
):
    """获取单个批注记录详情"""
    try:
        correction_data = load_correction_data(user_id, correction_id)

        if not correction_data:
            raise HTTPException(status_code=404, detail="批注记录不存在")

        if correction_data.get("status") != "completed":
            raise HTTPException(status_code=400, detail="批注尚未处理完成")

        # 构建响应
        original_image_url = f"/api/v1/rpj/corrections/{correction_id}/image/original"

        return CorrectionResponse(
            id=correction_data.get("id"),
            user_id=correction_data.get("user_id"),
            subject=correction_data.get("subject"),
            grade=correction_data.get("grade"),
            exam_title=correction_data.get("exam_title"),
            original_image_url=original_image_url,
            total_score=correction_data.get("total_score", 0.0),
            max_score=correction_data.get("max_score", 100.0),
            accuracy_rate=correction_data.get("accuracy_rate", 0.0),
            question_count=correction_data.get("question_count", 0),
            overall_analysis=correction_data.get("overall_analysis"),
            created_at=correction_data.get("created_at", ""),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取批注详情失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取批注详情失败: {str(e)}")

@router.get("/{correction_id}/image/original")
async def get_correction_image(
    correction_id: int = Path(..., description="批注记录ID"),
    user_id: int = Depends(get_current_user_id),
):
    """获取批注原始图片"""
    try:
        corrections_dir = get_user_corrections_dir(user_id)
        image_filename = f"correction_{correction_id}_original.jpg"
        image_path = os.path.join(corrections_dir, image_filename)

        if os.path.exists(image_path):
            return FileResponse(
                image_path,
                media_type="image/jpeg",
                filename=image_filename
            )
        else:
            raise HTTPException(status_code=404, detail="图片不存在")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取批注图片失败: {e}")
        raise HTTPException(status_code=500, detail=f"获取图片失败: {str(e)}")

@router.delete("/{correction_id}", status_code=204)
async def delete_correction(
    correction_id: int = Path(..., description="批注记录ID"),
    user_id: int = Depends(get_current_user_id),
):
    """删除批注记录"""
    try:
        corrections_dir = get_user_corrections_dir(user_id)

        # 删除数据文件
        data_file = os.path.join(corrections_dir, f"correction_{correction_id}.json")
        if os.path.exists(data_file):
            os.remove(data_file)

        # 删除图片文件
        image_file = os.path.join(corrections_dir, f"correction_{correction_id}_original.jpg")
        if os.path.exists(image_file):
            os.remove(image_file)

        logger.info(f"用户 {user_id} 删除了批注记录 {correction_id}")

    except Exception as e:
        logger.error(f"删除批注记录失败: {e}")
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")
