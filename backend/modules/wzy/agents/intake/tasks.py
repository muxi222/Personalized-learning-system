"""
WZY Agents - Intake Tasks (Celery)

Intake module: "录入错题" + reanalyze.
WZY 只处理数学和物理学科。
"""

import logging
from typing import Optional, List

from backend.modules.wzy.celery_app import celery_app
from backend.modules.wzy.agents.shared.celery_utils import run_async, update_task_status, mark_task_failed

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3)
def process_question_task(
    self,
    task_id: str,
    raw_input: str,
    user_id: int,
    image_urls: Optional[List[str]] = None,
    student_answer: Optional[str] = None,
    subject: str = None,  # 新增 subject 参数，只能为 '数学' 或 '物理'
):
    """
    处理错题的Celery任务
    WZY 只处理数学和物理学科
    """
    logger.info(f"[Celery] Starting WZY question intake task {task_id} for user {user_id}")
    
    # 学科验证
    if subject not in ['数学', '物理']:
        error_msg = f"WZY only supports math and physics, got {subject}"
        logger.error(f"[Celery] Task {task_id} failed: {error_msg}")
        run_async(mark_task_failed(task_id, error_msg))
        raise ValueError(error_msg)

    try:
        result = run_async(_process_question_async(task_id, raw_input, user_id, image_urls, student_answer, subject))
        logger.info(f"[Celery] WZY task {task_id} completed successfully")
        return result
    except Exception as e:
        logger.error(f"[Celery] WZY task {task_id} failed: {e}")
        run_async(mark_task_failed(task_id, str(e)))
        raise self.retry(exc=e, countdown=60)


async def _process_question_async(
    task_id: str,
    raw_input: str,
    user_id: int,
    image_urls: Optional[List[str]] = None,
    student_answer: Optional[str] = None,
    subject: str = None,
) -> dict:
    """异步处理错题 - WZY版本，只处理数学和物理"""
    from .question_intake_agent import WzyQuestionIntakeAgent

    await update_task_status(task_id, "processing", 5.0, f"initializing for {subject}")

    agent = WzyQuestionIntakeAgent()
    result = await agent.process(
        raw_input=raw_input,
        user_id=user_id,
        task_id=task_id,
        image_urls=image_urls,
        student_answer=student_answer,
        subject=subject,  # 传递学科信息
    )
    return result


@celery_app.task(bind=True, max_retries=2)
def reanalyze_question_task(
    self,
    task_id: str,
    question_id: int,
):
    """重新分析已有错题的Celery任务 - WZY版本"""
    logger.info(f"[Celery] Starting WZY reanalysis task {task_id} for question {question_id}")

    try:
        result = run_async(_reanalyze_async(task_id, question_id))
        logger.info(f"[Celery] WZY reanalysis task {task_id} completed")
        return result
    except Exception as e:
        logger.error(f"[Celery] WZY reanalysis task {task_id} failed: {e}")
        run_async(mark_task_failed(task_id, str(e)))
        raise self.retry(exc=e, countdown=30)


async def _reanalyze_async(task_id: str, question_id: int) -> dict:
    """异步重新分析 - WZY版本"""
    from backend.core.db.session import async_session_maker
    from backend.core.crud.crud_question import get_question
    from .question_intake_agent import WzyQuestionIntakeAgent

    async with async_session_maker() as session:
        question = await get_question(session, question_id)
        if not question:
            raise ValueError(f"Question {question_id} not found")
        
        # 检查学科是否为数学或物理
        if question.subject not in ['数学', '物理']:
            error_msg = f"WZY only supports math and physics, question has {question.subject}"
            await mark_task_failed(task_id, error_msg)
            raise ValueError(error_msg)

    await update_task_status(task_id, "processing", 50.0, f"reanalyzing {question.subject} question")

    agent = WzyQuestionIntakeAgent()
    result = await agent.process(
        raw_input=question.content,
        user_id=question.user_id,
        task_id=task_id,
        student_answer=question.student_answer,
        subject=question.subject,  # 传递学科信息
    )
    return result