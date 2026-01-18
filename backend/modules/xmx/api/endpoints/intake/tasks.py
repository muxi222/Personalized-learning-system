"""
XMX - Task API Endpoints
任务状态查询、流式输出接口（经济/英语专用）
"""

import json
import logging
import asyncio
from typing import Optional, Dict, Any, AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.db.session import get_db
from backend.core.crud import crud_task
from backend.core.schemas.task import TaskResponse, TaskStatus, TaskDetail
from backend.modules.xmx.api.deps import get_current_user_id

logger = logging.getLogger(__name__)
router = APIRouter()

# 任务状态映射（与数据库/任务系统保持一致）
TASK_STATUS_MAP = {
    "pending": TaskStatus.PENDING,
    "processing": TaskStatus.PROCESSING,
    "completed": TaskStatus.COMPLETED,
    "failed": TaskStatus.FAILED,
}

@router.get("/{task_id}", response_model=TaskDetail)
async def get_task_status(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    查询单个任务状态详情
    """
    try:
        # 查询任务记录（关联用户ID，确保数据隔离）
        task = await crud_task.get_task(db, task_id, user_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found (XMX)")

        # 构建任务详情响应
        task_detail = TaskDetail(
            task_id=task.id,
            status=TASK_STATUS_MAP.get(task.status, TaskStatus.PENDING),
            message=task.message or "",
            progress=task.progress or 0.0,
            created_at=task.created_at,
            updated_at=task.updated_at,
            result=task.result if task.result else {},
            error=task.error or "",
        )

        logger.info(f"[XMX Task] Get status - task_id={task_id} user_id={user_id} status={task_detail.status}")
        return task_detail

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[XMX Task] Failed to get task {task_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get task status: {str(e)}")

@router.get("/{task_id}/stream")
async def stream_task_status(
    task_id: str,
    token: Optional[str] = Query(None),  # 兼容前端传参
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    流式输出任务状态更新（Server-Sent Events）
    前端通过SSE实时获取任务进度和状态
    """
    async def event_generator() -> AsyncGenerator[str, None]:
        # 初始查询任务状态
        try:
            task = await crud_task.get_task(db, task_id, user_id)
            if not task:
                # 发送错误事件后关闭流
                yield f"data: {json.dumps({'error': f'Task {task_id} not found', 'task_id': task_id})}\n\n"
                return

            # 发送初始状态
            initial_data = {
                "task_id": task_id,
                "status": TASK_STATUS_MAP.get(task.status, TaskStatus.PENDING).value,
                "progress": task.progress or 0.0,
                "message": task.message or "",
                "completed": task.status in ["completed", "failed"],
            }
            yield f"data: {json.dumps(initial_data)}\n\n"

            # 轮询更新（直到任务完成/失败）
            max_retries = 600  # 最多轮询10分钟（10*60秒）
            retry_count = 0
            while retry_count < max_retries:
                # 每次查询前刷新数据库会话
                await db.refresh(task)
                
                # 任务完成/失败则退出循环
                if task.status in ["completed", "failed"]:
                    final_data = {
                        "task_id": task_id,
                        "status": TASK_STATUS_MAP.get(task.status, TaskStatus.PENDING).value,
                        "progress": task.progress or 100.0 if task.status == "completed" else 0.0,
                        "message": task.message or "",
                        "result": task.result or {},
                        "error": task.error or "",
                        "completed": True,
                    }
                    yield f"data: {json.dumps(final_data)}\n\n"
                    break

                # 任务仍在处理，发送进度更新
                if task.progress or task.message:
                    update_data = {
                        "task_id": task_id,
                        "status": TASK_STATUS_MAP.get(task.status, TaskStatus.PROCESSING).value,
                        "progress": task.progress or 0.0,
                        "message": task.message or "",
                        "completed": False,
                    }
                    yield f"data: {json.dumps(update_data)}\n\n"

                # 等待1秒后再次查询
                await asyncio.sleep(1)
                retry_count += 1

            # 超时处理
            if retry_count >= max_retries:
                timeout_data = {
                    "task_id": task_id,
                    "status": TaskStatus.FAILED.value,
                    "message": "Task timeout (10 minutes)",
                    "completed": True,
                    "error": "Task polling timeout",
                }
                yield f"data: {json.dumps(timeout_data)}\n\n"

        except Exception as e:
            logger.error(f"[XMX Task Stream] Error for task {task_id}: {e}", exc_info=True)
            error_data = {
                "task_id": task_id,
                "status": TaskStatus.FAILED.value,
                "error": str(e),
                "completed": True,
            }
            yield f"data: {json.dumps(error_data)}\n\n"

    # 返回SSE流式响应
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 禁用Nginx缓冲，确保实时输出
        },
    )

@router.post("/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    取消正在执行的任务
    """
    try:
        task = await crud_task.get_task(db, task_id, user_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"Task {task_id} not found (XMX)")

        # 仅允许取消pending/processing状态的任务
        if task.status in ["completed", "failed"]:
            raise HTTPException(status_code=400, detail=f"Cannot cancel task in {task.status} status")

        # 更新任务状态为取消
        await crud_task.update_task_status(
            db,
            task_id,
            status="failed",  # 用failed标识取消状态
            current_step="Task cancelled by user",
            result_patch={"cancelled": True},
            error="Task cancelled by user",
        )
        await db.commit()

        logger.info(f"[XMX Task] Cancelled - task_id={task_id} user_id={user_id}")
        return {"task_id": task_id, "status": "cancelled", "message": "Task cancelled successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[XMX Task] Failed to cancel task {task_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to cancel task: {str(e)}")