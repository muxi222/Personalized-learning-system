"""
OCR API 端点 - 试卷分析与批改

功能:
1. 上传试卷图片进行 OCR 分析
2. 自动批改并打分
3. 生成批改后的图像
"""

import os
import uuid
import logging
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends, Query, Path
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.modules.tony.api.deps import get_current_user, get_current_user_id, get_optional_user_id, get_db, oauth2_scheme
from backend.core.services.gemini_ocr_service import (
    get_gemini_ocr_service,
    SubjectType,
    ExamAnalysisResult,
)
from backend.core.db.models import User
from backend.core.utils.file_utils import (
    get_user_upload_dir,
    get_user_file_url,
    get_user_directory_name,
    calculate_file_hash,
    get_filename_from_path,
)
from backend.core.crud import crud_image_file

logger = logging.getLogger(__name__)
router = APIRouter()

UPLOAD_DIR = "./data/uploads"

# 学科到模块的映射（用于生成完整URL）
SUBJECT_TO_MODULE = {
    # RPJ模块 (6001)
    "chinese": ("rpj", 6001),
    "english": ("rpj", 6001),
    "politics": ("rpj", 6001),
    # XMX模块 (6002)
    "economics": ("xmx", 6002),
    # WZY模块 (6003)
    "math": ("wzy", 6003),
    "physics": ("wzy", 6003),
    # WZM模块 (6004)
    "chemistry": ("wzm", 6004),
    # TONY模块 (6005)
    "history": ("tony", 6005),
    "geography": ("tony", 6005),
    "other": ("tony", 6005),
}


def generate_correction_image_url(correction_id: int, image_type: str, subject: str) -> str:
    """
    生成批改图片URL（根据学科路由到对应模块）

    Args:
        correction_id: 批注记录ID
        image_type: 图片类型 ('original' 或 'corrected')
        subject: 学科名称（用于确定模块和端口）

    Returns:
        完整的URL路径（包含协议、主机和端口）
    """
    # 获取学科对应的模块和端口
    module_info = SUBJECT_TO_MODULE.get(subject)
    if not module_info:
        # 未知学科，使用默认模块
        logger.warning(f"Unknown subject '{subject}', using default module (port 6100)")
        port = 6100
    else:
        _, port = module_info

    # 获取主机配置（支持环境变量）
    host = os.getenv('API_HOST', 'localhost')
    if host in ['0.0.0.0', '']:
        host = 'localhost'

    # 生成完整URL
    return f"http://{host}:{port}/api/v1/ocr/images/corrections/{correction_id}/{image_type}"

# 中文学科名称到英文的映射
SUBJECT_NAME_MAP = {
    "数学": "math",
    "英语": "english",
    "物理": "physics",
    "化学": "chemistry",
    "语文": "chinese",
    "生物": "biology",
    "政治": "politics",
    "经济学": "economics",
    "历史": "history",
    "地理": "geography",
    "其他": "other",
}


class OCRAnalysisResponse(BaseModel):
    """OCR 分析响应"""
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
    is_duplicate: bool = False  # 是否为重复图片
    duplicate_message: Optional[str] = None  # 重复提示信息


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


@router.post("/analyze", response_model=OCRAnalysisResponse)
async def analyze_exam_image(
    file: UploadFile = File(...),
    subject: str = Form("other"),
    grade: str = Form(""),
    hint: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    分析试卷图片

    上传试卷图片，使用 Gemini 2.5 Flash 进行:
    1. OCR 识别题目和答案
    2. 自动批改打分
    3. 错因分析
    4. 生成学习建议
    """
    # 验证文件类型
    allowed_types = ["image/jpeg", "image/png", "image/webp", "image/heic"]
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {file.content_type}。支持: {', '.join(allowed_types)}"
        )

    # 解析学科类型
    subject_en = SUBJECT_NAME_MAP.get(subject, subject.lower())
    
    # 读取文件内容并计算哈希值
    content = await file.read()
    file_hash = calculate_file_hash(content)
    
    # 检查图片是否已存在（同一用户维度去重）
    existing_image = await crud_image_file.get_image_by_hash(db, file_hash)
    is_duplicate = False
    duplicate_message = None
    
    # 检查是否为同一用户的重复图片
    if existing_image and existing_image.user_id == current_user.id:
        is_duplicate = True
        duplicate_message = "检测到您之前已上传过相同的图片，系统将复用已有图片进行分析"
        logger.info(f"Duplicate image detected for user {current_user.id}: hash={file_hash[:16]}...")
    
    # 生成task_id用于后续处理
    task_id = str(uuid.uuid4())
    
    # 获取或创建原始图片记录
    from backend.core.db.models import ImageFileTypeEnum
    
    if existing_image:
        # 图片已存在，复用现有文件
        original_image_file = existing_image
        file_path = existing_image.file_path
        filename = get_filename_from_path(file_path)
        logger.info(f"Image already exists, reusing: hash={file_hash[:16]}..., path={file_path}")
        
        # 增加引用计数
        await crud_image_file.increment_reference_count(db, file_hash)
    else:
        # 图片不存在，保存新文件（使用hash值作为文件名）
        file_ext = file.filename.split(".")[-1] if file.filename else "jpg"
        # 使用hash值的前32位作为文件名，避免文件名过长
        filename = f"{file_hash[:32]}.{file_ext}"
        
        # 保存到用户专属目录: data/uploads/{username_email}/corrections/{subject}/
        upload_dir = get_user_upload_dir(UPLOAD_DIR, current_user, "corrections", subject_en)
        file_path = os.path.join(upload_dir, filename)
        
        # 保存文件
        with open(file_path, "wb") as f:
            f.write(content)

        # 创建图片文件记录（原始图片）- 存储相对路径以便跨环境
        # 标准化路径格式为 data/uploads/... (不带 ./ 前缀)
        relative_path = os.path.relpath(file_path, os.path.abspath("."))
        # 移除开头的 ./ 或 ./
        relative_path = relative_path.lstrip("./")
        if not relative_path.startswith("data/uploads"):
            relative_path = f"data/uploads/{get_user_directory_name(current_user.username, current_user.email)}/corrections/{subject_en}/{filename}"
        
        original_image_file = await crud_image_file.create_image_file(
            db=db,
            file_hash=file_hash,
            user_id=current_user.id,
            file_type="corrections",
            subject=subject_en,
            file_path=relative_path,
            file_size=len(content),
            mime_type=file.content_type,
            image_type=ImageFileTypeEnum.ORIGINAL,
        )
        logger.info(f"New image saved: hash={file_hash[:16]}..., path={file_path}, id={original_image_file.id}")
    

    try:
        # 调用 OCR 服务
        ocr_service = get_gemini_ocr_service()
        await ocr_service.initialize()

        # 解析学科类型 - 支持中文和英文
        try:
            subject_type = SubjectType(subject_en)
        except ValueError:
            subject_type = SubjectType.OTHER

        # 分析试卷
        result = await ocr_service.analyze_exam_image(
            image_path=file_path,
            subject=subject_type,
            grade=grade,
            user_hint=hint,
        )

        # 生成批改图像
        correction_result = await ocr_service.create_correction_overlay(
            image_path=file_path,
            analysis_result=result,
        )

        # 保存批改后的图像到用户专属目录和image_files表
        corrected_image_file = None
        if correction_result.success and correction_result.corrected_image_base64:
            import base64
            corrected_image_bytes = base64.b64decode(correction_result.corrected_image_base64)
            corrected_file_hash = calculate_file_hash(corrected_image_bytes)
            
            # 检查批改后的图片是否已存在
            existing_corrected_image = await crud_image_file.get_image_by_hash(db, corrected_file_hash)
            
            if existing_corrected_image:
                corrected_image_file = existing_corrected_image
                corrected_path = existing_corrected_image.file_path
                await crud_image_file.increment_reference_count(db, corrected_file_hash)
                logger.info(f"Corrected image already exists, reusing: hash={corrected_file_hash[:16]}..., id={corrected_image_file.id}")
            else:
                # 保存批改后的图片文件（使用原始学科，保证与批改前一致）
                corrected_filename = f"{corrected_file_hash[:32]}.png"
                corrected_path = os.path.join(
                    get_user_upload_dir(UPLOAD_DIR, current_user, "corrections", subject_en),
                    corrected_filename
                )
                with open(corrected_path, "wb") as f:
                    f.write(corrected_image_bytes)

                # 标准化路径格式为 data/uploads/... (不带 ./ 前缀)
                corrected_relative_path = os.path.relpath(corrected_path, os.path.abspath("."))
                corrected_relative_path = corrected_relative_path.lstrip("./")
                if not corrected_relative_path.startswith("data/uploads"):
                    corrected_relative_path = f"data/uploads/{get_user_directory_name(current_user.username, current_user.email)}/corrections/{subject_en}/{corrected_filename}"

                # 创建批改后图片文件记录（关联到原始图片，使用原始学科）
                corrected_image_file = await crud_image_file.create_image_file(
                    db=db,
                    file_hash=corrected_file_hash,
                    user_id=current_user.id,
                    file_type="corrections",
                    subject=subject_en,  # 使用原始学科，保证与批改前一致
                    file_path=corrected_relative_path,  # 使用标准化路径（不带 ./ 前缀）
                    file_size=len(corrected_image_bytes),
                    mime_type="image/png",
                    image_type=ImageFileTypeEnum.CORRECTED,
                    original_image_id=original_image_file.id,  # 关联到原始图片
                )
                logger.info(f"Saved corrected image: hash={corrected_file_hash[:16]}..., path={corrected_relative_path}, id={corrected_image_file.id}")

        # 保存批注记录到数据库（使用原始学科，保证与批改前一致）
        from backend.core.db.models import ExamCorrection, QuestionSourceEnum

        exam_correction = ExamCorrection(
            user_id=current_user.id,
            subject=subject_type,  # 使用原始学科类型
            grade=grade or result.grade,
            exam_title=hint or f"{subject_en}试卷批改",  # 使用原始学科
            original_image_id=original_image_file.id,
            corrected_image_id=corrected_image_file.id if corrected_image_file else None,
            total_score=result.total_score,
            max_score=result.max_score,
            accuracy_rate=result.accuracy_rate,
            question_count=len(result.questions),
            correct_count=sum(1 for q in result.questions if q.is_correct),
            wrong_count=sum(1 for q in result.questions if not q.is_correct),
            overall_analysis=result.overall_analysis,
            weak_points=result.weak_points,
            improvement_suggestions=result.improvement_suggestions,
            questions_detail=[
                {
                    "question_number": q.question_number,
                    "question_type": q.question_type,
                    "question_text": q.question_text,
                    "student_answer": q.student_answer,
                    "correct_answer": q.correct_answer,
                    "score": q.score,
                    "max_score": q.max_score,
                    "is_correct": q.is_correct,
                    "error_analysis": q.error_analysis,
                    "knowledge_points": q.knowledge_points,
                    "solution_steps": q.solution_steps,
                    "difficulty": q.difficulty,
                }
                for q in result.questions
            ],
        )
        db.add(exam_correction)
        await db.flush()

        # 生成批改图片URL（使用新格式：通过 correction_id 访问）
        corrected_image_url = None
        if corrected_image_file:
            corrected_image_url = generate_correction_image_url(
                exam_correction.id, "corrected", subject_en
            )
            logger.info(f"Corrected image URL: {corrected_image_url}")

        # 为错误的题目自动创建错题记录
        from backend.core.crud import crud_question
        from backend.core.schemas.question import QuestionCreate
        
        wrong_question_ids = []
        for q in result.questions:
            if not q.is_correct:  # 只为错题创建记录
                # 保存错题图片到用户专属目录（使用原始学科，保证与批改前一致）
                question_filename = f"{task_id}_q{q.question_number}.{file_ext}"
                question_image_path = os.path.join(
                    get_user_upload_dir(UPLOAD_DIR, current_user, "questions", subject_en),
                    question_filename
                )

                # 复制原图作为错题图片（后续可优化为裁剪）
                import shutil
                try:
                    shutil.copy2(file_path, question_image_path)
                except Exception as e:
                    logger.warning(f"Failed to copy question image: {e}")
                    question_image_path = file_path

                # 生成URL路径（使用原始学科，保证与批改前一致）
                question_image_url = get_user_file_url(current_user, "questions", subject_en, question_filename)
                
                # 创建错题记录（使用原始学科，保证与批改前一致）
                question_data = QuestionCreate(
                    content=q.question_text,
                    title=f"第{q.question_number}题 - {q.question_type}",
                    subject=subject_en,  # 使用原始学科
                    difficulty=q.difficulty,
                    student_answer=q.student_answer,
                    correct_answer=q.correct_answer,
                    image_urls=[question_image_url],
                    tags=q.knowledge_points,
                )

                from backend.core.db.models import Question
                db_question = Question(
                    user_id=current_user.id,
                    exam_correction_id=exam_correction.id,
                    title=question_data.title,
                    content=question_data.content,
                    subject=subject_type,  # 使用原始学科类型
                    difficulty=question_data.difficulty,
                    student_answer=question_data.student_answer,
                    correct_answer=question_data.correct_answer,
                    image_urls=question_data.image_urls,
                    knowledge_points=q.knowledge_points,
                    error_analysis=q.error_analysis,
                    source=QuestionSourceEnum.AI_CORRECTION,
                    source_description=f"AI批注试卷第{q.question_number}题",
                    tags=q.knowledge_points,
                )
                db.add(db_question)
                await db.flush()
                wrong_question_ids.append(db_question.id)
        
        await db.commit()
        
        logger.info(
            f"Saved exam correction {exam_correction.id} for user {current_user.id}, "
            f"created {len(wrong_question_ids)} wrong question records"
        )

        return OCRAnalysisResponse(
            success=True,
            task_id=task_id,
            subject=result.subject.value,
            grade=result.grade,
            total_score=result.total_score,
            max_score=result.max_score,
            accuracy_rate=result.accuracy_rate,
            questions=[
                {
                    "question_number": q.question_number,
                    "question_type": q.question_type,
                    "question_text": q.question_text,
                    "student_answer": q.student_answer,
                    "correct_answer": q.correct_answer,
                    "score": q.score,
                    "max_score": q.max_score,
                    "is_correct": q.is_correct,
                    "error_analysis": q.error_analysis,
                    "knowledge_points": q.knowledge_points,
                    "solution_steps": q.solution_steps,
                    "difficulty": q.difficulty,
                }
                for q in result.questions
            ],
            overall_analysis=result.overall_analysis,
            weak_points=result.weak_points,
            improvement_suggestions=result.improvement_suggestions,
            corrected_image_url=corrected_image_url,
            is_duplicate=is_duplicate,
            duplicate_message=duplicate_message,
        )

    except Exception as e:
        logger.error(f"OCR analysis failed: {e}")
        raise HTTPException(status_code=500, detail=f"分析失败: {str(e)}")

    finally:
        # 清理临时文件 (可选，生产环境可保留用于审计)
        pass


@router.get("/images/{file_type}/{user_id}/{subject}/{filename}")
async def get_user_image(
    file_type: str,
    user_id: int,
    subject: str,
    filename: str,
    token: Optional[str] = Query(None, description="JWT token (for image tag access)"),
    current_user_id: Optional[int] = Depends(get_optional_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    获取用户图像
    
    路径格式: /ocr/images/{file_type}/{user_id}/{subject}/{filename}
    file_type: corrections 或 questions
    
    安全验证：
    - 如果提供了JWT token，验证路径中的user_id与JWT中的user_id是否一致
    - 如果没有token，在开发模式下允许访问（生产环境应要求认证）
    - 支持通过<img>标签直接访问（浏览器不会发送Authorization header）
    """
    from fastapi.responses import FileResponse
    from backend.core.crud import crud_user
    from backend.core.utils.file_utils import get_user_directory_name
    from backend.modules.tony.config import settings
    from jose import jwt, JWTError

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

    # 如果提供了token，验证用户ID是否一致
    if current_user_id is not None:
        logger.info(f"Image access with authentication: current_user_id={current_user_id}, path_user_id={user_id}")
        if user_id != current_user_id:
            logger.warning(f"User ID mismatch: current_user_id={current_user_id}, path_user_id={user_id}")
            raise HTTPException(
                status_code=403,
                detail="无权访问该用户的图像资源"
            )
    else:
        # 没有token的情况
        logger.warning(f"Image access without authentication: user_id={user_id}, file={filename}, is_development={settings.is_development}")
        if not settings.is_development:
            # 生产环境要求认证
            raise HTTPException(
                status_code=401,
                detail="需要认证才能访问图像资源",
                headers={"WWW-Authenticate": "Bearer"},
            )
        # 开发模式允许访问，但记录警告
    
    # 获取用户对象以构建正确的文件路径
    user = await crud_user.get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    # 根据用户信息构建用户目录名
    user_dir_name = get_user_directory_name(user.username, user.email)
    file_path = os.path.join(UPLOAD_DIR, user_dir_name, file_type, subject, filename)
    
    if os.path.exists(file_path):
        # 根据文件扩展名确定 MIME 类型
        ext = filename.split('.')[-1].lower()
        mime_types = {
            'png': 'image/png',
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'webp': 'image/webp',
            'heic': 'image/heic',
        }
        media_type = mime_types.get(ext, 'image/png')
        return FileResponse(file_path, media_type=media_type)
    
        raise HTTPException(status_code=404, detail="图像不存在")


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
    
    路径格式: /ocr/images/corrections/{correction_id}/{image_type}
    image_type: 'original' 或 'corrected'
    
    安全验证：
    - 通过correction_id查找ExamCorrection记录
    - 验证当前用户是否为批注记录的所有者
    - 根据image_type获取对应的图片ID并返回图片文件
    """
    from fastapi.responses import FileResponse
    from backend.core.crud import crud_exam_correction, crud_image_file
    from backend.modules.tony.config import settings
    from jose import jwt, JWTError
    import os

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
        from backend.core.crud import crud_user
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


@router.get("/images/{subject}/{filename}")
async def get_image_legacy(subject: str, filename: str):
    """
    获取图像（兼容旧路径）
    旧路径格式: /ocr/images/{subject}/{filename}
    """
    from fastapi.responses import FileResponse

    # 尝试从批注目录或错题目录查找（遍历所有用户目录）
    base_paths = [UPLOAD_DIR]
    
    for base_path in base_paths:
        # 遍历用户目录
        if os.path.exists(base_path):
            for user_dir in os.listdir(base_path):
                user_path = os.path.join(base_path, user_dir)
                if not os.path.isdir(user_path):
                    continue
                
                # 尝试 corrections 和 questions
                for file_type in ["corrections", "questions"]:
                    file_path = os.path.join(user_path, file_type, subject, filename)
                    if os.path.exists(file_path):
                        ext = filename.split('.')[-1].lower()
                        mime_types = {
                            'png': 'image/png',
                            'jpg': 'image/jpeg',
                            'jpeg': 'image/jpeg',
                            'webp': 'image/webp',
                            'heic': 'image/heic',
                        }
                        media_type = mime_types.get(ext, 'image/png')
                        return FileResponse(file_path, media_type=media_type)
    
    raise HTTPException(status_code=404, detail="图像不存在")


@router.post("/batch-analyze")
async def batch_analyze_images(
    files: list[UploadFile] = File(...),
    subject: str = Form("other"),
    current_user: User = Depends(get_current_user),
):
    """
    批量分析多张试卷图片
    """
    results = []

    for file in files:
        try:
            # 复用单张分析逻辑
            # 这里简化处理，实际应该异步处理
            results.append({
                "filename": file.filename,
                "status": "queued",
                "message": "已加入处理队列",
            })
        except Exception as e:
            results.append({
                "filename": file.filename,
                "status": "error",
                "message": str(e),
            })

    return {
        "success": True,
        "total": len(files),
        "results": results,
    }
