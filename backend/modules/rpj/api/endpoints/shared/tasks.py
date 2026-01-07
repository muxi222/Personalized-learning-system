"""RPJ - Tasks API（学生实现版 / Stub）

仅保留主要入口 endpoints 的定义，删除具体实现。
参考：`backend/modules/tony/api/endpoints/shared/tasks.py`
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.db.session import get_db
from backend.core.schemas.task import TaskStatusResponse
from backend.modules.rpj.api.deps import get_current_user_id

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str = Path(...), db: AsyncSession = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    """TODO(student): 任务状态/任务流入口。"""
    raise HTTPException(status_code=501, detail="Not Implemented: get_task_status")

@router.get("/{task_id}/stream")
async def stream_task_status(task_id: str = Path(...), db: AsyncSession = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    """TODO(student): 任务状态/任务流入口。"""
    raise HTTPException(status_code=501, detail="Not Implemented: stream_task_status")

@router.delete("/{task_id}", status_code=204)
async def delete_task(task_id: str = Path(...), db: AsyncSession = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    """TODO(student): 任务状态/任务流入口。"""
    raise HTTPException(status_code=501, detail="Not Implemented: delete_task")

