"""
TONY Module - Celery Application
处理异步任务(Agent处理等)
"""

from celery import Celery
from .config import settings

# 创建Celery应用实例
celery_app = Celery(
    f"learning_assistant_{settings.MODULE_NAME}",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        f"backend.modules.{settings.MODULE_NAME}.agents.tasks",
    ],
)

# Celery配置
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,

    # 使用模块独立队列
    task_default_queue=settings.module_celery_queue,

    # 任务路由配置
    task_routes={
        f"backend.modules.{settings.MODULE_NAME}.agents.tasks.*": {
            "queue": settings.module_celery_queue
        },
    },

    # 任务结果过期时间
    result_expires=3600,

    # 任务执行配置
    task_acks_late=True,
    task_reject_on_worker_lost=True,

    # Worker配置
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
)

# Worker启动时的banner
celery_app.conf.worker_send_task_events = True
celery_app.conf.task_send_sent_event = True
