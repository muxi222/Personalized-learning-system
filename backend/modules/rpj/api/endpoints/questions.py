"""
Questions API Endpoints (RPJ模块 - 学生实现版本)
错题相关API

本文件为框架代码，需要学生完成核心业务逻辑的实现。
完整实现请参考: backend/modules/tony/api/endpoints/questions.py
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
from backend.modules.rpj.api.deps import get_current_user_id
from backend.modules.rpj.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()

UPLOAD_DIR = "./data/uploads"


def validate_subject(subject: str) -> None:
    """
    验证学科是否属于RPJ模块

    RPJ模块支持的学科: chinese, english, politics
    """
    if subject not in settings.SUBJECTS:
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
    提交新错题（文字输入）

    工作流程:
    1. 验证学科是否属于RPJ模块
    2. 创建任务记录
    3. 触发QuestionIntakeAgent异步处理
    4. 返回task_id供前端轮询状态

    TODO: 学生需要实现以下功能
    1. 调用QuestionIntakeAgent处理题目
    2. Agent工作流应包括:
       - 解析输入，提取结构化信息
       - 保存到数据库
       - 生成embedding并存入FAISS向量库
       - AI分析错因
       - 生成举一反三推荐

    参考实现: backend/modules/tony/api/endpoints/questions.py
    """
    # 学科验证（已实现）
    validate_subject(question_data.subject)

    # 生成任务ID（已实现）
    task_id = str(uuid.uuid4())

    # ============ TODO 1: 创建任务记录 ============
    # 提示: 使用 crud_task.create_task(db, task_id)
    # await crud_task.create_task(db, task_id)
    # await db.commit()

    # ============ TODO 2: 启动后台处理 ============
    # 提示:
    # 1. 定义异步函数 process_async()
    # 2. 导入并实例化 QuestionIntakeAgent
    # 3. 调用 agent.process() 处理题目
    # 4. 根据结果更新任务状态
    # 5. 使用 background_tasks.add_task() 或 Celery 执行
    #
    # 示例代码结构:
    # async def process_async():
    #     from backend.modules.rpj.agents.question_intake_agent import QuestionIntakeAgent
    #     agent = QuestionIntakeAgent()
    #     result = await agent.process(
    #         raw_input=question_data.content,
    #         user_id=user_id,
    #         task_id=task_id,
    #         ...
    #     )
    #     # 更新任务状态
    #
    # background_tasks.add_task(process_async)

    # ============ 当前返回Mock响应 ============
    logger.info(f"[RPJ] 收到错题提交请求: task_id={task_id}, subject={question_data.subject}")

    return TaskResponse(
        task_id=task_id,
        status=TaskStatus.PENDING,
        message="题目已提交，正在处理中（学生TODO：实现实际处理逻辑）"
    )


@router.post("/ocr", response_model=TaskResponse, status_code=202)
async def create_question_from_image(
    subject: str = Form(...),
    image: UploadFile = File(...),
    background_tasks: BackgroundTasks = None,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    提交新错题（图片OCR识别）

    工作流程:
    1. 验证学科
    2. 保存上传的图片到用户目录
    3. 触发OCR识别和QuestionIntakeAgent处理

    TODO: 学生需要实现以下功能
    1. 保存图片文件到 data/uploads/{username}/questions/{subject}/
    2. 调用 GeminiOCRService 识别题目内容
    3. 将识别结果传递给 QuestionIntakeAgent

    参考实现: backend/modules/tony/api/endpoints/questions.py
    """
    # 学科验证（已实现）
    validate_subject(subject)

    task_id = str(uuid.uuid4())

    # ============ TODO 3: 保存图片文件 ============
    # 提示:
    # 1. 获取用户信息: user = await crud_user.get_user(db, user_id)
    # 2. 构建保存路径: {UPLOAD_DIR}/{username}/questions/{subject}/
    # 3. 生成文件名: {uuid}.{ext}
    # 4. 保存文件: with open(save_path, "wb") as f: f.write(await image.read())

    # ============ TODO 4: OCR识别 ============
    # 提示:
    # 1. 导入: from backend.core.services.gemini_ocr_service import get_gemini_ocr_service
    # 2. 调用: ocr_service = get_gemini_ocr_service()
    # 3. 识别: result = await ocr_service.recognize_question(image_path, subject)
    # 4. 提取文本内容

    # ============ TODO 5: 触发QuestionIntakeAgent ============
    # 提示: 将OCR识别的内容传递给Agent处理

    logger.info(f"[RPJ] 收到OCR错题提交: task_id={task_id}, subject={subject}")

    return TaskResponse(
        task_id=task_id,
        status=TaskStatus.PENDING,
        message="图片已上传，正在识别中（学生TODO：实现OCR和处理逻辑）"
    )


@router.get("/", response_model=QuestionListResponse)
async def list_questions(
    subject: Optional[str] = Query(None, description="学科筛选"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    获取错题列表（分页）

    TODO: 学生需要实现以下功能
    1. 验证学科（如果提供）
    2. 从数据库查询该用户的错题
    3. 按学科过滤（如果指定）
    4. 分页返回结果

    参考实现: backend/modules/tony/api/endpoints/questions.py
    """
    # ============ TODO 6: 学科验证 ============
    # 提示: 如果提供了subject参数，调用 validate_subject(subject)

    # ============ TODO 7: 数据库查询 ============
    # 提示:
    # 1. 使用 crud_question.get_questions_by_user() 查询
    # 2. 添加学科过滤
    # 3. 计算分页参数: skip = (page - 1) * page_size
    # 4. 查询总数: total = await crud_question.count_questions(db, user_id, subject)

    logger.info(f"[RPJ] 查询错题列表: user_id={user_id}, subject={subject}, page={page}")

    # ============ 当前返回Mock响应 ============
    return QuestionListResponse(
        items=[],  # TODO: 返回实际数据
        total=0,
        page=page,
        page_size=page_size,
        message="学生TODO：实现数据库查询逻辑"
    )


@router.get("/{question_id}", response_model=QuestionDetail)
async def get_question(
    question_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    获取错题详情

    TODO: 学生需要实现以下功能
    1. 从数据库查询题目详情
    2. 验证题目所有权（仅返回用户自己的题目）
    3. 返回完整信息（包括错因分析、举一反三等）

    参考实现: backend/modules/tony/api/endpoints/questions.py
    """
    # ============ TODO 8: 查询题目详情 ============
    # 提示:
    # 1. question = await crud_question.get_question(db, question_id)
    # 2. 检查: if not question: raise HTTPException(404)
    # 3. 权限验证: if question.user_id != user_id: raise HTTPException(403)
    # 4. 验证学科: validate_subject(question.subject)

    logger.info(f"[RPJ] 查询错题详情: question_id={question_id}")

    # ============ 当前返回Mock响应 ============
    raise HTTPException(
        status_code=404,
        detail="学生TODO：实现题目详情查询逻辑"
    )


@router.put("/{question_id}", response_model=QuestionResponse)
async def update_question(
    question_id: int,
    question_update: QuestionUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    更新错题信息

    TODO: 学生需要实现以下功能
    1. 验证题目存在和所有权
    2. 更新数据库记录
    3. 如果内容变化，重新生成embedding并更新向量库

    参考实现: backend/modules/tony/api/endpoints/questions.py
    """
    # ============ TODO 9: 更新题目 ============
    # 提示:
    # 1. 查询现有题目
    # 2. 验证所有权和学科
    # 3. 更新数据库: updated = await crud_question.update_question(db, question_id, question_update)
    # 4. 如果content变化，更新向量库

    logger.info(f"[RPJ] 更新错题: question_id={question_id}")

    raise HTTPException(
        status_code=404,
        detail="学生TODO：实现题目更新逻辑"
    )


@router.delete("/{question_id}")
async def delete_question(
    question_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    删除错题

    TODO: 学生需要实现以下功能
    1. 验证题目存在和所有权
    2. 从数据库删除
    3. 从向量库删除对应的embedding

    参考实现: backend/modules/tony/api/endpoints/questions.py
    """
    # ============ TODO 10: 删除题目 ============
    # 提示:
    # 1. 查询题目并验证
    # 2. 从向量库删除: vector_store = get_vector_store_service(); await vector_store.delete_question(question_id)
    # 3. 从数据库删除: await crud_question.delete_question(db, question_id)

    logger.info(f"[RPJ] 删除错题: question_id={question_id}")

    raise HTTPException(
        status_code=404,
        detail="学生TODO：实现题目删除逻辑"
    )


@router.post("/{question_id}/similar", response_model=QuestionListResponse)
async def find_similar_questions(
    question_id: int,
    query: SimilarQuestionQuery,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    查找相似题目（举一反三）

    TODO: 学生需要实现以下功能
    1. 验证题目存在
    2. 使用 SimilarQuestionAgent 查找相似题目
    3. 基于FAISS向量检索 + BM25关键词检索混合搜索
    4. 返回相似题目列表

    参考实现: backend/modules/tony/api/endpoints/questions.py
    """
    # ============ TODO 11: 相似题目检索 ============
    # 提示:
    # 1. 查询原题目
    # 2. 导入: from backend.modules.rpj.agents.similar_question_agent import SimilarQuestionAgent
    # 3. 实例化Agent: agent = SimilarQuestionAgent()
    # 4. 调用: result = await agent.find_similar(question_id, top_k=query.top_k)
    # 5. 返回结果

    logger.info(f"[RPJ] 查找相似题目: question_id={question_id}")

    return QuestionListResponse(
        items=[],
        total=0,
        page=1,
        page_size=query.top_k,
        message="学生TODO：实现相似题目检索逻辑（FAISS + BM25混合检索）"
    )
