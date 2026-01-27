"""
Feedback stats - Default module

当未选择学科时，前端会路由到 default 模块(6100)，由该接口汇总所有学科的反馈统计。
当携带 subject 时，也可按学科筛选统计（可选）。
"""

import logging
from typing import Optional, List

from fastapi import APIRouter, Depends, Query, HTTPException, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.db.session import get_db
from backend.core.db.models import Feedback, Question, SubjectEnum
from backend.core.schemas.feedback import FeedbackStats
from backend.modules.default.api.deps import get_current_user_id
from backend.modules.default.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

# 学科到模块的映射（与前端 moduleRouting 保持一致）
SUBJECT_TO_MODULE = {
    "chinese": "rpj",
    "english": "rpj",
    "politics": "rpj",
    "economics": "xmx",
    "math": "wzy",
    "physics": "wzy",
    "chemistry": "wzm",
    "history": "tony",
    "geography": "tony",
    "other": "tony",
}

# 模块端口（开发/本机环境默认）
MODULE_PORTS = {
    "rpj": 6001,
    "xmx": 6002,
    "wzy": 6003,
    "wzm": 6004,
    "tony": 6005,
}


async def _proxy_stats_to_module(module: str, subject: str, request: Request) -> dict:
    """
    将 /api/v1/feedback/stats?subject=xxx 转发到对应子模块的 /api/v1/feedback/stats?subject=xxx
    """
    import httpx

    port = MODULE_PORTS.get(module)
    if not port:
        raise HTTPException(status_code=502, detail=f"Unknown module port for '{module}'")

    url = f"http://127.0.0.1:{port}/api/v1/feedback/stats"
    headers = {}
    auth = request.headers.get("authorization")
    if auth:
        headers["authorization"] = auth

    try:
        # Localhost intra-service call; do not route through env proxies.
        async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
            resp = await client.get(url, params={"subject": subject}, headers=headers)
    except Exception as e:
        logger.error(f"[DEFAULT] proxy feedback stats failed: module={module}, subject={subject}, err={e}")
        raise HTTPException(status_code=502, detail=f"Failed to proxy stats to module '{module}'")

    if resp.status_code >= 400:
        # 透传错误（学生模块可能返回 501 TODO）
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

    try:
        return resp.json()
    except Exception:
        raise HTTPException(status_code=502, detail=f"Invalid response from module '{module}'")


@router.get("/stats", response_model=FeedbackStats)
async def get_feedback_stats(
    request: Request,
    subject: Optional[str] = Query(None, description="学科筛选（可选）"),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    获取反馈统计（跨学科）
    - 不传 subject：统计当前用户所有学科
    - 传 subject：仅统计该学科
    """

    if subject == "":
        subject = None

    # 选择学科时：仍然访问 default，由 default 转发到各学科子模块
    if subject:
        module = SUBJECT_TO_MODULE.get(subject)
        if module and module != "default":
            return await _proxy_stats_to_module(module=module, subject=subject, request=request)

    subject_enums: Optional[List[SubjectEnum]] = None
    if subject:
        if subject not in settings.SUBJECTS:
            raise HTTPException(status_code=400, detail=f"Subject '{subject}' is not supported. Supported subjects: {settings.SUBJECTS}")
        subject_enums = [SubjectEnum(subject)]

    # 统计 feedback 相关：若有 subject 筛选，需要 join 到 Question 才能过滤
    if subject_enums:
        base_feedback_where = (
            (Feedback.user_id == user_id)
            & (Question.user_id == user_id)
            & (Question.subject.in_(subject_enums))
        )
        total_stmt = select(func.count(Feedback.id)).select_from(Feedback).join(Question, Feedback.question_id == Question.id).where(base_feedback_where)
        helpful_stmt = select(func.count(Feedback.id)).select_from(Feedback).join(Question, Feedback.question_id == Question.id).where(base_feedback_where & (Feedback.feedback_type == "helpful"))
        not_helpful_stmt = select(func.count(Feedback.id)).select_from(Feedback).join(Question, Feedback.question_id == Question.id).where(base_feedback_where & (Feedback.feedback_type == "not_helpful"))
        avg_stmt = select(func.avg(Feedback.rating)).select_from(Feedback).join(Question, Feedback.question_id == Question.id).where(base_feedback_where & (Feedback.rating.isnot(None)))
        with_feedback_stmt = select(func.count(func.distinct(Feedback.question_id))).select_from(Feedback).join(Question, Feedback.question_id == Question.id).where(base_feedback_where)
        total_questions_stmt = select(func.count(Question.id)).where(Question.user_id == user_id, Question.subject.in_(subject_enums))
    else:
        total_stmt = select(func.count(Feedback.id)).where(Feedback.user_id == user_id)
        helpful_stmt = select(func.count(Feedback.id)).where(Feedback.user_id == user_id, Feedback.feedback_type == "helpful")
        not_helpful_stmt = select(func.count(Feedback.id)).where(Feedback.user_id == user_id, Feedback.feedback_type == "not_helpful")
        avg_stmt = select(func.avg(Feedback.rating)).where(Feedback.user_id == user_id, Feedback.rating.isnot(None))
        with_feedback_stmt = select(func.count(func.distinct(Feedback.question_id))).where(Feedback.user_id == user_id)
        total_questions_stmt = select(func.count(Question.id)).where(Question.user_id == user_id)

    total_feedbacks = (await db.execute(total_stmt)).scalar() or 0
    helpful_count = (await db.execute(helpful_stmt)).scalar() or 0
    not_helpful_count = (await db.execute(not_helpful_stmt)).scalar() or 0
    average_rating = (await db.execute(avg_stmt)).scalar()
    questions_with_feedback = (await db.execute(with_feedback_stmt)).scalar() or 0
    total_questions = (await db.execute(total_questions_stmt)).scalar() or 0

    feedback_rate = questions_with_feedback / total_questions if total_questions > 0 else 0.0

    return FeedbackStats(
        total_feedbacks=total_feedbacks,
        helpful_count=helpful_count,
        not_helpful_count=not_helpful_count,
        average_rating=float(average_rating) if average_rating is not None else None,
        feedback_rate=feedback_rate,
    )


