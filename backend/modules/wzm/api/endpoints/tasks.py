"""
任务状态API (WZM模块 - 学生实现版本)

本文件为框架代码，需要学生完成核心业务逻辑的实现。
完整实现请参考: backend/modules/tony/api/endpoints/tasks.py

WZM模块支持的学科: chemistry
"""

import logging
from typing import Optional, Any
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.db.session import get_db
from backend.core.crud import crud_task
from backend.core.schemas.task import TaskStatusResponse, TaskStatus
from backend.modules.wzm.api.deps import get_current_user_id
from backend.modules.wzm.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()

def _extract_image_id(task_result: Any) -> Optional[int]:
    if not isinstance(task_result, dict):
        return None
    stages = task_result.get("stages")
    if not isinstance(stages, dict):
        return None
    for path in [("saved", "source_image_id"), ("uploaded", "image_id"), ("uploaded", "source_image_id")]:
        cur: Any = stages
        ok = True
        for k in path:
            if not isinstance(cur, dict) or k not in cur:
                ok = False
                break
            cur = cur.get(k)
        if ok:
            try:
                v = int(cur)
                if v > 0:
                    return v
            except Exception:
                pass
    return None

def validate_subject(subject: str) -> None:
    """验证学科是否属于WZM模块"""
    if subject not in settings.SUBJECTS:
        raise HTTPException(
            status_code=400,
            detail=f"Subject '{subject}' is not supported by WZM module. "
                   f"Supported subjects: {settings.SUBJECTS}"
        )

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
        image_id=_extract_image_id(task.result if isinstance(task.result, dict) else None),
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

# ============================================================
# TODO: 学生需要实现以下API endpoints
# ============================================================
#
# 请参考完整实现: backend/modules/tony/api/endpoints/tasks.py
#
# 实现步骤:
# 1. 复制TONY模块对应文件的函数签名和路由装饰器
# 2. 保留学科验证逻辑 (validate_subject)
# 3. 实现业务逻辑（数据库查询、Agent调用等）
# 4. 返回正确的响应数据
#
# 提示:
# - 所有数据库操作使用 backend/core/crud/ 中的函数
# - 所有Agent操作使用 backend/modules/wzm/agents/ 中的类
# - 所有Schema使用 backend/core/schemas/ 中的定义
# ============================================================

# TODO: 在这里添加endpoint实现
# 示例:
# @router.get("/example")
# async def example_endpoint():
#     """示例端点"""
#     return {"message": "学生TODO: 实现此endpoint"}
