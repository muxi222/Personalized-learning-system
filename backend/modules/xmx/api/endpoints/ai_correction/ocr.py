"""
XMX 模块 - OCR 顺序写入 · TONY 100% 对齐最终版（已修复）
"""

import os
import time
import hashlib
import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException

from backend.modules.xmx.api.deps import get_current_user, get_db
from backend.core.db.models import (
    User,
    SubjectEnum,
    ImageFileTypeEnum,
)
from backend.core.services.gemini_ocr_service import GeminiOCRService, SubjectType
from backend.core.crud import crud_image_file
from backend.core.crud.crud_exam_correction import create_exam_correction
from backend.core.utils.file_utils import (
    get_user_upload_dir,
    get_user_directory_name,
)

logger = logging.getLogger(__name__)
router = APIRouter()

UPLOAD_ROOT = "data/uploads"


# ================= 工具函数 =================

def calculate_file_hash(content: bytes) -> str:
    return hashlib.md5(content).hexdigest()


def to_dict_safe(obj: Any) -> Dict[str, Any]:
    if obj is None:
        return {}
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "dict"):
        return obj.dict()
    if hasattr(obj, "__dict__"):
        return vars(obj)
    return {"raw": str(obj)}


# ================= API =================

@router.post("/analyze")
async def analyze_exam_image(
    file: UploadFile = File(...),
    subject: str = Form("economics"),
    grade: str = Form(""),
    db=Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    t0 = time.time()

    # ---------- 1. 学科解析（TONY 规则） ----------
    try:
        subject_en = subject.lower()
        subject_enum = SubjectEnum[subject.upper()]
        subject_type = SubjectType(subject_en)
    except Exception:
        subject_en = "other"
        subject_enum = SubjectEnum.OTHER
        subject_type = SubjectType.OTHER

    # ---------- 2. 读取文件 ----------
    content = await file.read()
    file_hash = calculate_file_hash(content)
    file_size = len(content)
    mime_type = file.content_type or "image/png"

    ext = os.path.splitext(file.filename or "")[1].lower() or ".png"
    filename = f"{file_hash[:32]}{ext}"

    # ---------- 3. 路径（TONY 规范） ----------
    upload_dir = get_user_upload_dir(
        UPLOAD_ROOT,
        current_user,
        "corrections",
        subject_en,
    )
    os.makedirs(upload_dir, exist_ok=True)

    abs_path = os.path.join(upload_dir, filename)

    relative_path = os.path.relpath(abs_path, os.path.abspath(".")).lstrip("./")
    if not relative_path.startswith("data/uploads"):
        user_dir = get_user_directory_name(
            current_user.username, current_user.email
        )
        relative_path = (
            f"data/uploads/{user_dir}/corrections/{subject_en}/{filename}"
        )

    # ---------- 4. 写入磁盘 ----------
    if not os.path.exists(abs_path):
        with open(abs_path, "wb") as f:
            f.write(content)

    # ---------- 5. OCR（无 DB） ----------
    try:
        ocr_service = GeminiOCRService()
        result = await ocr_service.analyze_exam_image(
            image_path=abs_path,
            subject=subject_type,
        )
    except Exception as e:
        logger.exception("OCR failed")
        raise HTTPException(status_code=500, detail=f"OCR失败: {e}")

    # ================= DB 顺序写入 =================
    try:
        # ===== Step 1: 原始 ImageFile =====
        original_image = await crud_image_file.create_image_file(
            db=db,
            file_hash=file_hash,
            user_id=current_user.id,
            file_type="corrections",
            subject=subject_en,   # 字符串（TONY）
            file_path=relative_path,
            file_size=file_size,
            mime_type=mime_type,
            image_type=ImageFileTypeEnum.ORIGINAL,
        )
        await db.commit()
        await db.refresh(original_image)

        # ===== Step 2: 批改图 ImageFile =====
        corrected_image = None
        if getattr(result, "corrected_image_path", None):
            with open(result.corrected_image_path, "rb") as f:
                corr_bytes = f.read()

            corr_hash = calculate_file_hash(corr_bytes)
            corr_filename = f"{corr_hash[:32]}.png"
            corr_abs_path = os.path.join(upload_dir, corr_filename)

            with open(corr_abs_path, "wb") as f:
                f.write(corr_bytes)

            corr_rel_path = os.path.relpath(
                corr_abs_path, os.path.abspath(".")
            ).lstrip("./")

            corrected_image = await crud_image_file.create_image_file(
                db=db,
                file_hash=corr_hash,
                user_id=current_user.id,
                file_type="corrections",
                subject=subject_en,
                file_path=corr_rel_path,
                file_size=len(corr_bytes),
                mime_type="image/png",
                image_type=ImageFileTypeEnum.CORRECTED,
                original_image_id=original_image.id,
            )
            await db.commit()
            await db.refresh(corrected_image)

            # ⭐ TONY 行为：原图引用 +1
            await crud_image_file.increment_reference_count(
                db, original_image.id
            )
            await db.commit()

        # ===== Step 3: ExamCorrection =====
        questions_detail = [to_dict_safe(q) for q in result.questions]

        exam_title = (
            getattr(result, "exam_title", None)
            or grade
            or f"{subject_en}试卷批改"
        )

        correction = await create_exam_correction(
            db=db,
            user_id=current_user.id,
            subject=subject_type,   # SubjectType（TONY）
            grade=grade or getattr(result, "grade", ""),
            exam_title=exam_title,
            original_image_id=original_image.id,
            corrected_image_id=corrected_image.id if corrected_image else None,
            total_score=float(getattr(result, "total_score", 0.0)),
            max_score=float(getattr(result, "max_score", 100.0)),
            accuracy_rate=float(getattr(result, "accuracy_rate", 0.0)),
            question_count=len(questions_detail),
            correct_count=sum(1 for q in questions_detail if q.get("is_correct")),
            wrong_count=sum(1 for q in questions_detail if not q.get("is_correct")),
            overall_analysis=getattr(result, "overall_analysis", None),
            weak_points=getattr(result, "weak_points", []),
            improvement_suggestions=getattr(result, "improvement_suggestions", []),
            questions_detail=questions_detail,
        )
        await db.commit()

        # ===== Response（TONY 对齐）=====
        return {
            "success": True,
            "data": {
                "task_id": correction.id,
                "subject": subject_en,
                "grade": correction.grade,
                "total_score": correction.total_score,
                "max_score": correction.max_score,
                "accuracy_rate": correction.accuracy_rate,
                "questions": questions_detail,
                "overall_analysis": correction.overall_analysis,
                "weak_points": correction.weak_points,
                "improvement_suggestions": correction.improvement_suggestions,
                "corrected_image_url": (
                    corrected_image.file_path if corrected_image else None
                ),
                "is_duplicate": False,
                "duplicate_message": None,
            },
        }

    except Exception as e:
        await db.rollback()
        logger.exception("XMX OCR DB pipeline failed")
        raise HTTPException(status_code=500, detail=f"数据库写入失败: {e}")
