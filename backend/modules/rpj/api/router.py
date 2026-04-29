"""
TONY Module - API Router
聚合所有API端点
"""

from fastapi import APIRouter
from .endpoints.intake import questions
from .endpoints.ai_correction import ocr, corrections
from .endpoints.learning import learning, guidance
from .endpoints.companion import chat as companion_chat
from .endpoints.review import review
from .endpoints.shared import image_files, users, tasks, feedback
from .endpoints.stats import feedback as feedback_stats

api_router = APIRouter()

# 注册所有端点(与原系统相同结构)
api_router.include_router(questions.router, prefix="/questions", tags=["Questions"])
api_router.include_router(ocr.router, prefix="/ocr", tags=["OCR"])
api_router.include_router(corrections.router, prefix="/corrections", tags=["Corrections"])
api_router.include_router(learning.router, prefix="/learning", tags=["Learning"])
api_router.include_router(guidance.router, prefix="/guidance", tags=["Guidance"])
api_router.include_router(companion_chat.router, prefix="/companion", tags=["Companion"])
# Review endpoints are still mounted under /questions/... for backward compatibility
api_router.include_router(review.router, prefix="/questions", tags=["Review"])
api_router.include_router(image_files.router, prefix="/image-files", tags=["Image Files"])
api_router.include_router(users.router, prefix="/users", tags=["Users"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["Tasks"])
api_router.include_router(feedback.router, prefix="/feedback", tags=["Feedback"])
api_router.include_router(feedback_stats.router, prefix="/feedback", tags=["Feedback"])
