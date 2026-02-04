"""
Tasks API Endpoints
任务状态查询API
"""

import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.db.session import get_db
from backend.core.crud import crud_task
from backend.core.schemas.task import TaskStatusResponse, TaskStatus

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    查询任务状态
    
    返回任务的:
    - 当前状态 (pending/processing/completed/failed)
    - 进度百分比
    - 当前步骤
    - 结果ID (完成后)
    - 错误信息 (失败时)
    """
    task = await crud_task.get_task_by_task_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    # Map database enum to schema enum
    status_map = {
        "pending": TaskStatus.PENDING,
        "processing": TaskStatus.PROCESSING,
        "completed": TaskStatus.COMPLETED,
        "failed": TaskStatus.FAILED,
    }

    return TaskStatusResponse(
        task_id=task.task_id,
        status=status_map.get(task.status.value, TaskStatus.PENDING),
        progress=task.progress or 0.0,
        current_step=task.current_step,
        result_id=task.question_id,
        error_message=task.error_message,
        started_at=task.started_at,
        completed_at=task.completed_at,
        created_at=task.created_at,
    )


@router.delete("/{task_id}", status_code=204)
async def cancel_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    取消任务 (仅限pending状态)
    """
    task = await crud_task.get_task_by_task_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status.value != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel task in {task.status.value} status"
        )

    # Mark as failed/cancelled
    from backend.core.db.models import TaskStatusEnum
    await crud_task.update_task_status(
        db,
        task_id,
        TaskStatusEnum.FAILED,
        error_message="Cancelled by user",
    )
    await db.commit()

