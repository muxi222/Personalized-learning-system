"""
XMX Agents - Economics & English Correction Tasks (Celery)

Economics/English correction module: Subject-specific exam correction workflows.
Aligned with TONY's task structure for consistency.
"""

import logging
from typing import List, Dict, Any

from backend.modules.xmx.celery_app import celery_app  # 适配XMX模块的celery_app
from backend.modules.xmx.agents.shared.celery_utils import run_async, update_task_status, mark_task_failed

# 只定义一次logger，避免重复
logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=2)
def subject_correction_task(
    self,
    task_id: str,
    image_path: str,
    user_id: int,
    subject: str = "economics",  # 默认经济板块
) -> Dict[str, Any]:
    """经济/英语试卷批改的Celery任务
    支持的subject: economics(经济) / english(英语)
    """
    # 校验科目合法性，仅允许经济和英语
    if subject not in ["economics", "english"]:
        error_msg = f"[Celery] Invalid subject {subject} for XMX task {task_id}, only economics/english are supported"
        logger.error(error_msg)
        # 正确调用异步函数mark_task_failed
        run_async(mark_task_failed(task_id, error_msg))
        raise ValueError(error_msg)

    logger.info(f"[Celery] Starting {subject} correction task {task_id} for user {user_id}")

    try:
        # 执行异步批改逻辑
        result = run_async(_subject_correction_async(task_id, image_path, user_id, subject))
        logger.info(f"[Celery] {subject} correction task {task_id} completed")
        return result
    except Exception as e:
        logger.error(f"[Celery] {subject} correction task {task_id} failed: {e}", exc_info=True)
        run_async(mark_task_failed(task_id, str(e)))
        # 重试机制：按配置重试，最终失败则抛出异常
        raise self.retry(exc=e, countdown=30)


async def _subject_correction_async(
    task_id: str,
    image_path: str,
    user_id: int,
    subject: str,
) -> dict:
    """异步批改（经济/英语专用）"""
    from .subject_agent import SubjectAgent  # 延迟导入避免循环依赖

    # 更新任务状态：开始处理
    await update_task_status(task_id, "processing", 5.0, f"{subject}_correction_starting")

    try:
        # 初始化专用Agent并处理
        agent = SubjectAgent()
        result = await agent.process(
            image_path=image_path,
            user_id=user_id,
            task_id=task_id,
            subject=subject,
        )
        # 任务完成，更新最终状态
        await update_task_status(task_id, "completed", 100.0, f"{subject}_correction_completed")
        return result
    except Exception as e:
        # 异步函数内的异常处理
        logger.error(f"[Async] {subject} correction task {task_id} failed: {e}", exc_info=True)
        await update_task_status(task_id, "failed", 100.0, f"{subject}_correction_failed: {str(e)}")
        raise


@celery_app.task(bind=True, max_retries=1)
def batch_subject_correction_task(
    self,
    task_id: str,
    image_paths: List[str],
    user_id: int,
    subject: str = "economics",
) -> Dict[str, Any]:
    """批量经济/英语试卷批改任务"""
    # 校验科目合法性
    if subject not in ["economics", "english"]:
        error_msg = f"[Celery] Invalid subject {subject} for XMX batch task {task_id}, only economics/english are supported"
        logger.error(error_msg)
        run_async(mark_task_failed(task_id, error_msg))
        raise ValueError(error_msg)

    logger.info(f"[Celery] Starting batch {subject} correction task {task_id} with {len(image_paths)} images")

    try:
        results = []
        total_images = len(image_paths)
        
        # 初始化批量任务状态
        run_async(update_task_status(task_id, "processing", 0.0, f"batch_started ({subject})"))

        for i, path in enumerate(image_paths):
            sub_task_id = f"{task_id}_sub_{i}"
            try:
                # 调用单任务处理每张图片（通过Celery子任务方式）
                sub_task_result = run_async(_subject_correction_async(sub_task_id, path, user_id, subject))
                results.append({
                    "sub_task_id": sub_task_id,
                    "image_path": path,
                    "result": sub_task_result,
                    "status": "success"
                })
            except Exception as sub_e:
                # 单个子任务失败不影响整体批量任务
                logger.error(f"[Celery] Batch sub task {sub_task_id} failed: {sub_e}", exc_info=True)
                results.append({
                    "sub_task_id": sub_task_id,
                    "image_path": path,
                    "error": str(sub_e),
                    "status": "failed"
                })

            # 计算并更新批量任务进度（正确调用异步函数）
            progress = ((i + 1) / total_images) * 100
            run_async(update_task_status(
                task_id,
                "processing",
                progress,
                f"processing_{i+1}/{total_images} ({subject})"
            ))

        # 批量任务完成，更新最终状态
        run_async(update_task_status(task_id, "completed", 100.0, f"batch_completed ({subject})"))
        logger.info(f"[Celery] Batch {subject} correction task {task_id} completed")
        
        # 正确返回结果（缩进在try块内）
        return {
            "task_id": task_id,
            "subject": subject,
            "total_images": total_images,
            "completed_images": len([r for r in results if r["status"] == "success"]),
            "failed_images": len([r for r in results if r["status"] == "failed"]),
            "results": results
        }

    except Exception as e:
        logger.error(f"[Celery] Batch {subject} correction task {task_id} failed: {e}", exc_info=True)
        run_async(mark_task_failed(task_id, str(e)))
        run_async(update_task_status(task_id, "failed", 100.0, f"batch_failed: {str(e)}"))
        raise self.retry(exc=e, countdown=60)