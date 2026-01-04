"""
OCR批改API (RPJ模块 - 学生实现版本)

本文件为框架代码，需要学生完成核心业务逻辑的实现。
完整实现请参考: backend/modules/tony/api/endpoints/ocr.py

RPJ模块支持的学科: chinese, english, politics
"""

import os
import uuid
import hashlib
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends, Query, Path
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.core.db.session import get_db
from backend.modules.rpj.api.deps import get_current_user_id, get_current_user
from backend.modules.rpj.config import settings
from backend.modules.rpj.agents.ocr_agent import OCRAgent
from backend.core.crud import crud_image_file, crud_exam_correction, crud_question
from backend.core.db.models import User, ImageFile, ExamCorrection, Question, QuestionSourceEnum, ImageFileTypeEnum

logger = logging.getLogger(__name__)

router = APIRouter()

def validate_subject(subject: str) -> None:
    """验证学科是否属于RPJ模块"""
    if subject not in settings.SUBJECTS:
        raise HTTPException(
            status_code=400,
            detail=f"Subject '{subject}' is not supported by RPJ module. "
                   f"Supported subjects: {settings.SUBJECTS}"
        )

# ============ Helper Functions ============

def calculate_file_hash(content: bytes) -> str:
    """计算文件内容的哈希值"""
    return hashlib.md5(content).hexdigest()

def generate_correction_image_url(correction_id: int, image_type: str, subject: str = "chinese") -> str:
    """
    生成批改图片URL

    Args:
        correction_id: 批注记录ID
        image_type: 图片类型 ('original' 或 'corrected')
        subject: 学科名称

    Returns:
        完整的URL路径
    """
    # 获取主机配置
    host = settings.HOST if settings.HOST not in ['0.0.0.0', ''] else 'localhost'
    port = settings.PORT

    # 生成完整URL: http://{host}:{port}/api/v1/rpj/ocr/images/corrections/{correction_id}/{image_type}
    return f"http://{host}:{port}/api/v1/rpj/ocr/images/corrections/{correction_id}/{image_type}"

def get_user_upload_dir(user_id: int, file_type: str, subject: str) -> str:
    """
    获取用户上传目录

    Args:
        user_id: 用户ID
        file_type: 文件类型 (corrections 或 questions)
        subject: 学科

    Returns:
        用户上传目录路径
    """
    # 创建用户目录结构: uploads/{user_id}/{file_type}/{subject}/
    upload_dir = os.path.join(settings.IMAGE_UPLOAD_DIR, str(user_id), file_type, subject)
    os.makedirs(upload_dir, exist_ok=True)
    return upload_dir

def get_filename_from_path(file_path: str) -> str:
    """从文件路径中提取文件名"""
    return os.path.basename(file_path)

def get_subject_display_name(subject: str) -> str:
    """获取学科显示名称"""
    subject_names = {
        "chinese": "语文",
        "english": "英语",
        "politics": "道法"
    }
    return subject_names.get(subject, subject)

# ============ Response Models ============

class OCRAnalysisResponse(BaseModel):
    """OCR 分析响应"""
    success: bool
    task_id: str
    subject: str
    subject_display: str
    grade: str
    total_score: float
    max_score: float
    accuracy_rate: float
    questions: list
    overall_analysis: str
    weak_points: list
    improvement_suggestions: list
    corrected_image_url: Optional[str] = None
    is_duplicate: bool = False  # 是否为重复图片
    duplicate_message: Optional[str] = None  # 重复提示信息
    correction_id: Optional[int] = None  # 批改记录ID

class QuestionDetail(BaseModel):
    """题目详情"""
    question_number: int
    question_type: str
    question_text: str
    student_answer: str
    correct_answer: Optional[str]
    score: float
    max_score: float
    is_correct: bool
    error_analysis: str
    knowledge_points: list
    solution_steps: list
    difficulty: str

class BatchAnalysisResponse(BaseModel):
    """批量分析响应"""
    success: bool
    total: int
    results: List[Dict[str, Any]]

class OCRErrorResponse(BaseModel):
    """OCR错误响应"""
    error: str
    message: str
    task_id: Optional[str] = None

# ============ API Endpoints ============

@router.post("/analyze", response_model=OCRAnalysisResponse)
async def analyze_exam_image(
    file: UploadFile = File(...),
    subject: str = Form(..., description="学科"),
    grade: str = Form("", description="年级"),
    hint: Optional[str] = Form(None, description="试卷标题或提示"),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    分析试卷图片

    上传试卷图片，进行OCR识别和自动批改：
    1. OCR 识别题目和答案
    2. 自动批改打分
    3. 错因分析
    4. 生成学习建议

    注意：只支持RPJ模块的学科 (chinese, english, politics)
    """
    # 验证学科是否属于RPJ模块
    validate_subject(subject)

    # 验证文件类型
    allowed_types = ["image/jpeg", "image/jpg", "image/png", "image/webp", "image/gif"]
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {file.content_type}。支持: {', '.join(allowed_types)}"
        )

    # 验证文件大小（限制为10MB）
    max_size = 10 * 1024 * 1024  # 10MB
    file.file.seek(0, 2)  # 移动到文件末尾
    file_size = file.file.tell()
    file.file.seek(0)  # 重置文件指针

    if file_size > max_size:
        raise HTTPException(
            status_code=400,
            detail=f"文件太大。最大支持 {max_size // (1024*1024)}MB"
        )

    # 读取文件内容并计算哈希值
    content = await file.read()
    file_hash = calculate_file_hash(content)

    # 检查图片是否已存在（同一用户维度去重）
    existing_image = await crud_image_file.get_image_by_hash(db, file_hash, user_id)
    is_duplicate = False
    duplicate_message = None

    if existing_image and existing_image.user_id == user_id:
        is_duplicate = True
        duplicate_message = "检测到您之前已上传过相同的图片，系统将复用已有图片进行分析"
        logger.info(f"重复图片检测: 用户ID={user_id}, 文件哈希={file_hash[:16]}...")

    # 生成task_id用于后续处理
    task_id = str(uuid.uuid4())

    # 获取或创建原始图片记录
    if existing_image:
        # 图片已存在，复用现有文件
        original_image_file = existing_image
        file_path = original_image_file.file_path
        filename = get_filename_from_path(file_path)
        logger.info(f"图片已存在，复用: 文件哈希={file_hash[:16]}..., 路径={file_path}")

        # 增加引用计数
        await crud_image_file.increment_reference_count(db, file_hash, user_id)
    else:
        # 图片不存在，保存新文件
        file_ext = file.filename.split(".")[-1] if file.filename and "." in file.filename else "jpg"
        filename = f"{file_hash[:32]}.{file_ext}"

        # 保存到用户专属目录
        upload_dir = get_user_upload_dir(user_id, "corrections", subject)
        file_path = os.path.join(upload_dir, filename)

        # 保存文件
        with open(file_path, "wb") as f:
            f.write(content)

        # 创建图片文件记录（原始图片）
        relative_path = os.path.relpath(file_path, os.path.abspath("."))
        if relative_path.startswith(".."):
            # 如果相对路径包含上级目录，使用绝对路径
            relative_path = file_path

        original_image_file = await crud_image_file.create_image_file(
            db=db,
            file_hash=file_hash,
            user_id=user_id,
            file_type="corrections",
            subject=subject,
            file_path=relative_path,
            file_size=file_size,
            mime_type=file.content_type,
            image_type=ImageFileTypeEnum.ORIGINAL,
        )
        logger.info(f"新图片已保存: 文件哈希={file_hash[:16]}..., 路径={file_path}, ID={original_image_file.id}")

    try:
        # 调用RPJ模块的OCR Agent
        ocr_agent = OCRAgent(subject)
        await ocr_agent.initialize()

        # 分析试卷
        analysis_result = await ocr_agent.analyze_exam_image(
            image_path=file_path,
            subject=subject,
            grade=grade,
            hint=hint,
        )

        # TODO(student): 学科判定 + 分类归一化（统一模板 v1；不要在此处直接实现，留给学生）
        # 【输入】user_selected_subject=subject，text=OCR/试卷解析得到的题目文本/结构化题目
        # 【输出】对每题生成：
        #   - detected_subject + confidence(0~1)
        #   - chapter: 从 CHAPTER_TAXONOMY[detected_subject] 选 1 个（否则“综合”）
        #   - knowledge_points: 从 KNOWLEDGE_POINT_TAXONOMY[detected_subject] 选 1~3 个（否则“综合”）
        #   - tags: 2~6 个短词（用于检索，避免太碎）
        # 【规则】
        #   - 若 detected_subject != user_selected_subject 且 confidence >= 0.75：提示“学科不匹配”并拒绝返回批改结果
        #   - taxonomy 必须收敛：chapter 建议 6~10 个，knowledge_points 建议 10~25 个；同义项合并，避免发散
        # 【推荐 taxonomy 示例（RPJ: chinese/english/morality）】
        #   CHAPTER_TAXONOMY = {
        #     "chinese": ["阅读理解", "文言文", "诗词鉴赏", "写作", "基础知识(字词句)", "综合"],
        #     "english": ["词汇语法", "完形填空", "阅读理解", "写作", "听力", "综合"],
        #     "morality": ["法律与规则", "道德与价值观", "国家制度", "经济与社会", "时政与案例", "综合"],
        #   }
        #   KNOWLEDGE_POINT_TAXONOMY = {
        #     "chinese": ["主旨概括", "人物形象", "修辞手法", "表达方式", "文言实词虚词", "病句与标点", "写作立意与结构", "综合"],
        #     "english": ["时态语态", "从句", "非谓语", "词汇辨析", "阅读策略", "写作句型", "综合"],
        #     "morality": ["宪法与法律", "权利与义务", "社会主义核心价值观", "法治思维", "公民责任", "时事热点", "综合"],
        #   }
        # 【实现建议】
        #   - OCR/解析后调用 settings.LLM_API_ENDPOINT 的 /chat/completions（二次判定+归一化）
        #   - 优先更强模型（gemini-3-pro-preview / gpt-5.2），可通过环境变量 RPJ_HIGH_ACCURACY_MODEL 覆盖
        # 【参考实现】backend/modules/tony/agents/question_intake_ocr_agent.py（仅 tony 模块完整实现）

        if not analysis_result or not analysis_result.get("success", False):
            raise HTTPException(
                status_code=500,
                detail="试卷分析失败，请稍后重试"
            )

        # 提取分析结果
        questions = analysis_result.get("questions", [])
        total_score = analysis_result.get("total_score", 0.0)
        max_score = analysis_result.get("max_score", 100.0)
        overall_analysis = analysis_result.get("overall_analysis", "")
        weak_points = analysis_result.get("weak_points", [])
        improvement_suggestions = analysis_result.get("improvement_suggestions", [])
        accuracy_rate = analysis_result.get("accuracy_rate", 0.0)
        result_grade = analysis_result.get("grade", grade)

        # 生成批改图像（如果支持）
        corrected_image_file = None
        corrected_image_url = None

        if analysis_result.get("corrected_image_base64"):
            try:
                import base64

                corrected_image_bytes = base64.b64decode(analysis_result["corrected_image_base64"])
                corrected_file_hash = calculate_file_hash(corrected_image_bytes)

                # 检查批改后的图片是否已存在
                existing_corrected_image = await crud_image_file.get_image_by_hash(db, corrected_file_hash, user_id)

                if existing_corrected_image:
                    corrected_image_file = existing_corrected_image
                    corrected_path = existing_corrected_image.file_path
                    await crud_image_file.increment_reference_count(db, corrected_file_hash, user_id)
                    logger.info(f"批改后图片已存在，复用: 文件哈希={corrected_file_hash[:16]}..., ID={corrected_image_file.id}")
                else:
                    # 保存批改后的图片文件
                    corrected_filename = f"{corrected_file_hash[:32]}_corrected.png"
                    corrected_upload_dir = get_user_upload_dir(user_id, "corrections", subject)
                    corrected_path = os.path.join(corrected_upload_dir, corrected_filename)

                    with open(corrected_path, "wb") as f:
                        f.write(corrected_image_bytes)

                    # 创建批改后图片文件记录
                    corrected_relative_path = os.path.relpath(corrected_path, os.path.abspath("."))
                    if corrected_relative_path.startswith(".."):
                        corrected_relative_path = corrected_path

                    corrected_image_file = await crud_image_file.create_image_file(
                        db=db,
                        file_hash=corrected_file_hash,
                        user_id=user_id,
                        file_type="corrections",
                        subject=subject,
                        file_path=corrected_relative_path,
                        file_size=len(corrected_image_bytes),
                        mime_type="image/png",
                        image_type=ImageFileTypeEnum.CORRECTED,
                        original_image_id=original_image_file.id,
                    )
                    logger.info(f"批改后图片已保存: 文件哈希={corrected_file_hash[:16]}..., 路径={corrected_path}, ID={corrected_image_file.id}")

            except Exception as e:
                logger.error(f"保存批改后图片失败: {str(e)}")
                # 批改后图片保存失败不影响整体流程

        # 保存批注记录到数据库
        exam_correction = ExamCorrection(
            user_id=user_id,
            subject=subject,
            grade=result_grade,
            exam_title=hint or f"{get_subject_display_name(subject)}试卷批改",
            original_image_id=original_image_file.id,
            corrected_image_id=corrected_image_file.id if corrected_image_file else None,
            total_score=total_score,
            max_score=max_score,
            accuracy_rate=accuracy_rate,
            question_count=len(questions),
            correct_count=sum(1 for q in questions if q.get("is_correct", False)),
            wrong_count=sum(1 for q in questions if not q.get("is_correct", True)),
            overall_analysis=overall_analysis,
            weak_points=weak_points,
            improvement_suggestions=improvement_suggestions,
            questions_detail=[
                {
                    "question_number": q.get("question_number", 0),
                    "question_type": q.get("question_type", ""),
                    "question_text": q.get("question_text", ""),
                    "student_answer": q.get("student_answer", ""),
                    "correct_answer": q.get("correct_answer"),
                    "score": q.get("score", 0.0),
                    "max_score": q.get("max_score", 0.0),
                    "is_correct": q.get("is_correct", False),
                    "error_analysis": q.get("error_analysis", ""),
                    "knowledge_points": q.get("knowledge_points", []),
                    "solution_steps": q.get("solution_steps", []),
                    "difficulty": q.get("difficulty", "medium"),
                }
                for q in questions
            ],
            created_at=datetime.utcnow(),
        )

        db.add(exam_correction)
        await db.flush()

        # 生成批改图片URL
        if corrected_image_file:
            corrected_image_url = generate_correction_image_url(
                exam_correction.id, "corrected", subject
            )
            logger.info(f"批改后图片URL: {corrected_image_url}")

        # 为错误的题目自动创建错题记录
        wrong_question_ids = []
        for i, q in enumerate(questions):
            if not q.get("is_correct", False):
                # 构建错题图片路径
                question_filename = f"{task_id}_q{q.get('question_number', i+1)}.{file_ext if 'file_ext' in locals() else 'jpg'}"
                question_upload_dir = get_user_upload_dir(user_id, "questions", subject)
                question_image_path = os.path.join(question_upload_dir, question_filename)

                # 复制原图作为错题图片（简化处理，直接使用原图路径）
                import shutil
                try:
                    shutil.copy2(file_path, question_image_path)
                except Exception as e:
                    logger.warning(f"复制错题图片失败: {str(e)}")
                    question_image_path = file_path

                # 获取相对路径
                question_relative_path = os.path.relpath(question_image_path, os.path.abspath("."))
                if question_relative_path.startswith(".."):
                    question_relative_path = question_image_path

                # 保存错题图片记录
                question_image_file = await crud_image_file.create_image_file(
                    db=db,
                    file_hash=calculate_file_hash(open(question_image_path, 'rb').read()),
                    user_id=user_id,
                    file_type="questions",
                    subject=subject,
                    file_path=question_relative_path,
                    file_size=os.path.getsize(question_image_path),
                    mime_type=file.content_type,
                    image_type=ImageFileTypeEnum.ORIGINAL,
                )

                # 创建错题记录
                db_question = Question(
                    user_id=user_id,
                    exam_correction_id=exam_correction.id,
                    title=f"第{q.get('question_number', i+1)}题 - {q.get('question_type', '题目')}",
                    content=q.get("question_text", ""),
                    subject=subject,
                    difficulty=q.get("difficulty", "medium"),
                    student_answer=q.get("student_answer", ""),
                    correct_answer=q.get("correct_answer"),
                    knowledge_points=q.get("knowledge_points", []),
                    error_analysis=q.get("error_analysis", ""),
                    source=QuestionSourceEnum.AI_CORRECTION,
                    source_description=f"AI批注试卷第{q.get('question_number', i+1)}题",
                    tags=q.get("knowledge_points", []),
                    created_at=datetime.utcnow(),
                )

                db.add(db_question)
                await db.flush()
                wrong_question_ids.append(db_question.id)

        await db.commit()

        logger.info(
            f"试卷批改记录已保存: 记录ID={exam_correction.id}, 用户ID={user_id}, "
            f"创建错题记录数={len(wrong_question_ids)}"
        )

        return OCRAnalysisResponse(
            success=True,
            task_id=task_id,
            subject=subject,
            subject_display=get_subject_display_name(subject),
            grade=result_grade,
            total_score=total_score,
            max_score=max_score,
            accuracy_rate=accuracy_rate,
            questions=questions,
            overall_analysis=overall_analysis,
            weak_points=weak_points,
            improvement_suggestions=improvement_suggestions,
            corrected_image_url=corrected_image_url,
            is_duplicate=is_duplicate,
            duplicate_message=duplicate_message,
            correction_id=exam_correction.id,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"试卷分析失败: {str(e)}")
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"分析失败: {str(e)}")

@router.get("/images/corrections/{correction_id}/{image_type}")
async def get_correction_image(
    correction_id: int = Path(..., description="批改记录ID"),
    image_type: str = Path(..., description="图片类型: 'original' 或 'corrected'"),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    获取批注图片（通过correction_id和image_type）

    路径格式: /api/v1/rpj/ocr/images/corrections/{correction_id}/{image_type}
    image_type: 'original' 或 'corrected'

    安全验证：
    - 通过correction_id查找ExamCorrection记录
    - 验证当前用户是否为批注记录的所有者
    - 根据image_type获取对应的图片ID并返回图片文件
    """
    from fastapi.responses import FileResponse

    # 验证image_type
    if image_type not in ["original", "corrected"]:
        raise HTTPException(
            status_code=400,
            detail="image_type必须是'original'或'corrected'"
        )

    # 获取批注记录
    result = await db.execute(
        select(ExamCorrection).where(
            ExamCorrection.id == correction_id,
            ExamCorrection.user_id == user_id
        )
    )
    correction = result.scalar_one_or_none()

    if not correction:
        raise HTTPException(status_code=404, detail="批注记录不存在或无权访问")

    # 验证学科是否属于RPJ模块
    validate_subject(correction.subject)

    # 根据image_type获取对应的图片文件
    image_file_id = None
    if image_type == "original":
        image_file_id = correction.original_image_id
    else:  # corrected
        image_file_id = correction.corrected_image_id

    if not image_file_id:
        raise HTTPException(
            status_code=404,
            detail=f"{'原始' if image_type == 'original' else '批改后'}图片不存在"
        )

    # 获取图片文件记录
    result = await db.execute(
        select(ImageFile).where(
            ImageFile.id == image_file_id,
            ImageFile.user_id == user_id
        )
    )
    image_file = result.scalar_one_or_none()

    if not image_file:
        raise HTTPException(status_code=404, detail="图片文件不存在")

    # 检查文件是否存在
    file_path = image_file.file_path

    # 如果文件路径是相对路径，转换为绝对路径
    if not os.path.isabs(file_path):
        # 尝试基于项目根目录
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.abspath(os.path.join(current_dir, "../../../../.."))
        file_path = os.path.join(project_root, file_path)

    if not os.path.exists(file_path):
        # 尝试使用配置中的上传目录
        upload_base = settings.IMAGE_UPLOAD_DIR
        if upload_base and os.path.exists(upload_base):
            # 构建可能的路径
            possible_paths = [
                file_path,
                os.path.join(upload_base, file_path),
                os.path.join(upload_base, str(user_id), "corrections", correction.subject, os.path.basename(file_path)),
            ]

            for path in possible_paths:
                if os.path.exists(path):
                    file_path = path
                    break
            else:
                logger.error(f"图片文件不存在: 原始路径={image_file.file_path}, 用户ID={user_id}")
                raise HTTPException(status_code=404, detail="图片文件不存在")

    # 根据文件扩展名确定 MIME 类型
    ext = os.path.splitext(file_path)[1].lower().lstrip('.')
    mime_types = {
        'png': 'image/png',
        'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg',
        'webp': 'image/webp',
        'gif': 'image/gif',
        'bmp': 'image/bmp',
    }
    media_type = mime_types.get(ext, 'image/jpeg')

    logger.info(f"返回图片文件: 路径={file_path}, 媒体类型={media_type}")

    return FileResponse(file_path, media_type=media_type)

@router.post("/batch-analyze", response_model=BatchAnalysisResponse)
async def batch_analyze_images(
    files: List[UploadFile] = File(...),
    subject: str = Form(..., description="学科"),
    grade: str = Form("", description="年级"),
    hint: Optional[str] = Form(None, description="试卷标题或提示"),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    批量分析多张试卷图片

    注意：批量分析可能耗时较长，建议异步处理
    """
    # 验证学科是否属于RPJ模块
    validate_subject(subject)

    # 限制批量处理数量
    max_files = 5
    if len(files) > max_files:
        raise HTTPException(
            status_code=400,
            detail=f"一次最多上传{max_files}个文件"
        )

    results = []

    for file in files:
        try:
            # 为每个文件生成task_id
            task_id = str(uuid.uuid4())

            # 验证文件类型
            allowed_types = ["image/jpeg", "image/jpg", "image/png", "image/webp", "image/gif"]
            if file.content_type not in allowed_types:
                results.append({
                    "filename": file.filename,
                    "task_id": task_id,
                    "status": "error",
                    "message": f"不支持的文件类型: {file.content_type}"
                })
                continue

            # 保存文件到临时目录
            content = await file.read()
            file_hash = calculate_file_hash(content)

            # 检查是否已存在
            existing_image = await crud_image_file.get_image_by_hash(db, file_hash, user_id)

            if existing_image:
                # 文件已存在
                results.append({
                    "filename": file.filename,
                    "task_id": task_id,
                    "status": "skipped",
                    "message": "文件已存在，跳过处理",
                    "file_hash": file_hash[:16] + "..."
                })
                continue

            # 保存临时文件
            temp_dir = os.path.join(settings.IMAGE_UPLOAD_DIR, "temp", str(user_id))
            os.makedirs(temp_dir, exist_ok=True)

            temp_filename = f"{task_id}_{file.filename or 'upload'}"
            temp_path = os.path.join(temp_dir, temp_filename)

            with open(temp_path, "wb") as f:
                f.write(content)

            # 记录任务信息
            results.append({
                "filename": file.filename,
                "task_id": task_id,
                "status": "queued",
                "message": "已加入处理队列",
                "file_hash": file_hash[:16] + "...",
                "temp_path": temp_path
            })

        except Exception as e:
            logger.error(f"批量处理文件失败: {file.filename}, 错误: {str(e)}")
            results.append({
                "filename": file.filename,
                "status": "error",
                "message": f"处理失败: {str(e)}"
            })

    # 异步处理批量任务
    try:
        # 这里可以启动后台任务来处理批量分析
        # 简化处理：立即处理所有文件（实际应该使用任务队列）
        from backend.modules.rpj.agents.task_processor import TaskProcessor

        processor = TaskProcessor()
        for result in results:
            if result.get("status") == "queued" and result.get("temp_path"):
                await processor.submit_ocr_task(
                    task_id=result["task_id"],
                    file_path=result["temp_path"],
                    subject=subject,
                    grade=grade,
                    hint=hint,
                    user_id=user_id
                )
    except Exception as e:
        logger.error(f"提交批量任务失败: {str(e)}")

    return BatchAnalysisResponse(
        success=True,
        total=len(results),
        results=results
    )

@router.get("/status/{task_id}")
async def get_ocr_task_status(
    task_id: str = Path(..., description="任务ID"),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    获取OCR任务状态

    查询指定任务的处理状态
    """
    # 这里可以查询任务状态表或使用Redis等缓存
    # 简化处理：返回基本状态信息

    from backend.modules.rpj.agents.task_processor import TaskProcessor

    try:
        processor = TaskProcessor()
        status = await processor.get_task_status(task_id, user_id)

        if not status:
            raise HTTPException(status_code=404, detail="任务不存在")

        return {
            "task_id": task_id,
            "status": status.get("status", "unknown"),
            "progress": status.get("progress", 0),
            "message": status.get("message", ""),
            "result": status.get("result"),
            "created_at": status.get("created_at"),
            "updated_at": status.get("updated_at"),
        }

    except Exception as e:
        logger.error(f"获取任务状态失败: {task_id}, 错误: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取任务状态失败: {str(e)}")

@router.get("/recent-corrections")
async def get_recent_corrections(
    limit: int = Query(10, ge=1, le=50, description="返回数量"),
    subject: Optional[str] = Query(None, description="学科筛选"),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    获取最近的批改记录

    返回用户最近的OCR批改记录
    """
    # 验证学科是否属于RPJ模块
    if subject:
        validate_subject(subject)

    # 构建查询
    query = select(ExamCorrection).where(
        ExamCorrection.user_id == user_id
    ).order_by(ExamCorrection.created_at.desc())

    # 应用学科筛选
    if subject:
        query = query.where(ExamCorrection.subject == subject)

    # 限制结果数量
    query = query.limit(limit)

    # 执行查询
    result = await db.execute(query)
    corrections = result.scalars().all()

    # 构建响应
    response = []
    for correction in corrections:
        # 生成图片URL
        original_image_url = generate_correction_image_url(correction.id, "original", correction.subject)
        corrected_image_url = None
        if correction.corrected_image_id:
            corrected_image_url = generate_correction_image_url(correction.id, "corrected", correction.subject)

        response.append({
            "id": correction.id,
            "subject": correction.subject,
            "subject_display": get_subject_display_name(correction.subject),
            "grade": correction.grade,
            "exam_title": correction.exam_title,
            "total_score": correction.total_score,
            "max_score": correction.max_score,
            "accuracy_rate": correction.accuracy_rate,
            "question_count": correction.question_count,
            "correct_count": correction.correct_count,
            "wrong_count": correction.wrong_count,
            "original_image_url": original_image_url,
            "corrected_image_url": corrected_image_url,
            "created_at": correction.created_at.isoformat(),
        })

    return {
        "total": len(response),
        "corrections": response,
    }

@router.delete("/corrections/{correction_id}")
async def delete_correction(
    correction_id: int = Path(..., description="批改记录ID"),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    删除批改记录

    删除指定的批改记录及相关联的图片和题目
    """
    # 获取批改记录
    result = await db.execute(
        select(ExamCorrection).where(
            ExamCorrection.id == correction_id,
            ExamCorrection.user_id == user_id
        )
    )
    correction = result.scalar_one_or_none()

    if not correction:
        raise HTTPException(status_code=404, detail="批改记录不存在或无权访问")

    # 验证学科是否属于RPJ模块
    validate_subject(correction.subject)

    try:
        # 删除相关联的题目
        questions_result = await db.execute(
            select(Question).where(
                Question.exam_correction_id == correction_id,
                Question.user_id == user_id
            )
        )
        questions = questions_result.scalars().all()

        for question in questions:
            await db.delete(question)

        # 删除批改记录
        await db.delete(correction)

        # 删除相关联的图片（如果引用计数为0）
        image_files = []
        if correction.original_image_id:
            result = await db.execute(
                select(ImageFile).where(ImageFile.id == correction.original_image_id)
            )
            original_image = result.scalar_one_or_none()
            if original_image:
                image_files.append(original_image)

        if correction.corrected_image_id:
            result = await db.execute(
                select(ImageFile).where(ImageFile.id == correction.corrected_image_id)
            )
            corrected_image = result.scalar_one_or_none()
            if corrected_image:
                image_files.append(corrected_image)

        # 检查并删除图片文件记录
        for image_file in image_files:
            # 减少引用计数
            await crud_image_file.decrement_reference_count(db, image_file.file_hash, user_id)

            # 检查引用计数，如果为0则删除文件记录和物理文件
            if image_file.reference_count <= 0:
                # 删除物理文件
                try:
                    if os.path.exists(image_file.file_path):
                        os.remove(image_file.file_path)
                except Exception as e:
                    logger.warning(f"删除物理文件失败: {image_file.file_path}, 错误: {str(e)}")

                # 删除数据库记录
                await db.delete(image_file)

        await db.commit()

        logger.info(f"批改记录已删除: 记录ID={correction_id}, 用户ID={user_id}")

        return {
            "success": True,
            "message": "批改记录已删除",
            "deleted_correction_id": correction_id,
            "deleted_questions_count": len(questions),
        }

    except Exception as e:
        logger.error(f"删除批改记录失败: {correction_id}, 错误: {str(e)}")
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")

@router.get("/statistics")
async def get_ocr_statistics(
    subject: Optional[str] = Query(None, description="学科筛选"),
    days: int = Query(30, ge=1, le=365, description="统计天数"),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    获取OCR批改统计

    统计用户的OCR批改使用情况
    """
    from datetime import datetime, timedelta
    from sqlalchemy import func

    # 验证学科是否属于RPJ模块
    if subject:
        validate_subject(subject)
        subjects = [subject]
    else:
        subjects = settings.SUBJECTS

    # 计算时间范围
    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)

    statistics = {
        "period": {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "days": days,
        },
        "summary": {
            "total_corrections": 0,
            "total_questions": 0,
            "total_images": 0,
            "avg_accuracy": 0.0,
            "by_subject": {},
        },
        "daily_trend": [],
        "recent_activity": [],
    }

    try:
        # 按学科统计
        for subj in subjects:
            # 统计批改记录数量
            corrections_query = select(func.count(ExamCorrection.id)).where(
                ExamCorrection.user_id == user_id,
                ExamCorrection.subject == subj,
                ExamCorrection.created_at >= start_date,
                ExamCorrection.created_at <= end_date,
            )
            corrections_result = await db.execute(corrections_query)
            corrections_count = corrections_result.scalar() or 0

            if corrections_count > 0:
                # 统计题目数量
                questions_query = select(func.sum(ExamCorrection.question_count)).where(
                    ExamCorrection.user_id == user_id,
                    ExamCorrection.subject == subj,
                    ExamCorrection.created_at >= start_date,
                    ExamCorrection.created_at <= end_date,
                )
                questions_result = await db.execute(questions_query)
                questions_count = questions_result.scalar() or 0

                # 统计平均准确率
                accuracy_query = select(func.avg(ExamCorrection.accuracy_rate)).where(
                    ExamCorrection.user_id == user_id,
                    ExamCorrection.subject == subj,
                    ExamCorrection.created_at >= start_date,
                    ExamCorrection.created_at <= end_date,
                )
                accuracy_result = await db.execute(accuracy_query)
                avg_accuracy = accuracy_result.scalar() or 0.0

                # 统计图片数量
                images_query = select(func.count(ImageFile.id)).where(
                    ImageFile.user_id == user_id,
                    ImageFile.subject == subj,
                    ImageFile.file_type == "corrections",
                    ImageFile.created_at >= start_date,
                    ImageFile.created_at <= end_date,
                )
                images_result = await db.execute(images_query)
                images_count = images_result.scalar() or 0

                statistics["summary"]["by_subject"][subj] = {
                    "subject_display": get_subject_display_name(subj),
                    "corrections_count": corrections_count,
                    "questions_count": questions_count,
                    "images_count": images_count,
                    "avg_accuracy": round(float(avg_accuracy), 2),
                }

                statistics["summary"]["total_corrections"] += corrections_count
                statistics["summary"]["total_questions"] += questions_count
                statistics["summary"]["total_images"] += images_count

        # 计算总体平均准确率
        if statistics["summary"]["total_corrections"] > 0:
            total_accuracy_query = select(func.avg(ExamCorrection.accuracy_rate)).where(
                ExamCorrection.user_id == user_id,
                ExamCorrection.created_at >= start_date,
                ExamCorrection.created_at <= end_date,
            )
            total_accuracy_result = await db.execute(total_accuracy_query)
            total_avg_accuracy = total_accuracy_result.scalar() or 0.0
            statistics["summary"]["avg_accuracy"] = round(float(total_avg_accuracy), 2)

        # 生成每日趋势（最近7天）
        for i in range(7):
            day_date = end_date - timedelta(days=i)
            day_start = day_date.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_date.replace(hour=23, minute=59, second=59, microsecond=999999)

            daily_query = select(func.count(ExamCorrection.id)).where(
                ExamCorrection.user_id == user_id,
                ExamCorrection.created_at >= day_start,
                ExamCorrection.created_at <= day_end,
            )
            daily_result = await db.execute(daily_query)
            daily_count = daily_result.scalar() or 0

            statistics["daily_trend"].insert(0, {
                "date": day_date.strftime("%Y-%m-%d"),
                "corrections_count": daily_count,
            })

        # 获取最近活动
        recent_query = select(ExamCorrection).where(
            ExamCorrection.user_id == user_id,
        ).order_by(ExamCorrection.created_at.desc()).limit(5)

        recent_result = await db.execute(recent_query)
        recent_corrections = recent_result.scalars().all()

        for correction in recent_corrections:
            statistics["recent_activity"].append({
                "id": correction.id,
                "subject": correction.subject,
                "subject_display": get_subject_display_name(correction.subject),
                "exam_title": correction.exam_title,
                "total_score": correction.total_score,
                "max_score": correction.max_score,
                "accuracy_rate": correction.accuracy_rate,
                "created_at": correction.created_at.isoformat(),
            })

    except Exception as e:
        logger.error(f"获取OCR统计失败: {str(e)}")

    return statistics

@router.get("/usage-tips")
async def get_ocr_usage_tips(
    subject: Optional[str] = Query(None, description="学科"),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    获取OCR使用技巧

    提供各学科图片上传的注意事项和技巧
    """
    # 验证学科是否属于RPJ模块
    if subject:
        validate_subject(subject)

    general_tips = {
        "title": "OCR批改使用技巧",
        "general_tips": [
            "确保图片清晰，光线充足",
            "尽量拍摄正面，避免倾斜",
            "图片中只包含试卷内容，减少背景干扰",
            "文字大小适中，避免过小或模糊",
            "文件大小建议在10MB以内",
            "支持的格式：JPEG、PNG、WebP、GIF"
        ],
        "upload_advice": [
            "拍照时手机与试卷平行，减少透视变形",
            "使用高分辨率模式拍摄",
            "在光线均匀的环境下拍摄",
            "避免使用闪光灯，以免反光",
            "一次上传一张试卷图片"
        ],
        "common_issues": [
            "图片模糊：重新拍照，确保对焦准确",
            "文字识别错误：调整光线，确保文字清晰",
            "批改结果不准确：检查图片质量，重新上传",
            "处理时间过长：可能是图片较大，请耐心等待"
        ]
    }

    # 学科特定技巧
    subject_specific_tips = {}

    if subject == "chinese" or not subject:
        subject_specific_tips["chinese"] = {
            "title": "语文试卷上传技巧",
            "tips": [
                "确保作文文字清晰可辨",
                "古诗文题目要拍摄完整",
                "阅读题的段落要拍摄清楚",
                "字迹工整的试卷识别效果更好",
                "注意标点符号的清晰度"
            ]
        }

    if subject == "english" or not subject:
        subject_specific_tips["english"] = {
            "title": "英语试卷上传技巧",
            "tips": [
                "注意英文字母的清晰度",
                "作文部分要拍摄完整",
                "选择题的选项要清晰可见",
                "注意大小写字母的区分",
                "连笔字可能会影响识别效果"
            ]
        }

    if subject == "politics" or not subject:
        subject_specific_tips["politics"] = {
            "title": "道法试卷上传技巧",
            "tips": [
                "简答题的答案要拍摄完整",
                "论述题的文字要清晰",
                "注意条目的编号清晰",
                "案例分析题要拍摄全部内容",
                "注意标点符号的清晰度"
            ]
        }

    return {
        "user_id": user_id,
        "subject": subject or "all",
        "general_tips": general_tips,
        "subject_specific_tips": subject_specific_tips if subject_specific_tips else None
    }

@router.get("/support-formats")
async def get_supported_formats():
    """
    获取支持的图片格式

    返回系统支持的图片格式信息
    """
    return {
        "supported_formats": [
            {
                "format": "JPEG/JPG",
                "mime_type": "image/jpeg",
                "description": "最常见的有损压缩图片格式",
                "max_size_mb": 10,
                "recommended": True
            },
            {
                "format": "PNG",
                "mime_type": "image/png",
                "description": "无损压缩，支持透明度",
                "max_size_mb": 10,
                "recommended": True
            },
            {
                "format": "WebP",
                "mime_type": "image/webp",
                "description": "Google开发的现代图片格式",
                "max_size_mb": 10,
                "recommended": True
            },
            {
                "format": "GIF",
                "mime_type": "image/gif",
                "description": "支持动画，但通常用于静态图片",
                "max_size_mb": 10,
                "recommended": False
            }
        ],
        "requirements": {
            "max_file_size": "10MB",
            "min_resolution": "300×300像素",
            "recommended_resolution": "1500×2000像素以上",
            "color_mode": "彩色或黑白均可",
            "orientation": "建议竖屏拍摄"
        },
        "tips": {
            "quality": "图片质量越高，识别效果越好",
            "lighting": "均匀光线，避免阴影",
            "focus": "确保文字清晰对焦",
            "background": "纯色背景效果更佳",
            "perspective": "正面拍摄，避免倾斜"
        }
    }
