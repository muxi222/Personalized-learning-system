"""
学习指导API (XMX模块 - 学生实现版本)

本文件为框架代码，需要学生完成核心业务逻辑的实现。
完整实现请参考: backend/modules/tony/api/endpoints/guidance.py

XMX模块支持的学科: economics
"""

import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.db.session import get_db
from backend.modules.xmx.api.deps import get_current_user_id
from backend.modules.xmx.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()

def validate_subject(subject: str) -> None:
    """验证学科是否属于XMX模块"""
    if subject not in settings.SUBJECTS:
        raise HTTPException(
            status_code=400,
            detail=f"Subject '{subject}' is not supported by XMX module. "
                   f"Supported subjects: {settings.SUBJECTS}"
        )

# ============================================================
# TODO: 学生需要实现以下API endpoints
# ============================================================
#
# 请参考完整实现: backend/modules/tony/api/endpoints/guidance.py
#
# 实现步骤:
# 1. 复制TONY模块对应文件的函数签名和路由装饰器
# 2. 保留学科验证逻辑 (validate_subject)
# 3. 实现业务逻辑（数据库查询、Agent调用等）
# 4. 返回正确的响应数据
#
# 提示:
# - 所有数据库操作使用 backend/core/crud/ 中的函数
# - 所有Agent操作使用 backend/modules/xmx/agents/ 中的类
# - 所有Schema使用 backend/core/schemas/ 中的定义
# ============================================================

# TODO: 在这里添加endpoint实现
# 示例:
# @router.get("/example")
# async def example_endpoint():
#     """示例端点"""
#     return {"message": "学生TODO: 实现此endpoint"}
