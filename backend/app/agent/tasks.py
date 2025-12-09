"""
Celery Tasks for Agent
异步任务定义
"""

import logging
import asyncio
from typing import Optional, List

from ..core.celery_app import celery_app

logger = logging.getLogger(__name__)


def run_async(coro):
    """Helper to run async functions in sync context"""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(coro)


@celery_app.task(bind=True, max_retries=3)
def process_question_task(
    self,
    task_id: str,
    raw_input: str,
    user_id: int,
    image_urls: Optional[List[str]] = None,
):
    """
    处理错题的Celery任务
    
    Args:
        task_id: 任务ID
        raw_input: 原始输入文本
        user_id: 用户ID
        image_urls: 图片URL列表
    """
    logger.info(f"[Celery] Starting task {task_id} for user {user_id}")

    try:
        result = run_async(
            _process_question_async(task_id, raw_input, user_id, image_urls)
        )
        logger.info(f"[Celery] Task {task_id} completed successfully")
        return result
    except Exception as e:
        logger.error(f"[Celery] Task {task_id} failed: {e}")
        # Mark task as failed in database
        run_async(_mark_task_failed(task_id, str(e)))
        raise self.retry(exc=e, countdown=60)


async def _process_question_async(
    task_id: str,
    raw_input: str,
    user_id: int,
    image_urls: Optional[List[str]] = None,
) -> dict:
    """异步处理错题"""
    from .graph import get_main_graph
    from ..db.session import async_session_maker
    from ..crud.crud_task import update_task_status
    from ..db.models import TaskStatusEnum

    # Update task status to processing
    async with async_session_maker() as session:
        await update_task_status(
            db=session,
            task_id=task_id,
            status=TaskStatusEnum.PROCESSING,
            progress=5.0,
            current_step="initializing",
        )
        await session.commit()

    # Prepare initial state
    initial_state = {
        "raw_input": raw_input,
        "user_id": user_id,
        "task_id": task_id,
        "image_urls": image_urls or [],
        "errors": [],
    }

    # Get and run the agent graph
    graph = get_main_graph()

    # Run graph with progress updates
    final_state = None
    async for state in graph.astream(initial_state):
        # Each step returns partial state
        if state:
            # Get the node name and its output
            for node_name, node_output in state.items():
                if isinstance(node_output, dict):
                    final_state = {**initial_state, **(final_state or {}), **node_output}

                    # Update progress in database
                    progress = node_output.get("progress", 0)
                    current_step = node_output.get("current_step", node_name)

                    async with async_session_maker() as session:
                        await update_task_status(
                            db=session,
                            task_id=task_id,
                            status=TaskStatusEnum.PROCESSING,
                            progress=progress,
                            current_step=current_step,
                        )
                        await session.commit()

    return {
        "task_id": task_id,
        "question_id": final_state.get("question_id") if final_state else None,
        "errors": final_state.get("errors", []) if final_state else [],
    }


async def _mark_task_failed(task_id: str, error_message: str):
    """标记任务失败"""
    from ..db.session import async_session_maker
    from ..crud.crud_task import fail_task

    async with async_session_maker() as session:
        await fail_task(session, task_id, error_message)
        await session.commit()


@celery_app.task(bind=True, max_retries=2)
def reanalyze_question_task(
    self,
    task_id: str,
    question_id: int,
):
    """
    重新分析已有错题的Celery任务
    """
    logger.info(f"[Celery] Starting reanalysis task {task_id} for question {question_id}")

    try:
        result = run_async(
            _reanalyze_question_async(task_id, question_id)
        )
        logger.info(f"[Celery] Reanalysis task {task_id} completed")
        return result
    except Exception as e:
        logger.error(f"[Celery] Reanalysis task {task_id} failed: {e}")
        run_async(_mark_task_failed(task_id, str(e)))
        raise self.retry(exc=e, countdown=30)


async def _reanalyze_question_async(task_id: str, question_id: int) -> dict:
    """异步重新分析错题"""
    from .graph import get_analysis_graph
    from ..db.session import async_session_maker
    from ..crud.crud_question import get_question
    from ..crud.crud_task import update_task_status
    from ..db.models import TaskStatusEnum

    # Get question from database
    async with async_session_maker() as session:
        question = await get_question(session, question_id)
        if not question:
            raise ValueError(f"Question {question_id} not found")

        # Prepare state from existing question
        initial_state = {
            "task_id": task_id,
            "question_id": question_id,
            "user_id": question.user_id,
            "raw_input": question.content,
            "structured_data": {
                "content": question.content,
                "student_answer": question.student_answer,
                "correct_answer": question.correct_answer,
            },
            "subject": question.subject.value if question.subject else "other",
            "difficulty": question.difficulty.value if question.difficulty else "medium",
            "knowledge_points": question.knowledge_points or [],
            "errors": [],
        }

    # Update task status
    async with async_session_maker() as session:
        await update_task_status(
            db=session,
            task_id=task_id,
            status=TaskStatusEnum.PROCESSING,
            progress=50.0,
            current_step="analyze_error",
        )
        await session.commit()

    # Run analysis-only graph
    graph = get_analysis_graph()

    final_state = None
    async for state in graph.astream(initial_state):
        for node_name, node_output in state.items():
            if isinstance(node_output, dict):
                final_state = {**initial_state, **(final_state or {}), **node_output}

    return {
        "task_id": task_id,
        "question_id": question_id,
        "success": True,
    }

