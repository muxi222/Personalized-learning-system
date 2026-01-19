"""
WZY Agents - Learning Tasks (Celery)

Learning module: "学习建议 / 举一反三" (similar questions).
WZY 只处理数学和物理学科。
"""

import logging

from backend.modules.wzy.celery_app import celery_app
from backend.modules.wzy.agents.shared.celery_utils import run_async, update_task_status, mark_task_failed

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=2)
def find_similar_questions_task(
    self,
    task_id: str,
    question_id: int,
    user_id: int,
    top_k: int = 5,
):
    """查找相似题目的Celery任务 - WZY版本"""
    logger.info(f"[Celery] Starting WZY similar question task {task_id} for question {question_id}")

    try:
        result = run_async(_find_similar_async(task_id, question_id, user_id, top_k))
        logger.info(f"[Celery] WZY similar task {task_id} completed")
        return result
    except Exception as e:
        logger.error(f"[Celery] WZY similar task {task_id} failed: {e}")
        run_async(mark_task_failed(task_id, str(e)))
        raise self.retry(exc=e, countdown=30)


async def _find_similar_async(
    task_id: str,
    question_id: int,
    user_id: int,
    top_k: int,
) -> dict:
    """异步查找相似题目 - WZY版本，只处理数学和物理"""
    from backend.core.db.session import async_session_maker
    from backend.core.crud.crud_question import get_question
    from .similar_question_agent import WzySimilarQuestionAgent

    # 获取题目信息以检查学科
    async with async_session_maker() as session:
        question = await get_question(session, question_id)
        if not question:
            raise ValueError(f"Question {question_id} not found")
        
        # 检查学科是否为数学或物理
        if question.subject not in ['数学', '物理']:
            error_msg = f"WZY only supports math and physics, question has {question.subject}"
            await mark_task_failed(task_id, error_msg)
            raise ValueError(error_msg)

    await update_task_status(task_id, "processing", 10.0, f"searching for {question.subject} similar questions")

    agent = WzySimilarQuestionAgent()
    result = await agent.process(
        question_id=question_id,
        user_id=user_id,
        task_id=task_id,
        top_k=top_k,
        subject=question.subject,  # 传递学科信息给代理
    )
    return result