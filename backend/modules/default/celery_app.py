"""
Default Module - Celery Application
处理跨学科异步任务
"""

from celery import Celery
from .config import settings

celery_app = Celery(
    f"learning_assistant_{settings.MODULE_NAME}",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        f"backend.modules.{settings.MODULE_NAME}.agents.tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_default_queue=settings.module_celery_queue,
    task_routes={
        f"backend.modules.{settings.MODULE_NAME}.agents.tasks.*": {
            "queue": settings.module_celery_queue
        },
    },
    result_expires=3600,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
)

celery_app.conf.worker_send_task_events = True
celery_app.conf.task_send_sent_event = True
