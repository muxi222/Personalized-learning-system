"""
Celery Configuration for Background Tasks

异步任务队列配置
支持:
- 错题录入处理
- 相似题目检索
- OCR 试卷批改
- 学习建议生成
"""

from celery import Celery
from .config import settings

celery_app = Celery(
    "learning_assistant",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "backend.app.agents.tasks",  # Agent 任务模块
    ],
)

# Celery configuration
celery_app.conf.update(
    # 序列化
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",

    # 时区
    timezone="Asia/Shanghai",
    enable_utc=True,

    # 任务追踪
    task_track_started=True,
    task_acks_late=True,  # 确保任务完成后才确认

    # 超时设置
    task_time_limit=600,  # 10 minutes (OCR 可能较慢)
    task_soft_time_limit=540,  # 9 minutes

    # Worker 配置
    worker_prefetch_multiplier=1,  # 每个 worker 一次只取一个任务
    worker_concurrency=4,

    # 结果过期
    result_expires=3600,  # 1 hour

    # 任务路由 (可用于分配不同类型任务到不同队列)
    task_routes={
        "backend.app.agents.tasks.ocr_*": {"queue": "ocr"},
        "backend.app.agents.tasks.batch_*": {"queue": "batch"},
        "backend.app.agents.tasks.*": {"queue": "default"},
    },

    # 重试配置
    task_default_retry_delay=60,
    task_max_retries=3,
)

