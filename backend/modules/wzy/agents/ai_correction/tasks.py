"""
WZY Celery Utilities - Task status management
Adapted from tony module for WZY.
"""

import logging
from typing import Optional
from datetime import datetime

from backend.core.db.session import async_session_maker
from backend.core.crud.crud_task import (
    create_task,
    update_task_status as update_task_status_db,
    mark_task_failed as mark_task_failed_db,
    complete_task as complete_task_db,
)

logger = logging.getLogger(__name__)


def run_async(async_func):
    """同步运行异步函数（用于Celery任务）"""
    import asyncio
    
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    
    return loop.run_until_complete(async_func)


async def create_new_task(
    task_id: str,
    task_type: str,
    user_id: int,
    metadata: Optional[dict] = None,
) -> bool:
    """创建新任务记录"""
    try:
        async with async_session_maker() as session:
            task_data = {
                "task_id": task_id,
                "task_type": task_type,
                "user_id": user_id,
                "status": "pending",
                "metadata": metadata or {},
            }
            
            task = await create_task(session, task_data)
            await session.commit()
            
            logger.info(f"[WZY] Created task {task_id} of type {task_type} for user {user_id}")
            return True
            
    except Exception as e:
        logger.error(f"[WZY] Failed to create task {task_id}: {e}")
        return False


async def update_task_status(
    task_id: str,
    status: str,
    progress: float = 0.0,
    current_step: str = "",
    result_id: Optional[int] = None,
    error_message: Optional[str] = None,
):
    """更新任务状态"""
    try:
        async with async_session_maker() as session:
            update_data = {
                "status": status,
                "progress": progress,
                "current_step": current_step,
            }
            
            if result_id:
                update_data["result_id"] = result_id
            
            if error_message:
                update_data["error_message"] = error_message
            
            if status == "completed":
                update_data["completed_at"] = datetime.utcnow()
            elif status == "processing":
                update_data["started_at"] = datetime.utcnow()
            
            await update_task_status_db(session, task_id, update_data)
            await session.commit()
            
            logger.debug(f"[WZY] Updated task {task_id}: {status} ({progress}%) - {current_step}")
            
    except Exception as e:
        logger.error(f"[WZY] Failed to update task {task_id}: {e}")


async def mark_task_failed(
    task_id: str,
    error_message: str,
):
    """标记任务失败"""
    try:
        async with async_session_maker() as session:
            await mark_task_failed_db(session, task_id, error_message)
            await session.commit()
            
            logger.warning(f"[WZY] Marked task {task_id} as failed: {error_message}")
            
    except Exception as e:
        logger.error(f"[WZY] Failed to mark task {task_id} as failed: {e}")


async def complete_task(
    task_id: str,
    result_id: int,
):
    """完成任务"""
    try:
        async with async_session_maker() as session:
            await complete_task_db(session, task_id, result_id)
            await session.commit()
            
            logger.info(f"[WZY] Completed task {task_id} with result {result_id}")
            
    except Exception as e:
        logger.error(f"[WZY] Failed to complete task {task_id}: {e}")