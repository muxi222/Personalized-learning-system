"""
Task CRUD Operations
Agent任务数据库操作
"""

from datetime import datetime
from typing import Optional, Any, Dict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import InvalidRequestError

from ..db.models import AgentTask, TaskStatusEnum

def _deep_merge(base: Any, patch: Any) -> Any:
    """Deep-merge dicts; lists/scalars are replaced."""
    if isinstance(base, dict) and isinstance(patch, dict):
        out: Dict[str, Any] = dict(base)
        for k, v in patch.items():
            if k in out:
                out[k] = _deep_merge(out[k], v)
            else:
                out[k] = v
        return out
    return patch

def _merge_task_result(
    existing: Optional[dict],
    *,
    stage: Optional[str],
    patch: dict,
) -> dict:
    """
    Productized task result protocol:
    - Store per-stage artifacts under result["stages"][stage]
    - Maintain monotonically increasing result["_rev"]
    - Store last incremental patch in result["_last_patch"] for SSE delta streaming
    """
    base: dict = existing if isinstance(existing, dict) else {}
    rev = int(base.get("_rev") or 0) + 1
    merged = dict(base)
    merged["_rev"] = rev
    merged["_ts"] = datetime.utcnow().isoformat()
    if stage:
        stages = merged.get("stages") if isinstance(merged.get("stages"), dict) else {}
        prev_stage = stages.get(stage) if isinstance(stages.get(stage), dict) else {}
        stages[stage] = _deep_merge(prev_stage, patch)
        merged["stages"] = stages
        merged["_last_patch"] = {"stage": stage, "patch": patch, "rev": rev}
    else:
        merged = _deep_merge(merged, patch)
        merged["_last_patch"] = {"stage": None, "patch": patch, "rev": rev}
    return merged

async def create_task(
    db: AsyncSession,
    task_id: str,
    question_id: Optional[int] = None,
) -> AgentTask:
    """
    创建新任务（幂等）。

    Notes:
    - In some SQLite legacy schemas / edge cases, `refresh()` may fail with
      InvalidRequestError("Could not refresh instance ..."). We treat refresh
      as best-effort and fall back to querying by task_id.
    """
    existing = await get_task_by_task_id(db, task_id)
    if existing:
        return existing

    db_task = AgentTask(task_id=task_id, question_id=question_id, status=TaskStatusEnum.PENDING, progress=0.0)
    db.add(db_task)
    await db.flush()

    # Best-effort refresh; DO NOT fail request if refresh is not possible (legacy sqlite schemas).
    try:
        await db.refresh(db_task)
    except InvalidRequestError:
        import logging
        logging.getLogger(__name__).warning("[crud_task] refresh(AgentTask) failed; will fallback to query by task_id", exc_info=True)

    # Prefer querying by task_id (stable unique key) if possible
    try:
        task2 = await get_task_by_task_id(db, task_id)
        return task2 or db_task
    except Exception:
        return db_task

async def get_task(
    db: AsyncSession,
    task_db_id: int,
) -> Optional[AgentTask]:
    """通过数据库ID获取任务"""
    # populate_existing: avoid stale identity-map objects with expire_on_commit=False
    query = select(AgentTask).where(AgentTask.id == task_db_id).execution_options(populate_existing=True)
    result = await db.execute(query)
    return result.scalar_one_or_none()

async def get_task_by_task_id(
    db: AsyncSession,
    task_id: str,
) -> Optional[AgentTask]:
    """通过任务UUID获取任务"""
    # populate_existing: avoid stale identity-map objects with expire_on_commit=False
    query = select(AgentTask).where(AgentTask.task_id == task_id).execution_options(populate_existing=True)
    result = await db.execute(query)
    return result.scalar_one_or_none()

async def update_task_status(
    db: AsyncSession,
    task_id: str,
    status: TaskStatusEnum,
    progress: Optional[float] = None,
    current_step: Optional[str] = None,
    result: Optional[dict] = None,
    result_patch: Optional[dict] = None,
    result_stage: Optional[str] = None,
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
    if result_patch is not None:
        task.result = _merge_task_result(task.result, stage=result_stage, patch=result_patch)
    if error_message is not None:
        task.error_message = error_message

    # Update timestamps
    if status == TaskStatusEnum.PROCESSING and task.started_at is None:
        task.started_at = datetime.utcnow()
    elif status in (TaskStatusEnum.COMPLETED, TaskStatusEnum.FAILED):
        task.completed_at = datetime.utcnow()

    await db.flush()
    try:
        await db.refresh(task)
    except InvalidRequestError:
        # Best-effort: caller usually doesn't need a fully refreshed instance
        pass
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
        # Merge completion result into existing stage artifacts (do not overwrite)
        task.result = _deep_merge(task.result if isinstance(task.result, dict) else {}, result)

    await db.flush()
    try:
        await db.refresh(task)
    except InvalidRequestError:
        pass
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
        progress=100.0,
        current_step=(error_message or "任务失败")[:200],
        error_message=error_message,
    )
