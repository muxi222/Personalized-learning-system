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
from backend.modules.xmx.api.deps import get_current_user_id
from backend.modules.xmx.config import settings
from backend.core.services.gemini_ocr_service import get_gemini_ocr_service, SubjectType

logger = logging.getLogger(__name__)

router = APIRouter()

UPLOAD_DIR = "./data/uploads"

# 中文学科名称到英文的映射（XMX模块专用）
SUBJECT_NAME_MAP = {
    "历史": "history",
    "地理": "geography",
    "其他": "other",
}

def validate_subject(subject: str) -> None:
    """验证学科是否属于XMX模块"""
    if subject not in settings.SUBJECTS:
        raise HTTPException(
            status_code=400,
            detail=f"Subject '{subject}' is not supported by XMX module. "
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
        from backend.modules.xmx.agents.question_intake_agent import QuestionIntakeAgent

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
    # TODO(student): 学科判定 + 分类归一化（统一模板 v1；与 tony 最新实现对齐的关键能力）
    # 【输入】user_selected_subject=subject_en，text=OCR提取出的题目文本/结构化题目
    # 【输出】对每题生成：
    #   - detected_subject + confidence(0~1)
    #   - chapter: 从 CHAPTER_TAXONOMY[detected_subject] 选 1 个（否则“综合”）
    #   - knowledge_points: 从 KNOWLEDGE_POINT_TAXONOMY[detected_subject] 选 1~3 个（否则“综合”）
    #   - tags: 2~6 个短词（用于检索，避免太碎）
    # 【规则】
    #   - 若 detected_subject != user_selected_subject 且 confidence >= 0.75：提示“学科不匹配”并拒绝入库
    #   - taxonomy 必须收敛：chapter 建议 6~10 个，knowledge_points 建议 10~25 个；同义项合并，避免发散
    # 【推荐 taxonomy 示例（XMX: economics）】
    #   CHAPTER_TAXONOMY = {
    #     "economics": ["供需与弹性", "成本与收益", "市场结构", "宏观经济(国民收入)", "货币与金融", "市场与政策", "国际贸易", "综合"],
    #   }
    #   KNOWLEDGE_POINT_TAXONOMY = {
    #     "economics": ["供给与需求", "价格弹性", "边际分析", "机会成本", "市场失灵", "财政政策", "货币政策", "通货膨胀", "GDP与失业", "汇率与贸易", "综合"],
    #   }
    # 【实现建议】
    #   - OCR 后调用 settings.LLM_API_ENDPOINT 的 /chat/completions（二次判定+归一化）
    #   - 优先更强模型（gemini-3-pro-preview / gpt-5.2），可通过环境变量 XMX_HIGH_ACCURACY_MODEL 覆盖
    # 【参考实现】backend/modules/tony/agents/question_intake_ocr_agent.py（仅 tony 模块完整实现）
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

    # 生成task_id用于后续处理（并作为“本次上传”唯一标识，用于禁止去重）
    task_id = str(uuid.uuid4())

    # 读取文件内容并计算哈希值
    content = await file.read()
    from backend.core.utils.file_utils import calculate_file_hash
    from backend.core.crud import crud_image_file

    # No-dedupe for "question intake" images: same bytes should still create a new image_files.id
    file_hash_raw = calculate_file_hash(content)
    file_hash = calculate_file_hash(content + task_id.encode("utf-8"))

    # 每次上传都保存为新文件（避免物理文件共享导致删除互相影响）
    file_ext = file.filename.split(".")[-1] if file.filename else "jpg"
    filename = f"{task_id.replace('-', '')[:16]}_{file_hash_raw[:16]}.{file_ext}"
    file_path = os.path.join(get_user_upload_dir(UPLOAD_DIR, user, "questions", subject_en), filename)
    with open(file_path, "wb") as f:
        f.write(content)

    img = await crud_image_file.create_image_file(
        db=db,
        file_hash=file_hash,
        user_id=user.id,
        file_type="questions",
        subject=subject_en,
        file_path=file_path,
        file_size=len(content),
        mime_type=file.content_type,
    )
    logger.info(f"New image saved: id={getattr(img, 'id', None)} hash_raw={file_hash_raw[:16]}..., path={file_path}")

    try:

        # 创建任务记录
        await crud_task.create_task(db, task_id)
        await db.commit()

        # 异步处理OCR和分析
        async def process_with_ocr():
            from backend.modules.xmx.agents.question_intake_agent import QuestionIntakeAgent
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
    q = await crud_question.get_question(db, question_id, user_id)
    if not q:
        raise HTTPException(status_code=404, detail="Question not found")
    source_image_id = getattr(q, "source_image_id", None)

    success = await crud_question.delete_question(db, question_id, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="Question not found")

    try:
        from backend.core.crud import crud_image_file
        paths = await crud_image_file.mark_delete_orphan_question_images(
            db,
            user_id=int(user_id),
            image_ids=[int(source_image_id)] if source_image_id else [],
        )
        await db.commit()
        if paths:
            crud_image_file.delete_files_best_effort(paths)
    except Exception as e:
        logger.warning(f"[xmx] cleanup orphan question image failed: {e}")

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
        from backend.modules.xmx.agents.question_intake_agent import analyze_error, update_result
        from backend.modules.xmx.agents.state import QuestionIntakeState
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
    subject: Optional[str] = Query(None, description="学科筛选（可选）"),
    chapter: Optional[str] = Query(None, description="题目类型/章节筛选（可选）"),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    TODO: 学生实现 - 获取需要复习的错题（XMX模块）
    - 支持 subject=economics
    - 支持 chapter 筛选（题目类型/章节）
    - 参考完整实现：default、tony 模块
    """
    if subject and subject not in settings.SUBJECTS:
        raise HTTPException(status_code=400, detail=f"Subject '{subject}' is not supported by xmx. Supported subjects: {settings.SUBJECTS}")
    raise HTTPException(status_code=501, detail="TODO: Implement review/due in XMX module")
