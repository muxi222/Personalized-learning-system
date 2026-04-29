"""
TONY Agents - Learning Tasks (Celery)

Learning module: "学习建议 / 举一反三" (similar questions).
Moved from agents/tasks.py without logic changes.
"""

import logging

from backend.modules.tony.celery_app import celery_app
from backend.modules.tony.agents.shared.celery_utils import run_async, update_task_status, mark_task_failed

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=2)
def find_similar_questions_task(
    self,
    task_id: str,
    question_id: int,
    user_id: int,
    top_k: int = 5,
):
    """查找相似题目的Celery任务"""
    logger.info(f"[Celery] Starting similar question task {task_id} for question {question_id}")

    try:
        result = run_async(_find_similar_async(task_id, question_id, user_id, top_k))
        logger.info(f"[Celery] Similar task {task_id} completed")
        return result
    except Exception as e:
        logger.error(f"[Celery] Similar task {task_id} failed: {e}")
        run_async(mark_task_failed(task_id, str(e)))
        raise self.retry(exc=e, countdown=30)


async def _find_similar_async(
    task_id: str,
    question_id: int,
    user_id: int,
    top_k: int,
) -> dict:
    """异步查找相似题目"""
    from .similar_question_agent import SimilarQuestionAgent

    await update_task_status(task_id, "processing", 10.0, "searching")

    agent = SimilarQuestionAgent()
    result = await agent.process(
        question_id=question_id,
        user_id=user_id,
        task_id=task_id,
        top_k=top_k,
    )
    return result


