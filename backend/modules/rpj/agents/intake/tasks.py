"""
Intake module: "录入错题" + reanalyze.
Moved from agents/tasks.py without logic changes.
"""

import logging
from typing import Optional, List

from backend.modules.wzm.celery_app import celery_app
from backend.modules.wzm.agents.shared.celery_utils import run_async, update_task_status, mark_task_failed

logger = logging.getLogger(__name__)

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
    """
    logger.info(f"[Celery] Starting question intake task {task_id} for user {user_id}")

    try:
        result = run_async(_process_question_async(task_id, raw_input, user_id, image_urls, student_answer))
        logger.info(f"[Celery] Task {task_id} completed successfully")
        return result
    except Exception as e:
        logger.error(f"[Celery] Task {task_id} failed: {e}")
        run_async(mark_task_failed(task_id, str(e)))
        raise self.retry(exc=e, countdown=60)


async def _process_question_async(
    task_id: str,
    raw_input: str,
    user_id: int,
    image_urls: Optional[List[str]] = None,
    student_answer: Optional[str] = None,
) -> dict:
    """异步处理错题"""
    from .question_intake_agent import QuestionIntakeAgent

    await update_task_status(task_id, "processing", 5.0, "initializing")

    agent = QuestionIntakeAgent()
    result = await agent.process(
        raw_input=raw_input,
        user_id=user_id,
        task_id=task_id,
        image_urls=image_urls,
        student_answer=student_answer,
    )
    return result


@celery_app.task(bind=True, max_retries=2)
def reanalyze_question_task(
    self,
    task_id: str,
    question_id: int,
):
    """重新分析已有错题的Celery任务"""
    logger.info(f"[Celery] Starting reanalysis task {task_id} for question {question_id}")

    try:
        result = run_async(_reanalyze_async(task_id, question_id))
        logger.info(f"[Celery] Reanalysis task {task_id} completed")
        return result
    except Exception as e:
        logger.error(f"[Celery] Reanalysis task {task_id} failed: {e}")
        run_async(mark_task_failed(task_id, str(e)))
        raise self.retry(exc=e, countdown=30)


async def _reanalyze_async(task_id: str, question_id: int) -> dict:
    """异步重新分析"""
    from backend.core.db.session import async_session_maker
    from backend.core.crud.crud_question import get_question
    from .question_intake_agent import QuestionIntakeAgent

    async with async_session_maker() as session:
        question = await get_question(session, question_id)
        if not question:
            raise ValueError(f"Question {question_id} not found")

    await update_task_status(task_id, "processing", 50.0, "reanalyzing")

    agent = QuestionIntakeAgent()
    result = await agent.process(
        raw_input=question.content,
        user_id=question.user_id,
        task_id=task_id,
        student_answer=question.student_answer,
    )
    return result


