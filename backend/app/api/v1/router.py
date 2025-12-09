"""
API Router - 路由聚合
根据设计文档6.1节
"""

from fastapi import APIRouter

from .endpoints import questions, tasks, users, feedback, guidance

# 创建主路由
api_router = APIRouter()

# 注册各模块路由
api_router.include_router(
    questions.router,
    prefix="/questions",
    tags=["Questions - 错题管理"]
)

api_router.include_router(
    guidance.router,
    prefix="/guidance",
    tags=["Guidance - 学习指导"]
)

api_router.include_router(
    tasks.router,
    prefix="/tasks",
    tags=["Tasks - 任务管理"]
)

api_router.include_router(
    users.router,
    prefix="/users",
    tags=["Users - 用户管理"]
)

api_router.include_router(
    feedback.router,
    prefix="/feedback",
    tags=["Feedback - 反馈收集"]
)


__all__ = ["api_router"]

