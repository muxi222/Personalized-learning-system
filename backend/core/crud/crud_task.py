"""
Task CRUD Operations
Agent任务数据库操作
"""

from datetime import datetime
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import AgentTask, TaskStatusEnum


async def create_task(
    db: AsyncSession,
    task_id: str,
    question_id: Optional[int] = None,
) -> AgentTask:
    """创建新任务"""
    db_task = AgentTask(
        task_id=task_id,
        question_id=question_id,
        status=TaskStatusEnum.PENDING,
        progress=0.0,
    )
    db.add(db_task)
    await db.flush()
    await db.refresh(db_task)
    return db_task


async def get_task(
    db: AsyncSession,
    task_db_id: int,
) -> Optional[AgentTask]:
    """通过数据库ID获取任务"""
    query = select(AgentTask).where(AgentTask.id == task_db_id)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_task_by_task_id(
    db: AsyncSession,
    task_id: str,
) -> Optional[AgentTask]:
    """通过任务UUID获取任务"""
    query = select(AgentTask).where(AgentTask.task_id == task_id)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def update_task_status(
    db: AsyncSession,
    task_id: str,
    status: TaskStatusEnum,
    progress: Optional[float] = None,
    current_step: Optional[str] = None,
    result: Optional[dict] = None,
    error_message: Optional[str] = None,
) -> Optional[AgentTask]:
    """更新任务状态"""
    task = await get_task_by_task_id(db, task_id)
    if not task:
        return None

    task.status = status

    if progress is not None:
        task.progress = progress
    if current_step is not None:
        task.current_step = current_step
    if result is not None:
        task.result = result
    if error_message is not None:
        task.error_message = error_message

    # Update timestamps
    if status == TaskStatusEnum.PROCESSING and task.started_at is None:
        task.started_at = datetime.utcnow()
    elif status in (TaskStatusEnum.COMPLETED, TaskStatusEnum.FAILED):
        task.completed_at = datetime.utcnow()

    await db.flush()
    await db.refresh(task)
    return task


async def update_task_progress(
    db: AsyncSession,
    task_id: str,
    progress: float,
    current_step: str,
) -> Optional[AgentTask]:
    """更新任务进度"""
    return await update_task_status(
        db,
        task_id,
        status=TaskStatusEnum.PROCESSING,
        progress=progress,
        current_step=current_step,
    )


async def complete_task(
    db: AsyncSession,
    task_id: str,
    question_id: int,
    result: Optional[dict] = None,
) -> Optional[AgentTask]:
    """标记任务完成"""
    task = await get_task_by_task_id(db, task_id)
    if not task:
        return None

    task.status = TaskStatusEnum.COMPLETED
    task.progress = 100.0
    task.question_id = question_id
    task.completed_at = datetime.utcnow()
    if result:
        task.result = result

    await db.flush()
    await db.refresh(task)
    return task


async def fail_task(
    db: AsyncSession,
    task_id: str,
    error_message: str,
) -> Optional[AgentTask]:
    """标记任务失败"""
    return await update_task_status(
        db,
        task_id,
        status=TaskStatusEnum.FAILED,
        error_message=error_message,
    )

