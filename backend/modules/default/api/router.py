"""
Default Module - API Router
聚合所有API端点（跨学科查询）
"""

from fastapi import APIRouter
from .endpoints import corrections, users

api_router = APIRouter()

# 注册端点
api_router.include_router(corrections.router, prefix="/corrections", tags=["Corrections"])
api_router.include_router(users.router, prefix="/users", tags=["Users"])

# 注意：默认模块不提供OCR端点，因为OCR需要指定学科
# OCR请求应该路由到具体的学科模块（rpj, xmx, wzy, wzm, tony）
