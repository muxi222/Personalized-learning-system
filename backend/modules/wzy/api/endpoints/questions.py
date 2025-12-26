"""
Questions API Endpoints
错题相关API
"""

import os
import uuid
import logging
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.db.session import get_db
from backend.core.crud import crud_question, crud_task, crud_user
from backend.core.schemas.question import (
    QuestionCreate,
    QuestionUpdate,
    QuestionResponse,
    QuestionDetail,
    QuestionListResponse,
    SimilarQuestionQuery,
)
from backend.core.schemas.task import TaskResponse, TaskStatus
from backend.core.db.models import TaskStatusEnum
from backend.modules.wzy.api.deps import get_current_user_id
from backend.modules.wzy.config import settings
from backend.core.services.gemini_ocr_service import get_gemini_ocr_service, SubjectType

logger = logging.getLogger(__name__)

router = APIRouter()

UPLOAD_DIR = "./data/uploads"

# 中文学科名称到英文的映射（WZY模块专用）
SUBJECT_NAME_MAP = {
    "历史": "history",
    "地理": "geography",
    "其他": "other",
}


def validate_subject(subject: str) -> None:
    """验证学科是否属于WZY模块"""
    if subject not in settings.SUBJECTS:
        raise HTTPException(
            status_code=400,
            detail=f"Subject '{subject}' is not supported by WZY module. "
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
    # In production, this should use Celery
    # Using the new QuestionIntakeAgent (设计文档4.1节)
    
    # For development: use BackgroundTasks
    # For production: use Celery
    async def process_async():
        from backend.modules.wzy.agents.question_intake_agent import QuestionIntakeAgent

        try:
            # 使用新的 QuestionIntakeAgent (设计文档4.1节)
            agent = QuestionIntakeAgent()
            result = await agent.process(
                raw_input=question_data.content,
                user_id=user_id,
                task_id=task_id,
                image_urls=question_data.image_urls,
                student_answer=question_data.student_answer,
            )
            
            if result.get("success"):
                logger.info(f"Task {task_id} completed, question_id={result.get('question_id')}")
            else:
                logger.warning(f"Task {task_id} completed with errors: {result.get('errors')}")

        except Exception as e:
            logger.error(f"Task {task_id} failed: {e}")
            async with async_session_maker() as session:
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
    subject: str = Form("other"),
    difficulty: str = Form("medium"),
    title: Optional[str] = Form(None),
    background_tasks: BackgroundTasks = None,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    上传图片识别错题
    
    支持上传错题图片，自动OCR识别题目内容和答案，
    然后进行结构化存储和AI分析。
    
    流程:
    1. 上传图片并保存到用户专属目录
    2. OCR识别题目内容
    3. 提取题目、学生答案、正确答案
    4. 创建错题记录
    5. 触发AI分析流程
    """
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
        raise HTTPException(status_code=404, detail="User not found")

    # 解析学科
    subject_en = SUBJECT_NAME_MAP.get(subject, subject.lower())
    
    # 读取文件内容并计算哈希值
    content = await file.read()
    from backend.core.utils.file_utils import calculate_file_hash, get_filename_from_path
    from backend.core.crud import crud_image_file
    
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
    
    if existing_image:
        # 图片已存在，复用现有文件
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
        file_path = os.path.join(
            get_user_upload_dir(UPLOAD_DIR, user, "questions", subject_en),
            filename
        )
        
        # 保存文件
        with open(file_path, "wb") as f:
            f.write(content)
        
        # 创建图片文件记录
        await crud_image_file.create_image_file(
            db=db,
            file_hash=file_hash,
            user_id=user.id,
            file_type="questions",
            subject=subject_en,
            file_path=file_path,
            file_size=len(content),
            mime_type=file.content_type,
        )
        logger.info(f"New image saved: hash={file_hash[:16]}..., path={file_path}")

    try:

        # 创建任务记录
        await crud_task.create_task(db, task_id)
        await db.commit()

        # 异步处理OCR和分析
        async def process_with_ocr():
            from backend.modules.wzy.agents.question_intake_agent import QuestionIntakeAgent
            from backend.core.db.session import async_session_maker

            try:
                # 1. OCR识别
                ocr_service = get_gemini_ocr_service()
                await ocr_service.initialize()

                # 解析学科类型 - 支持中文和英文
                subject_en = SUBJECT_NAME_MAP.get(subject, subject.lower())
                try:
                    subject_type = SubjectType(subject_en)
                except ValueError:
                    subject_type = SubjectType.OTHER

                # 使用OCR识别单个题目（不是试卷批改，而是错题录入）
                logger.info(f"Starting OCR for question image: {file_path}")
                
                # 使用简化的prompt进行单题识别
                from backend.core.services.gemini_ocr_service import GeminiOCRService
                ocr_result = await ocr_service._analyze_image(
                    image_path=file_path,
                    prompt=f"""你是一个专业的学习助手。请识别图片中的错题，提取以下信息（如果图片中没有某项信息，请留空）：

1. **题目内容**: 完整的题目描述
2. **学生答案**: 学生写的答案（如果有）
3. **正确答案**: 正确的答案（如果有标注）
4. **题目类型**: 选择题/填空题/解答题等
5. **知识点**: 涉及的知识点（如果能识别）

请以JSON格式返回，格式如下：
{{
  "question_content": "题目内容",
  "student_answer": "学生答案",
  "correct_answer": "正确答案",
  "question_type": "题目类型",
  "knowledge_points": ["知识点1", "知识点2"]
}}

如果图片模糊或无法识别，请说明原因。"""
                )

                # 解析OCR结果
                import json
                import re
                
                # 尝试从结果中提取JSON
                json_match = re.search(r'\{[\s\S]*\}', ocr_result)
                if json_match:
                    ocr_data = json.loads(json_match.group())
                else:
                    # 如果没有JSON格式，使用原始文本作为题目内容
                    ocr_data = {
                        "question_content": ocr_result,
                        "student_answer": "",
                        "correct_answer": "",
                        "question_type": "",
                        "knowledge_points": []
                    }

                logger.info(f"OCR completed for task {task_id}: {ocr_data}")

                # 2. 使用QuestionIntakeAgent处理
                agent = QuestionIntakeAgent()
                result = await agent.process(
                    raw_input=ocr_data.get("question_content", ""),
                    user_id=user_id,
                    task_id=task_id,
                    image_urls=[file_path],
                    student_answer=ocr_data.get("student_answer", ""),
                    correct_answer=ocr_data.get("correct_answer", ""),
                    subject=subject,
                    difficulty=difficulty,
                    title=title or "OCR识别错题",
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
        )

    except Exception as e:
        logger.error(f"Failed to process image upload: {e}")
        # 清理文件
        if os.path.exists(file_path):
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
        raise HTTPException(status_code=404, detail="Question not found")

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
        raise HTTPException(status_code=404, detail="Question not found")

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
        raise HTTPException(status_code=404, detail="Question not found")


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
        raise HTTPException(status_code=404, detail="Question not found")

    # Create new task
    task_id = str(uuid.uuid4())
    await crud_task.create_task(db, task_id, question_id)
    await db.commit()

    # Start background reanalysis using new agent
    async def reanalyze_async():
        from backend.modules.wzy.agents.question_intake_agent import analyze_error, update_result
        from backend.modules.wzy.agents.state import QuestionIntakeState
        from backend.core.db.session import async_session_maker

        try:
            # 构建状态
            state: QuestionIntakeState = {
                "task_id": task_id,
                "question_id": question_id,
                "user_id": user_id,
                "raw_input": question.content,
                "structured_data": {
                    "question_body": question.content,
                    "student_answer": question.student_answer,
                    "correct_answer": question.correct_answer,
                },
                "subject": question.subject.value if question.subject else "other",
                "grade": question.grade or "",
                "chapter": question.chapter or "",
                "knowledge_points": question.knowledge_points or [],
                "errors": [],
            }
            
            # 执行分析
            result = await analyze_error(state)
            state = {**state, **result}
            
            # 更新结果
            await update_result(state)

            async with async_session_maker() as session:
                await crud_task.complete_task(session, task_id, question_id)
                await session.commit()

        except Exception as e:
            logger.error(f"Reanalysis task {task_id} failed: {e}")
            async with async_session_maker() as session:
                await crud_task.fail_task(session, task_id, str(e))
                await session.commit()

    background_tasks.add_task(reanalyze_async)

    return TaskResponse(
        task_id=task_id,
        status=TaskStatus.PENDING,
        message="Reanalysis started.",
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
            raise HTTPException(status_code=404, detail="Question not found")
        query_text = question.content
    elif query.content:
        query_text = query.content
    else:
        raise HTTPException(status_code=400, detail="Provide question_id or content")

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

