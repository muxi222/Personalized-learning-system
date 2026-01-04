"""
TONY Agents - Shared Celery Utils

Shared helpers for running async agent code inside Celery task functions.
Pure refactor: logic is unchanged, only moved out of monolithic tasks.py for clarity.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)


def run_async(coro):
    """Helper to run async functions in sync context (Celery tasks are sync)."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(coro)


async def update_task_status(task_id: str, status: str, progress: float, current_step: str):
    """Update task status in DB (best-effort)."""
    from backend.core.db.session import async_session_maker
    from backend.core.crud.crud_task import update_task_status as _update
    from backend.core.db.models import TaskStatusEnum

    status_map = {
        "processing": TaskStatusEnum.PROCESSING,
        "completed": TaskStatusEnum.COMPLETED,
        "failed": TaskStatusEnum.FAILED,
    }

    async with async_session_maker() as session:
        await _update(
            db=session,
            task_id=task_id,
            status=status_map.get(status, TaskStatusEnum.PROCESSING),
            progress=progress,
            current_step=current_step,
        )
        await session.commit()


async def mark_task_failed(task_id: str, error_message: str):
    """Mark task failed in DB."""
    from backend.core.db.session import async_session_maker
    from backend.core.crud.crud_task import fail_task

    async with async_session_maker() as session:
        await fail_task(session, task_id, error_message)
        await session.commit()


