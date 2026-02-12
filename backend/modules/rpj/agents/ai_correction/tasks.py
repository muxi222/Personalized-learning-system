"""
AI correction module: OCR exam correction / correction overlay workflows.
Moved from agents/tasks.py without logic changes.
"""

import os
import logging
from typing import List

from backend.modules.rpj.celery_app import celery_app
from backend.modules.rpj.agents.shared.celery_utils import run_async, update_task_status, mark_task_failed

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=2)
def ocr_exam_task(
    self,
    task_id: str,
    image_path: str,
    user_id: int,
    subject: str = "math",
):
    """OCR试卷批改的Celery任务"""
    logger.info(f"[Celery] Starting OCR task {task_id} for user {user_id}")

    try:
        result = run_async(_ocr_exam_async(task_id, image_path, user_id, subject))
        logger.info(f"[Celery] OCR task {task_id} completed")
        return result
    except Exception as e:
        logger.error(f"[Celery] OCR task {task_id} failed: {e}")
        run_async(mark_task_failed(task_id, str(e)))
        raise self.retry(exc=e, countdown=30)


async def _ocr_exam_async(
    task_id: str,
    image_path: str,
    user_id: int,
    subject: str,
) -> dict:
    """异步OCR批改"""
    from .ocr_agent import OCRAgent

    await update_task_status(task_id, "processing", 5.0, "ocr_starting")

    agent = OCRAgent()
    result = await agent.process(
        image_path=image_path,
        user_id=user_id,
        task_id=task_id,
        subject=subject,
    )
    return result


@celery_app.task(bind=True, max_retries=1)
def batch_ocr_task(
    self,
    task_id: str,
    image_paths: List[str],
    user_id: int,
    subject: str = "math",
):
    """批量OCR处理任务"""
    logger.info(f"[Celery] Starting batch OCR task {task_id} with {len(image_paths)} images")

    try:
        results = []
        for i, path in enumerate(image_paths):
            sub_task_id = f"{task_id}_sub_{i}"
            result = run_async(_ocr_exam_async(sub_task_id, path, user_id, subject))
            results.append(result)

            progress = ((i + 1) / len(image_paths)) * 100
            run_async(update_task_status(task_id, "processing", progress, f"processing_{i+1}/{len(image_paths)}"))

        logger.info(f"[Celery] Batch OCR task {task_id} completed")
        return {"task_id": task_id, "results": results}

    except Exception as e:
        logger.error(f"[Celery] Batch OCR task {task_id} failed: {e}")
        run_async(mark_task_failed(task_id, str(e)))
        raise self.retry(exc=e, countdown=60)


