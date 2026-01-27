from fastapi import APIRouter, HTTPException
from backend.modules.xmx.agents.shared.tasks import get_task

router = APIRouter()


@router.get("/{task_id}")
async def get_xmx_task(task_id: str):
    """
    XMX 模块 - 查询任务状态
    """
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.get("/{task_id}/stream")
async def stream_xmx_task(task_id: str):
    """
    XMX 模块 - 简化 stream
    """
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task
