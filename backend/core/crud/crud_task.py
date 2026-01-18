"""
Task CRUD Operations
Agent任务数据库操作
"""

from datetime import datetime
from typing import Optional, Any, Dict, Iterable
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.exc import OperationalError

from ..db.models import AgentTask, TaskStatusEnum

def _is_sqlite_locked_error(e: Exception) -> bool:
    msg = str(e).lower()
    return "database is locked" in msg or "database locked" in msg

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
    user_id: Optional[int] = None,
    question_id: Optional[int] = None,
) -> AgentTask:
    """
    创建新任务（幂等）。

    Notes:
    - In some SQLite legacy schemas / edge cases, `refresh()` may fail with
      InvalidRequestError("Could not refresh instance ..."). We treat refresh
      as best-effort and fall back to querying by task_id.
    """
    import asyncio
    import logging

    # SQLite can temporarily fail writes under concurrency ("database is locked").
    # Retry a few times with backoff to avoid surfacing 500s for transient contention.
    for attempt in range(6):
        try:
            existing = await get_task_by_task_id(db, task_id)
            if existing:
                return existing

            db_task = AgentTask(
                task_id=task_id,
                user_id=user_id,
                question_id=question_id,
                status=TaskStatusEnum.PENDING,
                progress=0.0,
            )
            db.add(db_task)
            await db.flush()

            # Best-effort refresh; DO NOT fail request if refresh is not possible (legacy sqlite schemas).
            try:
                await db.refresh(db_task)
            except InvalidRequestError:
                logging.getLogger(__name__).warning(
                    "[crud_task] refresh(AgentTask) failed; will fallback to query by task_id", exc_info=True
                )

            # Prefer querying by task_id (stable unique key) if possible
            try:
                task2 = await get_task_by_task_id(db, task_id)
                return task2 or db_task
            except Exception:
                return db_task
        except OperationalError as e:
            await db.rollback()
            if _is_sqlite_locked_error(e) and attempt < 5:
                await asyncio.sleep(0.15 * (2**attempt))
                continue
            raise

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


async def delete_task_by_task_id(
    db: AsyncSession,
    task_id: str,
    *,
    user_id: Optional[int] = None,
) -> bool:
    """
    Hard-delete a task row by task_id.

    Security:
    - If user_id is provided, only delete tasks that belong to that user.
    """
    import asyncio

    for attempt in range(6):
        try:
            q = delete(AgentTask).where(AgentTask.task_id == task_id)
            if user_id is not None:
                q = q.where(AgentTask.user_id == user_id)
            res = await db.execute(q)
            await db.flush()
            return bool(res.rowcount and res.rowcount > 0)
        except OperationalError as e:
            await db.rollback()
            if _is_sqlite_locked_error(e) and attempt < 5:
                await asyncio.sleep(0.15 * (2**attempt))
                continue
            raise


async def list_active_tasks_for_user(
    db: AsyncSession,
    user_id: int,
    statuses: Iterable[TaskStatusEnum] = (TaskStatusEnum.PENDING, TaskStatusEnum.PROCESSING),
    limit: int = 50,
) -> list[AgentTask]:
    """
    List active tasks for a user. Used for per-user intake concurrency limits.
    """
    statuses_list = list(statuses)
    query = (
        select(AgentTask)
        .where(AgentTask.user_id == user_id)
        .where(AgentTask.status.in_(statuses_list))
        .order_by(AgentTask.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(query)
    return list(result.scalars().all())


def _task_result_get_input_type(task: AgentTask) -> Optional[str]:
    try:
        r = task.result if isinstance(task.result, dict) else {}
        return (
            r.get("stages", {})
            .get("queued", {})
            .get("request", {})
            .get("input_type")
        )
    except Exception:
        return None


async def count_active_intake_image_tasks_for_user(
    db: AsyncSession,
    user_id: int,
    *,
    limit: int = 50,
) -> int:
    """
    Count active intake OCR image tasks for a user (best-effort; filters by stored task.result).
    """
    tasks = await list_active_tasks_for_user(db, user_id, limit=limit)
    return sum(1 for t in tasks if (_task_result_get_input_type(t) == "image"))

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
    import asyncio

    for attempt in range(6):
        try:
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
        except OperationalError as e:
            await db.rollback()
            if _is_sqlite_locked_error(e) and attempt < 5:
                await asyncio.sleep(0.15 * (2**attempt))
                continue
            raise

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
