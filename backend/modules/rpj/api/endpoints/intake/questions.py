"""
Questions API Endpoints - RPJ模块
错题相关API（支持语文、英语、政治学科）
"""

import os
import uuid
import json
import logging
import re
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.db.session import get_db
from backend.core.crud import crud_question, crud_task, crud_user, crud_image_file
from backend.core.schemas.question import (
    QuestionCreate,
    QuestionUpdate,
    QuestionResponse,
    QuestionDetail,
    QuestionListResponse,
    SimilarQuestionQuery,
)
from backend.core.schemas.task import TaskResponse, TaskStatus
from backend.core.db.models import TaskStatusEnum, ImageFileTypeEnum
from backend.modules.rpj.api.deps import get_current_user_id
from backend.modules.rpj.config import settings
from backend.core.services.gemini_ocr_service import get_gemini_ocr_service, SubjectType
from backend.core.utils.file_utils import (
    get_user_upload_dir,
    get_user_directory_name,
    calculate_file_hash,
    get_filename_from_path,
)

logger = logging.getLogger(__name__)

router = APIRouter()

UPLOAD_DIR = "./data/uploads"

# 中文学科名称到英文的映射（RPJ模块专用）
SUBJECT_NAME_MAP = {
    "语文": "chinese",
    "英语": "english", 
    "政治": "politics",
    "chinese": "chinese",
    "english": "english",
    "politics": "politics",
    "语文试卷": "chinese",
    "英语试卷": "english",
    "政治试卷": "politics",
}


def validate_subject(subject: str) -> None:
    """验证学科是否属于RPJ模块"""
    subject_lower = subject.lower()
    if subject_lower not in settings.SUBJECTS:
        raise HTTPException(
            status_code=400,
            detail=f"Subject '{subject}' is not supported by RPJ module. "
                   f"Supported subjects: {settings.SUBJECTS}"
        )


@router.post("/", response_model=TaskResponse, status_code=202)
async def create_question(
    question_data: QuestionCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    提交新错题
    
    触发Agent工作流进行异步处理:
    1. 解析输入提取结构化信息
    2. 保存到数据库
    3. 生成向量并存入向量库
    4. AI分析错因
    5. 生成举一反三题目
    
    返回task_id，可通过 /tasks/{task_id} 查询处理状态
    """
    # Generate task ID
    task_id = str(uuid.uuid4())

    # Create task record
    await crud_task.create_task(db, task_id)
    await db.commit()

    # Start background processing
    async def process_async():
        from backend.modules.rpj.agents.question_intake_ocr_agent import QuestionIntakeOCRAgent

        try:
            # 使用RPJ模块的QuestionIntakeOCRAgent
            agent = QuestionIntakeOCRAgent()
            
            # 转换QuestionCreate为text_data格式
            text_data = {
                "content": question_data.content,
                "student_answer": question_data.student_answer,
                "correct_answer": question_data.correct_answer,
                "knowledge_points": question_data.knowledge_points or [],
                "tags": question_data.tags or [],
            }
            
            result = await agent.process(
                input_type="text",
                user_id=user_id,
                task_id=task_id,
                subject=question_data.subject or "chinese",
                difficulty=question_data.difficulty or "medium",
                grade=question_data.grade or "",
                text_data=text_data,
            )
            
            if result.get("success"):
                logger.info(f"Task {task_id} completed, question_id={result.get('question_id')}")
            else:
                logger.warning(f"Task {task_id} completed with errors: {result.get('errors')}")

        except Exception as e:
            logger.error(f"Task {task_id} failed: {e}", exc_info=True)
            async with get_db() as session:
                await crud_task.fail_task(session, task_id, str(e))
                await session.commit()

    background_tasks.add_task(process_async)

    logger.info(f"Created task {task_id} for user {user_id}")

    return TaskResponse(
        task_id=task_id,
        status=TaskStatus.PENDING,
        message="Task created. Processing started.",
    )


@router.post("/ocr", response_model=TaskResponse, status_code=202)
async def create_question_with_image(
    file: UploadFile = File(...),
    subject: str = Form("chinese"),
    difficulty: str = Form("medium"),
    grade: str = Form(""),
    title: Optional[str] = Form(None),
    background_tasks: BackgroundTasks = None,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    上传图片识别错题（录入错题功能专用）
    
    支持上传错题图片，自动OCR识别题目内容和答案，
    然后进行结构化存储和AI分析。
    
    流程:
    1. 上传图片并保存到用户专属目录
    2. OCR识别题目内容
    3. 提取题目、学生答案、正确答案
    4. 创建错题记录
    5. 触发AI分析流程
    """
    # 验证学科
    subject_en = SUBJECT_NAME_MAP.get(subject, subject.lower())
    validate_subject(subject_en)
    
    # 验证文件类型
    allowed_types = ["image/jpeg", "image/png", "image/webp", "image/heic"]
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {file.content_type}。支持: {', '.join(allowed_types)}"
        )

    # 获取用户对象
    user = await crud_user.get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 读取文件内容并计算哈希值
    content = await file.read()
    file_hash = calculate_file_hash(content)
    
    # 检查图片是否已存在（同一用户维度去重）
    existing_image = await crud_image_file.get_image_by_hash(db, file_hash)
    is_duplicate = False
    
    # 检查是否为同一用户的重复图片
    if existing_image and existing_image.user_id == user.id:
        is_duplicate = True
        logger.info(f"Duplicate image detected for user {user.id}: hash={file_hash[:16]}...")
        # 前端可以通过响应中的信息来显示提醒
    
    # 生成task_id用于后续处理
    task_id = str(uuid.uuid4())
    
    # 创建任务记录
    await crud_task.create_task(db, task_id)
    await db.commit()
    
    # 获取或创建原始图片记录
    if existing_image:
        # 图片已存在，复用现有文件
        image_file = existing_image
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
        
        # 保存到用户专属目录: data/uploads/{username_email}/questions/{subject}/
        upload_dir = get_user_upload_dir(UPLOAD_DIR, user, "questions", subject_en)
        os.makedirs(upload_dir, exist_ok=True)
        file_path = os.path.join(upload_dir, filename)
        
        # 保存文件
        with open(file_path, "wb") as f:
            f.write(content)
        
        # 标准化路径格式为 data/uploads/... (不带 ./ 前缀)
        relative_path = os.path.relpath(file_path, os.path.abspath("."))
        relative_path = relative_path.lstrip("./")
        if not relative_path.startswith("data/uploads"):
            relative_path = f"data/uploads/{get_user_directory_name(user.username, user.email)}/questions/{subject_en}/{filename}"
        
        # 创建图片文件记录
        image_file = await crud_image_file.create_image_file(
            db=db,
            file_hash=file_hash,
            user_id=user.id,
            file_type="questions",
            subject=subject_en,
            file_path=relative_path,
            file_size=len(content),
            mime_type=file.content_type,
            image_type=ImageFileTypeEnum.ORIGINAL,
        )
        logger.info(f"New image saved: hash={file_hash[:16]}..., path={file_path}, id={image_file.id}")

    try:
        # 异步处理OCR和分析
        async def process_with_ocr():
            from backend.modules.rpj.agents.question_intake_ocr_agent import QuestionIntakeOCRAgent
            from backend.core.db.session import async_session_maker

            try:
                # 使用QuestionIntakeOCRAgent处理
                agent = QuestionIntakeOCRAgent()
                
                result = await agent.process(
                    input_type="image",
                    user_id=user_id,
                    task_id=task_id,
                    subject=subject_en,
                    difficulty=difficulty,
                    grade=grade,
                    source_image_id=image_file.id,
                    image_path=file_path,
                )

                if result.get("success"):
                    logger.info(f"OCR task {task_id} completed, question_id={result.get('question_id')}")
                else:
                    logger.warning(f"OCR task {task_id} completed with errors: {result.get('errors')}")

            except Exception as e:
                logger.error(f"OCR task {task_id} failed: {e}", exc_info=True)
                async with async_session_maker() as session:
                    await crud_task.fail_task(session, task_id, str(e))
                    await session.commit()

        background_tasks.add_task(process_with_ocr)

        logger.info(f"Created OCR task {task_id} for user {user_id}")

        return TaskResponse(
            task_id=task_id,
            status=TaskStatus.PENDING,
            message="图片已上传，OCR识别处理中...",
            details={"is_duplicate": is_duplicate},
        )

    except Exception as e:
        logger.error(f"Failed to process image upload: {e}", exc_info=True)
        # 清理文件
        if not existing_image and os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")


@router.get("/", response_model=QuestionListResponse)
async def list_questions(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    subject: Optional[str] = Query(None, description="学科筛选"),
    difficulty: Optional[str] = Query(None, description="难度筛选"),
    search: Optional[str] = Query(None, description="关键词搜索"),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    获取错题列表
    支持分页、筛选和搜索
    """
    skip = (page - 1) * page_size
    questions, total = await crud_question.get_questions(
        db,
        user_id=user_id,
        skip=skip,
        limit=page_size,
        subject=subject,
        difficulty=difficulty,
        search=search,
    )

    return QuestionListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[QuestionResponse.model_validate(q) for q in questions],
    )


@router.get("/{question_id}", response_model=QuestionDetail)
async def get_question(
    question_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    获取错题详情
    包含AI分析结果和举一反三题目
    """
    question = await crud_question.get_question(db, question_id, user_id)
    if not question:
        raise HTTPException(status_code=404, detail="错题不存在")

    return QuestionDetail.model_validate(question)


@router.patch("/{question_id}", response_model=QuestionResponse)
async def update_question(
    question_id: int,
    question_data: QuestionUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    更新错题信息
    """
    question = await crud_question.update_question(
        db, question_id, question_data, user_id
    )
    if not question:
        raise HTTPException(status_code=404, detail="错题不存在")

    return QuestionResponse.model_validate(question)


@router.delete("/{question_id}", status_code=204)
async def delete_question(
    question_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    删除错题
    """
    success = await crud_question.delete_question(db, question_id, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="错题不存在")


@router.post("/{question_id}/reanalyze", response_model=TaskResponse, status_code=202)
async def reanalyze_question(
    question_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    重新分析错题
    对已有错题重新进行AI分析
    """
    # Verify question exists and belongs to user
    question = await crud_question.get_question(db, question_id, user_id)
    if not question:
        raise HTTPException(status_code=404, detail="错题不存在")

    # Create new task
    task_id = str(uuid.uuid4())
    await crud_task.create_task(db, task_id, question_id)
    await db.commit()

    # Start background reanalysis
    async def reanalyze_async():
        from backend.core.db.session import async_session_maker
        from backend.modules.rpj.agents.question_intake_ocr_agent import QuestionIntakeOCRAgent

        try:
            # 使用QuestionIntakeOCRAgent进行重新分析
            agent = QuestionIntakeOCRAgent()
            
            # 构建text_data
            text_data = {
                "content": question.content,
                "student_answer": question.student_answer,
                "correct_answer": question.correct_answer,
                "knowledge_points": question.knowledge_points or [],
                "tags": question.tags or [],
            }
            
            result = await agent.process(
                input_type="text",
                user_id=user_id,
                task_id=task_id,
                subject=question.subject.value if hasattr(question.subject, 'value') else "chinese",
                difficulty=question.difficulty.value if hasattr(question.difficulty, 'value') else "medium",
                grade=question.grade or "",
                text_data=text_data,
            )
            
            if result.get("success"):
                logger.info(f"Reanalysis task {task_id} completed")
            else:
                logger.warning(f"Reanalysis task {task_id} completed with errors: {result.get('errors')}")

            async with async_session_maker() as session:
                await crud_task.complete_task(session, task_id, question_id)
                await session.commit()

        except Exception as e:
            logger.error(f"Reanalysis task {task_id} failed: {e}", exc_info=True)
            async with async_session_maker() as session:
                await crud_task.fail_task(session, task_id, str(e))
                await session.commit()

    background_tasks.add_task(reanalyze_async)

    return TaskResponse(
        task_id=task_id,
        status=TaskStatus.PENDING,
        message="重新分析任务已开始",
    )


@router.post("/similar", response_model=List[QuestionResponse])
async def find_similar_questions(
    query: SimilarQuestionQuery,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    查找相似题目
    基于向量相似度检索相关错题
    """
    from backend.core.services.vector_store_service import get_vector_store_service

    vector_store = get_vector_store_service()
    await vector_store.initialize()

    # Get query text
    if query.question_id:
        question = await crud_question.get_question(db, query.question_id, user_id)
        if not question:
            raise HTTPException(status_code=404, detail="错题不存在")
        query_text = question.content
    elif query.content:
        query_text = query.content
    else:
        raise HTTPException(status_code=400, detail="请提供question_id或content")

    # Search similar
    results = await vector_store.search_by_text(
        query_text=query_text,
        n_results=query.limit,
        where={"user_id": user_id} if user_id else None,
    )

    # Get full question data
    questions = []
    for result in results:
        q_id = int(result["id"])
        if query.question_id and q_id == query.question_id:
            continue  # Skip self
        question = await crud_question.get_question(db, q_id, user_id)
        if question:
            questions.append(QuestionResponse.model_validate(question))

    return questions


@router.get("/review/due", response_model=List[QuestionResponse])
async def get_due_for_review(
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    获取需要复习的错题
    基于艾宾浩斯遗忘曲线推荐
    """
    questions = await crud_question.get_questions_for_review(db, user_id, limit)
    return [QuestionResponse.model_validate(q) for q in questions]


@router.get("/stats/summary", response_model=dict)
async def get_question_stats(
    subject: Optional[str] = Query(None, description="学科筛选"),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    获取错题统计摘要
    包括各学科错题数量、掌握程度等
    """
    stats = await crud_question.get_question_stats(db, user_id, subject)
    
    return {
        "success": True,
        "stats": stats,
    }


@router.get("/stats/by-subject", response_model=dict)
async def get_stats_by_subject(
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    按学科统计错题分布
    """
    stats = await crud_question.get_stats_by_subject(db, user_id)
    
    return {
        "success": True,
        "stats": stats,
    }


@router.get("/stats/by-difficulty", response_model=dict)
async def get_stats_by_difficulty(
    subject: Optional[str] = Query(None, description="学科筛选"),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    按难度统计错题分布
    """
    stats = await crud_question.get_stats_by_difficulty(db, user_id, subject)
    
    return {
        "success": True,
        "stats": stats,
    }


@router.get("/export/json", response_model=dict)
async def export_questions_json(
    subject: Optional[str] = Query(None, description="学科筛选"),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    导出错题为JSON格式
    """
    questions = await crud_question.get_all_user_questions(db, user_id, subject)
    
    export_data = []
    for question in questions:
        export_data.append({
            "id": question.id,
            "content": question.content,
            "subject": question.subject.value if hasattr(question.subject, 'value') else str(question.subject),
            "difficulty": question.difficulty.value if hasattr(question.difficulty, 'value') else str(question.difficulty),
            "grade": question.grade,
            "student_answer": question.student_answer,
            "correct_answer": question.correct_answer,
            "explanation": question.explanation,
            "error_analysis": question.error_analysis,
            "knowledge_points": question.knowledge_points,
            "chapter": question.chapter,
            "tags": question.tags,
            "suggested_questions": question.suggested_questions,
            "created_at": question.created_at.isoformat() if question.created_at else None,
            "last_reviewed_at": question.last_reviewed_at.isoformat() if question.last_reviewed_at else None,
            "review_count": question.review_count,
            "mastery_level": question.mastery_level,
        })
    
    return {
        "success": True,
        "count": len(export_data),
        "questions": export_data,
        "exported_at": datetime.now().isoformat(),
    }


@router.post("/batch-delete", status_code=204)
async def batch_delete_questions(
    question_ids: List[int],
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    批量删除错题
    """
    success = await crud_question.batch_delete_questions(db, question_ids, user_id)
    if not success:
        raise HTTPException(
            status_code=400,
            detail="批量删除失败，请确保所有错题都属于当前用户"
        )