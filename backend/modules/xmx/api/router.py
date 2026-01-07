"""
XMX Module - API Router
聚合所有API端点
"""

from fastapi import APIRouter
from .endpoints.intake import questions as intake_questions
from .endpoints.ai_correction import ocr as ai_correction_ocr
from .endpoints.ai_correction import corrections as ai_correction_corrections
from .endpoints.learning import learning as learning_learning
from .endpoints.learning import guidance as learning_guidance
from .endpoints.review import review as review_review
from .endpoints.shared import image_files as shared_image_files
from .endpoints.shared import users as shared_users
from .endpoints.shared import tasks as shared_tasks
from .endpoints.shared import feedback as shared_feedback
from .endpoints.stats import feedback as feedback_stats

api_router = APIRouter()

# 注册所有端点(与原系统相同结构)
api_router.include_router(intake_questions.router, prefix="/questions", tags=["Questions"])
api_router.include_router(ai_correction_ocr.router, prefix="/ocr", tags=["OCR"])
api_router.include_router(ai_correction_corrections.router, prefix="/corrections", tags=["Corrections"])
api_router.include_router(learning_learning.router, prefix="/learning", tags=["Learning"])
api_router.include_router(learning_guidance.router, prefix="/guidance", tags=["Guidance"])
# Review endpoints are still mounted under /questions/... for backward compatibility
api_router.include_router(review_review.router, prefix="/questions", tags=["Review"])
api_router.include_router(shared_image_files.router, prefix="/image-files", tags=["Image Files"])
api_router.include_router(shared_users.router, prefix="/users", tags=["Users"])
api_router.include_router(shared_tasks.router, prefix="/tasks", tags=["Tasks"])
api_router.include_router(shared_feedback.router, prefix="/feedback", tags=["Feedback"])
api_router.include_router(feedback_stats.router, prefix="/feedback", tags=["Feedback"])
