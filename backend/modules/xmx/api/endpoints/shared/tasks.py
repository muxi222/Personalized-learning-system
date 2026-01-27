"""
XMX Tasks API Endpoints

与 TONY 的 shared/tasks API 100% 对齐
支持：
- 轮询查询
- SSE 流式状态推送
"""

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
from backend.modules.xmx.api.deps import get_current_user_id

logger = logging.getLogger(__name__)

router = APIRouter()
def _extract_image_id(task_result: Any) -> Optional[int]:
    if not isinstance(task_result, dict):
        return None
    stages = task_result.get("stages") or {}
    for path in [
        ("saved", "source_image_id"),
        ("uploaded", "image_id"),
        ("uploaded", "source_image_id"),
    ]:
        cur = stages
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
    task = await crud_task.get_task_by_task_id(db, task_id)
    if not task or (task.user_id is not None and int(task.user_id) != int(user_id)):
        raise HTTPException(status_code=404, detail="Task not found")

    status_map = {
        "pending": TaskStatus.PENDING,
        "processing": TaskStatus.PROCESSING,
        "completed": TaskStatus.COMPLETED,
        "failed": TaskStatus.FAILED,
    }

    task_result = task.result if isinstance(task.result, dict) else {}
    image_id = _extract_image_id(task_result)

    return TaskStatusResponse(
        task_id=task.task_id,
        status=status_map.get(task.status.value, TaskStatus.PENDING),
        progress=task.progress or 0.0,
        current_step=task.current_step,
        image_id=image_id,
        error_message=task.error_message,
        result=task_result,
        result_rev=int(task_result.get("_rev", 0)),
        last_patch=task_result.get("_last_patch"),
        started_at=task.started_at,
        completed_at=task.completed_at,
        created_at=task.created_at,
    )
@router.delete("/{task_id}", status_code=204)
async def delete_or_cancel_task(
    task_id: str,
    reason: str = Query("用户已取消任务"),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    task = await crud_task.get_task_by_task_id(db, task_id)
    if not task or (task.user_id is not None and int(task.user_id) != int(user_id)):
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status.value in ("completed", "failed"):
        await crud_task.delete_task_by_task_id(db, task_id, user_id=user_id)
        await db.commit()
        return

    from backend.core.db.models import TaskStatusEnum
    await crud_task.update_task_status(
        db,
        task_id,
        TaskStatusEnum.FAILED,
        progress=100.0,
        current_step=reason[:200],
        error_message=reason,
        result_patch={
            "status": "failed",
            "error": "cancelled_by_user",
            "message": reason[:200],
        },
        result_stage="cancel",
    )
    await db.commit()
@router.get("/{task_id}/stream")
async def stream_task_status(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> StreamingResponse:

    async def generate_events() -> AsyncGenerator[str, None]:
        last_status = last_progress = last_rev = None
        sent_snapshot = False

        while True:
            task = await crud_task.get_task_by_task_id(db, task_id)
            if not task or (task.user_id is not None and int(task.user_id) != int(user_id)):
                yield f"data: {json.dumps({'error': 'Task not found'})}\n\n"
                break

            result = task.result if isinstance(task.result, dict) else {}
            rev = int(result.get("_rev", 0))

            changed = (
                task.status.value != last_status
                or task.progress != last_progress
                or rev != last_rev
            )

            if changed:
                payload = {
                    "task_id": task.task_id,
                    "status": task.status.value,
                    "progress": task.progress or 0.0,
                    "current_step": task.current_step,
                    "image_id": _extract_image_id(result),
                    "error_message": task.error_message,
                    "result_rev": rev,
                }

                if not sent_snapshot:
                    payload["event_type"] = "snapshot"
                    payload["result"] = result
                    sent_snapshot = True
                else:
                    payload["event_type"] = "delta"
                    payload["patch"] = result.get("_last_patch")

                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

                last_status = task.status.value
                last_progress = task.progress
                last_rev = rev

                if task.status.value in ("completed", "failed"):
                    break

            await asyncio.sleep(0.5)

        yield "event: close\ndata: {}\n\n"

    return StreamingResponse(
        generate_events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
