import os
import uuid
import logging
import time
from datetime import datetime
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

# 导入 XMX 核心组件
from backend.modules.xmx.api.deps import get_current_user_id, get_db
from backend.modules.xmx.config import settings
from backend.modules.xmx.agents.ai_correction.ocr_agent import OCRAgent

# 核心工具与模型
from backend.core.utils.file_utils import (
    get_user_upload_dir,
    calculate_file_hash,
    get_user_directory_name
)
from backend.core.crud import crud_image_file, crud_user
from backend.core.db.models import ImageFileTypeEnum, ExamCorrection, Question, QuestionSourceEnum

logger = logging.getLogger(__name__)
router = APIRouter()

UPLOAD_DIR = "./data/uploads"

# 中文学科映射
SUBJECT_NAME_MAP = {
    "经济学": "economics",
    "数学": "math",
    "英语": "english",
}

class OCRAnalysisResponse(BaseModel):
    success: bool
    task_id: str
    subject: str
    total_score: float
    max_score: float
    accuracy_rate: float
    questions: List[Dict[str, Any]]
    overall_analysis: Optional[str] = None
    corrected_image_url: Optional[str] = None
    is_duplicate: bool = False

@router.post("/analyze", response_model=OCRAnalysisResponse)
async def analyze_exam_image(
    file: UploadFile = File(...),
    subject: str = Form("economics"),
    grade: str = Form(""),
    hint: Optional[str] = Form(None),
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    XMX 工业级 OCR 批改接口
    """
    t0 = time.perf_counter()
    
    # 0. 学科校验与转换 (解决 Enum/Str 冲突核心)
    subject_en = SUBJECT_NAME_MAP.get(subject, subject.lower())
    if subject_en not in [s.lower() for s in settings.SUBJECTS]:
        raise HTTPException(status_code=400, detail=f"不支持的学科: {subject}")

    # 1. 文件处理与去重
    content = await file.read()
    file_hash = calculate_file_hash(content)
    
    existing_image = await crud_image_file.get_image_by_hash(db, file_hash)
    is_duplicate = False
    
    if existing_image and existing_image.user_id == user_id:
        is_duplicate = True
        original_image_file = existing_image
        file_path = existing_image.file_path
        await crud_image_file.increment_reference_count(db, file_hash)
    else:
        user = await crud_user.get_user(db, user_id)
        file_ext = file.filename.split(".")[-1] if file.filename else "jpg"
        filename = f"{file_hash[:32]}.{file_ext}"
        upload_dir = get_user_upload_dir(UPLOAD_DIR, user, "corrections", subject_en)
        file_path = os.path.join(upload_dir, filename)
        
        if not os.path.exists(file_path):
            with open(file_path, "wb") as f:
                f.write(content)
            
        relative_path = os.path.relpath(file_path, os.path.abspath(".")).lstrip("./")
        original_image_file = await crud_image_file.create_image_file(
            db=db, file_hash=file_hash, user_id=user_id,
            file_type="corrections", subject=subject_en,
            file_path=relative_path, file_size=len(content),
            mime_type=file.content_type, image_type=ImageFileTypeEnum.ORIGINAL,
        )

    # 2. 调用 OCRAgent (带防御性处理)
    task_id = str(uuid.uuid4())
    agent = OCRAgent()
    result = await agent.process(
        image_path=file_path,
        user_id=user_id,
        task_id=task_id,
        subject=subject_en,
    )

    if not result.get("success"):
        # 即使失败也需要返回 400，但要保证 data 结构
        raise HTTPException(status_code=400, detail=result.get("errors", ["AI分析失败"])[0])

    data = result.get("data", {})
    questions_list = data.get("questions") or []
    score_info = data.get("score_info") or {"total_score": 0, "max_score": 100}

    # 3. 结果入库 ExamCorrection
    correction_record = ExamCorrection(
        user_id=user_id,
        subject=subject_en,
        grade=grade,
        original_image_id=original_image_file.id,
        total_score=score_info.get("total_score", 0),
        max_score=score_info.get("max_score", 100),
        accuracy_rate=result.get("accuracy_rate", 0),
        overall_analysis=data.get("analysis", {}).get("suggestions", ["完成"])[0],
        questions_detail=questions_list,
        weak_points=data.get("analysis", {}).get("weak_points", []),
        improvement_suggestions=data.get("analysis", {}).get("suggestions", [])
    )
    db.add(correction_record)
    await db.flush()
logger.info(f"OCR Analysis completed in {time.perf_counter() - t0:.2f} seconds for user_id={user_id}, task_id={task_id}")
    # 4. 错题同步
    for q in questions_list:
        if not q.get("is_correct", True):
            new_q = Question(
                user_id=user_id,
                exam_correction_id=correction_record.id,
                title=f"XMX-{subject_en}-错题",
                content=q.get("question_text", ""),
                subject=subject_en,
                student_answer=q.get("student_answer", ""),
                correct_answer=q.get("correct_answer", ""),
                source=QuestionSourceEnum.AI_CORRECTION,
                knowledge_points=q.get("knowledge_points", [])
            )
            db.add(new_q)

    await db.commit()

    return OCRAnalysisResponse(
        success=True,
        task_id=task_id,
        subject=subject_en,
        total_score=score_info.get("total_score", 0),
        max_score=score_info.get("max_score", 100),
        accuracy_rate=result.get("accuracy_rate", 0),
        questions=questions_list,
        overall_analysis=correction_record.overall_analysis,
        is_duplicate=is_duplicate
    )