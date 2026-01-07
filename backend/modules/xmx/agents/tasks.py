"""
Agent Tasks - Celery 异步任务定义

所有 Agent 工作流的 Celery 任务入口
支持:
- 错题录入任务
- 相似题目检索任务
- OCR 试卷批改任务
"""

import logging
import asyncio
from typing import Optional, List

from backend.modules.xmx.celery_app import celery_app

logger = logging.getLogger(__name__)

def run_async(coro):
    """Helper to run async functions in sync context"""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(coro)

async def _update_task_status(task_id: str, status: str, progress: float, current_step: str):
    """更新任务状态"""
    from backend.core.db.session import async_session_maker
    from backend.core.crud.crud_task import update_task_status
    from backend.core.db.models import TaskStatusEnum

    status_map = {
        "processing": TaskStatusEnum.PROCESSING,
        "completed": TaskStatusEnum.COMPLETED,
        "failed": TaskStatusEnum.FAILED,
    }

    async with async_session_maker() as session:
        await update_task_status(
            db=session,
            task_id=task_id,
            status=status_map.get(status, TaskStatusEnum.PROCESSING),
            progress=progress,
            current_step=current_step,
        )
        await session.commit()

async def _mark_task_failed(task_id: str, error_message: str):
    """标记任务失败"""
    from backend.core.db.session import async_session_maker
    from backend.core.crud.crud_task import fail_task

    async with async_session_maker() as session:
        await fail_task(session, task_id, error_message)
        await session.commit()

# ============ 错题录入任务 ============

@celery_app.task(bind=True, max_retries=3)
def process_question_task(
    self,
    task_id: str,
    raw_input: str,
    user_id: int,
    image_urls: Optional[List[str]] = None,
    student_answer: Optional[str] = None,
):
    """
    处理错题的Celery任务

    Args:
        task_id: 任务ID
        raw_input: 原始输入文本
        user_id: 用户ID
        image_urls: 图片URL列表
        student_answer: 学生答案
    """
    logger.info(f"[Celery] Starting question intake task {task_id} for user {user_id}")

    try:
        result = run_async(
            _process_question_async(task_id, raw_input, user_id, image_urls, student_answer)
        )
        logger.info(f"[Celery] Task {task_id} completed successfully")
        return result
    except Exception as e:
        logger.error(f"[Celery] Task {task_id} failed: {e}")
        run_async(_mark_task_failed(task_id, str(e)))
        raise self.retry(exc=e, countdown=60)

async def _process_question_async(
    task_id: str,
    raw_input: str,
    user_id: int,
    image_urls: Optional[List[str]] = None,
    student_answer: Optional[str] = None,
) -> dict:
    """异步处理错题"""
    from .intake.question_intake_agent import QuestionIntakeAgent

    await _update_task_status(task_id, "processing", 5.0, "initializing")

    agent = QuestionIntakeAgent()
    result = await agent.process(
        raw_input=raw_input,
        user_id=user_id,
        task_id=task_id,
        image_urls=image_urls,
        student_answer=student_answer,
    )

    return result

# ============ 相似题目检索任务 ============

@celery_app.task(bind=True, max_retries=2)
def find_similar_questions_task(
    self,
    task_id: str,
    question_id: int,
    user_id: int,
    top_k: int = 5,
):
    """
    查找相似题目的Celery任务

    Args:
        task_id: 任务ID
        question_id: 原题ID
        user_id: 用户ID
        top_k: 返回数量
    """
    logger.info(f"[Celery] Starting similar question task {task_id} for question {question_id}")

    try:
        result = run_async(
            _find_similar_async(task_id, question_id, user_id, top_k)
        )
        logger.info(f"[Celery] Similar task {task_id} completed")
        return result
    except Exception as e:
        logger.error(f"[Celery] Similar task {task_id} failed: {e}")
        run_async(_mark_task_failed(task_id, str(e)))
        raise self.retry(exc=e, countdown=30)

async def _find_similar_async(
    task_id: str,
    question_id: int,
    user_id: int,
    top_k: int,
) -> dict:
    """异步查找相似题目"""
    from .learning.similar_question_agent import SimilarQuestionAgent

    await _update_task_status(task_id, "processing", 10.0, "searching")

    agent = SimilarQuestionAgent()
    result = await agent.process(
        question_id=question_id,
        user_id=user_id,
        task_id=task_id,
        top_k=top_k,
    )

    return result

# ============ OCR 试卷批改任务 ============

@celery_app.task(bind=True, max_retries=2)
def ocr_exam_task(
    self,
    task_id: str,
    image_path: str,
    user_id: int,
    subject: str = "math",
):
    """
    OCR试卷批改的Celery任务

    Args:
        task_id: 任务ID
        image_path: 图片路径
        user_id: 用户ID
        subject: 学科 (math, physics, chemistry, english, chinese)
    """
    logger.info(f"[Celery] Starting OCR task {task_id} for user {user_id}")

    try:
        result = run_async(
            _ocr_exam_async(task_id, image_path, user_id, subject)
        )
        logger.info(f"[Celery] OCR task {task_id} completed")
        return result
    except Exception as e:
        logger.error(f"[Celery] OCR task {task_id} failed: {e}")
        run_async(_mark_task_failed(task_id, str(e)))
        raise self.retry(exc=e, countdown=30)

async def _ocr_exam_async(
    task_id: str,
    image_path: str,
    user_id: int,
    subject: str,
) -> dict:
    """异步OCR批改"""
    from .ai_correction.ocr_agent import OCRAgent

    await _update_task_status(task_id, "processing", 5.0, "ocr_starting")

    agent = OCRAgent()
    result = await agent.process(
        image_path=image_path,
        user_id=user_id,
        task_id=task_id,
        subject=subject,
    )

    return result

# ============ 重新分析任务 ============

@celery_app.task(bind=True, max_retries=2)
def reanalyze_question_task(
    self,
    task_id: str,
    question_id: int,
):
    """
    重新分析已有错题的Celery任务

    Args:
        task_id: 任务ID
        question_id: 题目ID
    """
    logger.info(f"[Celery] Starting reanalysis task {task_id} for question {question_id}")

    try:
        result = run_async(
            _reanalyze_async(task_id, question_id)
        )
        logger.info(f"[Celery] Reanalysis task {task_id} completed")
        return result
    except Exception as e:
        logger.error(f"[Celery] Reanalysis task {task_id} failed: {e}")
        run_async(_mark_task_failed(task_id, str(e)))
        raise self.retry(exc=e, countdown=30)

async def _reanalyze_async(task_id: str, question_id: int) -> dict:
    """异步重新分析"""
    from backend.core.db.session import async_session_maker
    from backend.core.crud.crud_question import get_question
    from .intake.question_intake_agent import QuestionIntakeAgent

    async with async_session_maker() as session:
        question = await get_question(session, question_id)
        if not question:
            raise ValueError(f"Question {question_id} not found")

    await _update_task_status(task_id, "processing", 50.0, "reanalyzing")

    agent = QuestionIntakeAgent()
    result = await agent.process(
        raw_input=question.content,
        user_id=question.user_id,
        task_id=task_id,
        student_answer=question.student_answer,
    )

    return result

# ============ 批量处理任务 ============

@celery_app.task(bind=True, max_retries=1)
def batch_ocr_task(
    self,
    task_id: str,
    image_paths: List[str],
    user_id: int,
    subject: str = "math",
):
    """
    批量OCR处理任务

    Args:
        task_id: 任务ID
        image_paths: 图片路径列表
        user_id: 用户ID
        subject: 学科
    """
    logger.info(f"[Celery] Starting batch OCR task {task_id} with {len(image_paths)} images")

    try:
        results = []
        for i, path in enumerate(image_paths):
            sub_task_id = f"{task_id}_sub_{i}"
            result = run_async(_ocr_exam_async(sub_task_id, path, user_id, subject))
            results.append(result)

            # 更新总进度
            progress = ((i + 1) / len(image_paths)) * 100
            run_async(_update_task_status(task_id, "processing", progress, f"processing_{i+1}/{len(image_paths)}"))

        logger.info(f"[Celery] Batch OCR task {task_id} completed")
        return {"task_id": task_id, "results": results}

    except Exception as e:
        logger.error(f"[Celery] Batch OCR task {task_id} failed: {e}")
        run_async(_mark_task_failed(task_id, str(e)))
        raise self.retry(exc=e, countdown=60)
