"""
Tasks API Endpoints
任务状态查询API
支持轮询和Server-Sent Events (SSE) 流式推送
"""

import os
import logging
import asyncio
import json
from typing import AsyncGenerator, Optional, Any, Dict
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.db.session import get_db
from backend.core.crud import crud_task
from backend.core.schemas.task import TaskStatusResponse, TaskStatus
from backend.modules.wzm.api.deps import get_current_user_id

logger = logging.getLogger(__name__)

router = APIRouter()

def _extract_image_id(task_result: Any) -> Optional[int]:
    """
    Extract image_files.id from productized task result payload.
    We support both:
    - result.stages.saved.source_image_id (final)
    - result.stages.uploaded.image_id / source_image_id (early)
    """
    if not isinstance(task_result, dict):
        return None
    stages = task_result.get("stages")
    if not isinstance(stages, dict):
        stages = {}
    for path in [
        ("saved", "source_image_id"),
        ("uploaded", "image_id"),
        ("uploaded", "source_image_id"),
    ]:
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

@router.get(
    "/{task_id}",
    response_model=TaskStatusResponse,
    response_model_exclude={"result_id"},
)
async def get_task_status(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
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
    if task.user_id is not None and int(task.user_id) != int(user_id):
        raise HTTPException(status_code=404, detail="Task not found")

    # Map database enum to schema enum
    status_map = {
        "pending": TaskStatus.PENDING,
        "processing": TaskStatus.PROCESSING,
        "completed": TaskStatus.COMPLETED,
        "failed": TaskStatus.FAILED,
    }

    task_result = task.result if isinstance(task.result, dict) else None
    image_id = _extract_image_id(task_result)
    return TaskStatusResponse(
        task_id=task.task_id,
        status=status_map.get(task.status.value, TaskStatus.PENDING),
        progress=task.progress or 0.0,
        current_step=task.current_step,
        image_id=image_id,
        error_message=task.error_message,
        result=task_result,
        result_rev=int(task_result.get("_rev", 0)) if isinstance(task_result, dict) else 0,
        last_patch=task_result.get("_last_patch") if isinstance(task_result, dict) else None,
        started_at=task.started_at,
        completed_at=task.completed_at,
        created_at=task.created_at,
    )

@router.delete("/{task_id}", status_code=204)
async def delete_or_cancel_task(
    task_id: str,
    reason: str = Query("用户已取消任务", description="取消原因（可选）"),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    DELETE /tasks/{task_id} semantics:
    - If task is pending/processing: cancel (mark failed) (record kept for background workers).
    - If task is completed/failed: hard-delete the task record.
    """
    task = await crud_task.get_task_by_task_id(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.user_id is not None and int(task.user_id) != int(user_id):
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status.value in ("completed", "failed"):
        deleted = await crud_task.delete_task_by_task_id(db, task_id, user_id=user_id)
        if deleted:
            await db.commit()
        return

    # Mark as failed/cancelled
    from backend.core.db.models import TaskStatusEnum
    await crud_task.update_task_status(
        db,
        task_id,
        TaskStatusEnum.FAILED,
        progress=100.0,
        current_step=(reason or "用户已取消任务")[:200],
        error_message=(reason or "用户已取消任务"),
        result_patch={"status": "failed", "error": "cancelled_by_user", "message": (reason or "用户已取消任务")[:200]},
        result_stage="cancel",
    )
    await db.commit()

@router.get("/{task_id}/stream")
async def stream_task_status(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> StreamingResponse:
    """
    通过Server-Sent Events (SSE) 流式推送任务状态更新
    
    前端可以使用 EventSource 连接此端点，实时接收任务状态更新：
    ```javascript
    const eventSource = new EventSource('/api/v1/tasks/{task_id}/stream');
    eventSource.onmessage = (event) => {
        const data = JSON.parse(event.data);
        console.log('任务状态:', data);
    };
    ```
    """
    async def generate_events() -> AsyncGenerator[str, None]:
        """生成SSE事件流"""
        last_status = None
        last_progress = None
        last_rev = None
        check_count = 0
        max_checks = 1200  # 最多检查5分钟（每0.5秒一次）
        sent_snapshot = False
        
        try:
            while check_count < max_checks:
                # 查询任务状态
                task = await crud_task.get_task_by_task_id(db, task_id)
                if not task:
                    yield f"data: {json.dumps({'error': 'Task not found'})}\n\n"
                    break
                if task.user_id is not None and int(task.user_id) != int(user_id):
                    yield f"data: {json.dumps({'error': 'Task not found'})}\n\n"
                    break
                
                # 检查状态是否有变化
                current_status = task.status.value
                current_progress = task.progress or 0.0
                current_step = task.current_step
                current_result = task.result if isinstance(task.result, dict) else {}
                current_rev = int(current_result.get("_rev", 0)) if isinstance(current_result, dict) else 0
                current_patch = current_result.get("_last_patch") if isinstance(current_result, dict) else None
                current_image_id = _extract_image_id(current_result)
                
                changed = (
                    current_status != last_status
                    or current_progress != last_progress
                    or current_rev != last_rev
                    or check_count == 0
                )
                if changed:
                    
                    # 构建响应数据
                    status_map = {
                        "pending": TaskStatus.PENDING,
                        "processing": TaskStatus.PROCESSING,
                        "completed": TaskStatus.COMPLETED,
                        "failed": TaskStatus.FAILED,
                    }

                    base = {
                        "task_id": task.task_id,
                        "status": status_map.get(current_status, TaskStatus.PENDING).value,
                        "progress": current_progress,
                        "current_step": current_step,
                        "image_id": current_image_id,
                        "error_message": task.error_message,
                        "started_at": task.started_at.isoformat() if task.started_at else None,
                        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
                        "created_at": task.created_at.isoformat() if task.created_at else None,
                        "result_rev": current_rev,
                    }

                    # 第一次：推 snapshot（全量 result）；后续：推 delta（仅 last_patch）
                    if not sent_snapshot:
                        payload = {**base, "event_type": "snapshot", "result": current_result}
                        sent_snapshot = True
                    else:
                        payload = {**base, "event_type": "delta", "patch": current_patch}

                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    
                    last_status = current_status
                    last_progress = current_progress
                    last_rev = current_rev
                    
                    # 如果任务完成或失败，结束流
                    if current_status in ("completed", "failed"):
                        break
                
                # 等待0.5秒后再次检查
                await asyncio.sleep(0.5)
                check_count += 1
                
                # 刷新数据库会话，避免使用过期的数据
                await db.commit()

            # Timeout safeguard: auto-fail stuck tasks to avoid infinite waiting after restarts.
            if check_count >= max_checks:
                try:
                    task = await crud_task.get_task_by_task_id(db, task_id)
                    if task and task.status.value not in ("completed", "failed"):
                        from backend.core.db.models import TaskStatusEnum
                        msg = "任务超时（10分钟无完成），已自动撤销，请重试"
                        await crud_task.update_task_status(
                            db,
                            task_id,
                            TaskStatusEnum.FAILED,
                            progress=100.0,
                            current_step=msg[:200],
                            error_message=msg,
                            result_patch={"status": "failed", "error": "timeout_auto_cancel", "message": msg},
                            result_stage="cancel",
                        )
                        await db.commit()

                        payload = {
                            "task_id": task_id,
                            "status": TaskStatus.FAILED.value,
                            "progress": 100.0,
                            "current_step": msg,
                            "image_id": _extract_image_id(task.result if isinstance(task.result, dict) else {}),
                            "error_message": msg,
                            "event_type": "snapshot",
                            "result": task.result if isinstance(task.result, dict) else {},
                            "result_rev": int(task.result.get("_rev", 0)) if isinstance(task.result, dict) else 0,
                        }
                        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                except Exception as e:
                    logger.error(f"Auto-timeout cancel failed: {e}", exc_info=True)
                
        except Exception as e:
            logger.error(f"Error in task stream: {e}", exc_info=True)
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        finally:
            # 发送结束标记
            yield "event: close\ndata: {}\n\n"
    
    return StreamingResponse(
        generate_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用nginx缓冲
        }
    )
