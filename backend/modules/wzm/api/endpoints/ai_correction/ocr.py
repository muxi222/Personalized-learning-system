"""
OCR API 端点 - 试卷分析与批改 (化学专用版 / Chemistry Only) - Fixed

功能:
1. 上传试卷图片进行 OCR 分析
2. 强制校验学科：仅支持化学 (Chemistry)
3. 自动批改并打分
4. 修复 file_ext 作用域错误
5. 修复 Pydantic dict() 兼容性问题
"""

import os
import uuid
import logging
import shutil
import asyncio
import base64
from typing import Optional, List, Dict, Any
from pathlib import Path

# 引入异步文件操作库
try:
    import aiofiles
except ImportError:
    aiofiles = None

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends, Query, Path as PathParam
from fastapi.responses import FileResponse, JSONResponse
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from jose import jwt, JWTError

# 内部模块导入
from backend.modules.wzm.api.deps import get_current_user, get_optional_user_id, get_db
from backend.modules.wzm.config import settings
from backend.modules.wzm.services.gemini_ocr_service import (
    get_gemini_ocr_service,
    SubjectType,
    ExamAnalysisResult,
)
from backend.core.db.models import User, ImageFileTypeEnum, ExamCorrection, QuestionSourceEnum, Question
from backend.core.utils.file_utils import (
    get_user_directory_name,
    calculate_file_hash,
)
from backend.core.crud import crud_image_file, crud_exam_correction, crud_user

logger = logging.getLogger(__name__)
router = APIRouter()

# --- 配置常量 ---
PROJECT_ROOT = Path(__file__).resolve().parents[5]
UPLOAD_ROOT = Path("./data/uploads")
ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic"}

# 仅支持的学科标识
TARGET_SUBJECT_EN = "chemistry"
TARGET_SUBJECT_CN = "化学"

# 学科映射
SUBJECT_NAME_MAP = {
    "化学": "chemistry", 
    "chemistry": "chemistry",
    "其他": "other",
    "other": "other"
}

# --- 知识体系配置 ---
CHAPTER_TAXONOMY = {
    "chemistry": ["物质结构", "化学反应原理", "无机化学", "有机化学", "实验与探究", "计算与守恒", "综合"],
    "other": ["综合"]
}

KNOWLEDGE_POINT_TAXONOMY = {
    "chemistry": ["氧化还原", "化学平衡", "电化学", "酸碱盐", "物质结构与性质", "官能团与有机反应", "实验操作与安全", "离子反应", "化学计量"],
}

# --- Pydantic Models ---

class OCRAnalysisResponse(BaseModel):
    success: bool
    task_id: str
    subject: str
    grade: str
    total_score: float
    max_score: float
    accuracy_rate: float
    questions: list
    overall_analysis: str
    weak_points: list
    improvement_suggestions: list
    corrected_image_url: Optional[str] = None
    is_duplicate: bool = False
    duplicate_message: Optional[str] = None
    filename: Optional[str] = None

# --- 辅助函数 ---

async def save_file_async(content: bytes, file_path: Path):
    """异步保存文件"""
    try:
        if not file_path.parent.exists():
            file_path.parent.mkdir(parents=True, exist_ok=True)
        
        if aiofiles is None:
            with open(file_path, "wb") as f:
                f.write(content)
        else:
            async with aiofiles.open(file_path, "wb") as f:
                await f.write(content)
    except Exception as e:
        logger.error(f"File save failed: {e}")
        raise HTTPException(status_code=500, detail="文件保存失败")

def get_clean_relative_path(full_path: Path) -> str:
    """将路径转换为相对于 uploads 目录的清洁路径"""
    try:
        return str(full_path.relative_to(UPLOAD_ROOT))
    except ValueError:
        parts = full_path.parts
        if "uploads" in parts:
            idx = parts.index("uploads")
            if idx + 1 < len(parts):
                return str(Path(*parts[idx+1:]))
        return full_path.name

def generate_api_url(path: str) -> str:
    return f"/api/v1/ocr{path}"

async def verify_image_access(
    token: Optional[str] = Query(None),
    current_user_id: Optional[int] = Depends(get_optional_user_id),
) -> int:
    if current_user_id is not None:
        return current_user_id
    if token:
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            user_id_str: str = payload.get("sub")
            if user_id_str:
                return int(user_id_str)
        except JWTError:
            pass
    if settings.is_development:
        return -1
    raise HTTPException(status_code=401, detail="Authentication required")

# --- 核心业务逻辑 ---

async def _process_single_image(
    db: AsyncSession,
    user: User,
    file_content: bytes,
    filename: str,
    mime_type: str,
    user_selected_subject: str,
    grade: str,
    hint: Optional[str]
) -> OCRAnalysisResponse:
    """
    核心处理函数
    """
    # 1. 校验输入学科
    subject_en = SUBJECT_NAME_MAP.get(user_selected_subject, "unknown")
    if subject_en == "unknown":
        raise HTTPException(
            status_code=400, 
            detail=f"仅支持化学学科。不支持的学科输入: {user_selected_subject}"
        )

    file_hash = calculate_file_hash(file_content)
    task_id = str(uuid.uuid4())
    save_subject_dir = TARGET_SUBJECT_EN
    
    # [修复] 提取文件扩展名提到最前，确保在任何分支都能访问
    file_ext = filename.split(".")[-1] if "." in filename else "jpg"

    user_dir_name = get_user_directory_name(user.username, user.email)
    base_save_dir = UPLOAD_ROOT / user_dir_name / "corrections" / save_subject_dir
    
    # 2. 检查重复
    existing_image = await crud_image_file.get_image_by_hash(db, file_hash)
    is_duplicate = False
    original_image_file = None
    files_to_rollback = []

    if existing_image and existing_image.user_id == user.id:
        is_duplicate = True
        original_image_file = existing_image
        file_path_obj = UPLOAD_ROOT / existing_image.file_path
        await crud_image_file.increment_reference_count(db, file_hash)
    else:
        save_filename = f"{file_hash[:32]}.{file_ext}"
        file_path_obj = base_save_dir / save_filename
        
        await save_file_async(file_content, file_path_obj)
        files_to_rollback.append(file_path_obj)
        
        relative_path = get_clean_relative_path(file_path_obj)

        original_image_file = await crud_image_file.create_image_file(
            db=db,
            file_hash=file_hash,
            user_id=user.id,
            file_type="corrections",
            subject=save_subject_dir,
            file_path=relative_path,
            file_size=len(file_content),
            mime_type=mime_type,
            image_type=ImageFileTypeEnum.ORIGINAL,
        )

    try:
        # 3. OCR 分析
        ocr_service = get_gemini_ocr_service()
        if ocr_service is None:
             raise HTTPException(status_code=503, detail="OCR Service Unavailable")

        try:
            analysis_result = await ocr_service.analyze_exam_image(
                image_path=str(file_path_obj),
                subject=SubjectType.CHEMISTRY, 
                grade=grade,
                user_hint=hint,
            )
        except AttributeError as e:
            if "'NoneType' object has no attribute 'post'" in str(e):
                raise HTTPException(status_code=503, detail="OCR服务未就绪 (依赖缺失: httpx[socks])")
            raise e
        
        if not analysis_result:
             raise HTTPException(status_code=500, detail="OCR Analysis returned empty result")

        # 4. 学科检查
        detected_subject = analysis_result.subject.value
        if detected_subject != TARGET_SUBJECT_EN:
            logger.warning(f"Subject Mismatch! Expected: {TARGET_SUBJECT_EN}, Detected: {detected_subject}")

        # 5. 知识点归一化
        valid_kps = KNOWLEDGE_POINT_TAXONOMY.get(TARGET_SUBJECT_EN, [])
        if valid_kps:
            for q in analysis_result.questions:
                cleaned_kps = [kp for kp in q.knowledge_points if kp in valid_kps]
                if not cleaned_kps and q.knowledge_points:
                    cleaned_kps = q.knowledge_points[:2] 
                q.knowledge_points = cleaned_kps

        # 6. 生成批改图片
        correction_overlay = await ocr_service.create_correction_overlay(
            image_path=str(file_path_obj),
            analysis_result=analysis_result,
        )

        corrected_image_file = None
        if correction_overlay.success and correction_overlay.corrected_image_base64:
            corrected_bytes = base64.b64decode(correction_overlay.corrected_image_base64)
            corrected_hash = calculate_file_hash(corrected_bytes)
            
            existing_corr = await crud_image_file.get_image_by_hash(db, corrected_hash)
            if existing_corr:
                corrected_image_file = existing_corr
                await crud_image_file.increment_reference_count(db, corrected_hash)
            else:
                corr_filename = f"{corrected_hash[:32]}.png"
                corr_path_obj = base_save_dir / corr_filename
                
                await save_file_async(corrected_bytes, corr_path_obj)
                files_to_rollback.append(corr_path_obj)
                
                corr_rel_path = get_clean_relative_path(corr_path_obj)

                corrected_image_file = await crud_image_file.create_image_file(
                    db=db,
                    file_hash=corrected_hash,
                    user_id=user.id,
                    file_type="corrections",
                    subject=TARGET_SUBJECT_EN,
                    file_path=corr_rel_path,
                    file_size=len(corrected_bytes),
                    mime_type="image/png",
                    image_type=ImageFileTypeEnum.CORRECTED,
                    original_image_id=original_image_file.id,
                )

        # 7. 保存记录
        questions_json = jsonable_encoder(analysis_result.questions)

        exam_correction = ExamCorrection(
            user_id=user.id,
            subject=SubjectType(TARGET_SUBJECT_EN),
            grade=grade or analysis_result.grade,
            exam_title=hint or "化学试卷智能批改",
            original_image_id=original_image_file.id,
            corrected_image_id=corrected_image_file.id if corrected_image_file else None,
            total_score=analysis_result.total_score,
            max_score=analysis_result.max_score,
            accuracy_rate=analysis_result.accuracy_rate,
            question_count=len(analysis_result.questions),
            correct_count=sum(1 for q in analysis_result.questions if q.is_correct),
            wrong_count=sum(1 for q in analysis_result.questions if not q.is_correct),
            overall_analysis=analysis_result.overall_analysis,
            weak_points=analysis_result.weak_points,
            improvement_suggestions=analysis_result.improvement_suggestions,
            questions_detail=questions_json,
        )
        db.add(exam_correction)
        await db.flush()

        # 8. 处理错题
        questions_dir = UPLOAD_ROOT / user_dir_name / "questions" / TARGET_SUBJECT_EN
        
        for q in analysis_result.questions:
            if not q.is_correct:
                q_filename = f"{task_id}_q{q.question_number}.{file_ext}"
                q_path_obj = questions_dir / q_filename

                if not q_path_obj.parent.exists():
                    q_path_obj.parent.mkdir(parents=True, exist_ok=True)

                if aiofiles is None:
                    shutil.copyfile(file_path_obj, q_path_obj)
                else:
                    async with aiofiles.open(file_path_obj, "rb") as src, aiofiles.open(q_path_obj, "wb") as dst:
                        await dst.write(await src.read())
                
                files_to_rollback.append(q_path_obj)
                
                q_clean_filename = q_path_obj.name
                q_img_url = generate_api_url(f"/images/questions/{user.id}/{TARGET_SUBJECT_EN}/{q_clean_filename}")

                db_question = Question(
                    user_id=user.id,
                    exam_correction_id=exam_correction.id,
                    title=f"第{q.question_number}题 - {q.question_type}",
                    content=q.question_text,
                    subject=SubjectType(TARGET_SUBJECT_EN),
                    difficulty=q.difficulty,
                    student_answer=q.student_answer,
                    correct_answer=q.correct_answer,
                    image_urls=[q_img_url],
                    knowledge_points=q.knowledge_points,
                    error_analysis=q.error_analysis,
                    source=QuestionSourceEnum.AI_CORRECTION,
                    source_description=f"AI批注试卷第{q.question_number}题",
                    tags=q.knowledge_points,
                )
                db.add(db_question)

        await db.commit()

        return OCRAnalysisResponse(
            success=True,
            task_id=task_id,
            subject=TARGET_SUBJECT_EN,
            grade=analysis_result.grade,
            total_score=analysis_result.total_score,
            max_score=analysis_result.max_score,
            accuracy_rate=analysis_result.accuracy_rate,
            questions=jsonable_encoder(analysis_result.questions),
            overall_analysis=analysis_result.overall_analysis,
            weak_points=analysis_result.weak_points,
            improvement_suggestions=analysis_result.improvement_suggestions,
            corrected_image_url=generate_api_url(f"/images/corrections/{exam_correction.id}/corrected") if corrected_image_file else None,
            is_duplicate=is_duplicate,
            duplicate_message="检测到重复图片" if is_duplicate else None,
            filename=filename
        )

    except Exception as e:
        await db.rollback()
        for path in files_to_rollback:
            if path.exists():
                try:
                    os.remove(path)
                except OSError:
                    pass
        raise e

# --- API Endpoints ---

@router.post("/analyze", response_model=OCRAnalysisResponse)
async def analyze_exam_image(
    file: UploadFile = File(...),
    subject: str = Form("chemistry"), 
    grade: str = Form(""),
    hint: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """单张化学试卷分析"""
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型。支持: {ALLOWED_MIME_TYPES}")

    content = await file.read()
    
    try:
        return await _process_single_image(
            db=db,
            user=current_user,
            file_content=content,
            filename=file.filename,
            mime_type=file.content_type,
            user_selected_subject=subject,
            grade=grade,
            hint=hint
        )
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        status = 503 if "socks" in str(e).lower() else (400 if "学科校验失败" in str(e) else 500)
        raise HTTPException(status_code=status, detail=str(e))

@router.post("/batch-analyze")
async def batch_analyze_images(
    files: List[UploadFile] = File(...),
    subject: str = Form("chemistry"),
    grade: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """批量化学试卷分析"""
    if len(files) > 10:
        raise HTTPException(status_code=400, detail="单次最多支持10张图片")

    results = []
    file_payloads = []
    for file in files:
        if file.content_type in ALLOWED_MIME_TYPES:
            content = await file.read()
            file_payloads.append({
                "content": content,
                "filename": file.filename,
                "mime_type": file.content_type
            })
        else:
            results.append({
                "filename": file.filename,
                "success": False,
                "error": "Unsupported file type"
            })

    for payload in file_payloads:
        try:
            res = await _process_single_image(
                db=db,
                user=current_user,
                file_content=payload["content"],
                filename=payload["filename"],
                mime_type=payload["mime_type"],
                user_selected_subject=subject,
                grade=grade,
                hint=None
            )
            res_dict = res.dict()
            results.append(res_dict)
        except Exception as e:
            logger.error(f"Batch item {payload['filename']} failed: {e}")
            results.append({
                "filename": payload["filename"],
                "success": False,
                "error": str(e)
            })

    return {
        "summary": {
            "total": len(files),
            "processed": len(results),
            "success_count": sum(1 for r in results if r.get("success", False))
        },
        "results": results
    }

@router.get("/images/corrections/{correction_id}/{image_type}")
async def get_correction_image(
    correction_id: int,
    image_type: str = PathParam(..., regex="^(original|corrected)$"),
    access_user_id: int = Depends(verify_image_access),
    db: AsyncSession = Depends(get_db),
):
    """获取批注相关图片"""
    correction = await crud_exam_correction.get_exam_correction(db, correction_id, None)
    if not correction:
        raise HTTPException(status_code=404, detail="记录不存在")

    if access_user_id != -1 and correction.user_id != access_user_id:
        raise HTTPException(status_code=403, detail="无权访问此资源")

    image_file = correction.original_image if image_type == "original" else correction.corrected_image
    if not image_file:
        raise HTTPException(status_code=404, detail="图片未生成")

    stored_path_str = image_file.file_path.lstrip("/").lstrip("\\")
    full_disk_path = UPLOAD_ROOT / stored_path_str
    
    if "data/uploads" in str(full_disk_path):
        clean = str(full_disk_path).replace("data/uploads/data/uploads", "data/uploads")
        full_disk_path = Path(clean)

    if not full_disk_path.exists():
        logger.error(f"File missing: {full_disk_path}")
        raise HTTPException(status_code=404, detail="文件丢失")

    ext = full_disk_path.suffix.lower().lstrip('.')
    media_type = f"image/{ext}" if ext != 'jpg' else 'image/jpeg'
    return FileResponse(full_disk_path, media_type=media_type)

@router.get("/images/{file_type}/{user_id}/{subject}/{filename}")
async def get_user_image(
    file_type: str = PathParam(..., regex="^(corrections|questions)$"),
    user_id: int = PathParam(...),
    subject: str = PathParam(...),
    filename: str = PathParam(...),
    access_user_id: int = Depends(verify_image_access),
    db: AsyncSession = Depends(get_db),
):
    """通用用户图片获取接口"""
    if access_user_id != -1 and user_id != access_user_id:
         raise HTTPException(status_code=403, detail="无权访问")

    user = await crud_user.get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    user_dir = get_user_directory_name(user.username, user.email)
    safe_filename = Path(filename).name

    file_path = UPLOAD_ROOT / user_dir / file_type / subject / safe_filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="图片不存在")

    return FileResponse(file_path)