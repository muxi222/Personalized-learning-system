"""
Default Module - API Router
聚合所有API端点（跨学科查询）
"""

from fastapi import APIRouter
from .endpoints import corrections, users, questions, ocr, learning, image_files, companion
from .endpoints.stats import feedback as feedback_stats

api_router = APIRouter()

# 注册端点
api_router.include_router(corrections.router, prefix="/corrections", tags=["Corrections"])
api_router.include_router(users.router, prefix="/users", tags=["Users"])
api_router.include_router(questions.router, prefix="/questions", tags=["Questions"])
# 注册图片访问端点（统一由 default 模块处理）
api_router.include_router(ocr.router, prefix="/ocr", tags=["OCR"])
api_router.include_router(image_files.router, tags=["Image Files"])
# 学习建议（跨学科 + 可按学科转发）
api_router.include_router(learning.router, prefix="/learning", tags=["Learning"])
# 小书童（跨学科入口；Tony-first，按学科转发）
api_router.include_router(companion.router, prefix="/companion", tags=["Companion"])
# 反馈统计（跨学科）
api_router.include_router(feedback_stats.router, prefix="/feedback", tags=["Feedback"])

# 注意：默认模块不提供OCR分析端点，因为OCR分析需要指定学科
# OCR分析请求应该路由到具体的学科模块（rpj, xmx, wzy, wzm, tony）
# 但图片访问接口统一由 default 模块处理
