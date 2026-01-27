"""
Learning endpoints - Default module

- 未选择学科：由 default 模块直接基于全学科数据生成学习画像/建议/计划/总结
- 选择学科：仍然访问 default (/api/v1/learning/*?subject=xxx)，由 default 转发到对应学科子模块
"""

import logging
from typing import Optional, List

from fastapi import APIRouter, Depends, Query, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.modules.default.api.deps import get_current_user, get_db
from backend.modules.default.config import settings
from backend.core.services.learning_advisor_service import (
    get_learning_advisor_service,
    LearningGoalType,
)
from backend.core.db.models import User

logger = logging.getLogger(__name__)
router = APIRouter()

# 学科到模块映射（与前端 moduleRouting 保持一致）
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

MODULE_PORTS = {
    "rpj": 6001,
    "xmx": 6002,
    "wzy": 6003,
    "wzm": 6004,
    "tony": 6005,
}


async def _proxy_learning_get(
    *,
    request: Request,
    module: str,
    path: str,
    params: dict,
) -> dict:
    import httpx

    port = MODULE_PORTS.get(module)
    if not port:
        raise HTTPException(status_code=502, detail=f"Unknown module port for '{module}'")

    url = f"http://127.0.0.1:{port}/api/v1/learning{path}"
    headers = {}
    auth = request.headers.get("authorization")
    if auth:
        headers["authorization"] = auth

    try:
        # Localhost intra-service call; do not route through env proxies.
        async with httpx.AsyncClient(timeout=20.0, trust_env=False) as client:
            resp = await client.get(url, params=params, headers=headers)
    except Exception as e:
        logger.error(f"[DEFAULT] proxy learning failed: module={module}, url={url}, err={e}")
        raise HTTPException(status_code=502, detail=f"Failed to proxy learning to module '{module}'")

    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    try:
        return resp.json()
    except Exception:
        raise HTTPException(status_code=502, detail=f"Invalid response from module '{module}'")


# ============ Response Models (与 tony 模块保持一致) ============

class WeakPointResponse(BaseModel):
    knowledge_point: str
    subject: str
    error_count: int
    error_rate: float
    recent_trend: str
    suggested_actions: List[str]


class LearningProfileResponse(BaseModel):
    user_id: int
    total_questions: int
    correct_count: int
    overall_accuracy: float
    subject_stats: dict
    weak_points: List[WeakPointResponse]
    strong_points: List[str]
    learning_style: str
    optimal_study_time: str
    streak_days: int


class RecommendationResponse(BaseModel):
    title: str
    description: str
    priority: str
    subject: str
    knowledge_points: List[str]
    estimated_time_minutes: int
    resources: List[dict]
    related_question_ids: List[int]


class StudyPlanResponse(BaseModel):
    user_id: int
    goal_type: str
    start_date: str
    end_date: str
    daily_tasks: List[dict]
    total_estimated_hours: float
    progress_percentage: float


class LearningSummaryResponse(BaseModel):
    period: str
    total_questions: int
    correct_rate: str
    subject_performance: dict
    top_weak_points: List[dict]
    strong_points: List[str]
    streak_days: int
    ai_comment: str


def _validate_subject(subject: str) -> None:
    if subject not in settings.SUBJECTS:
        raise HTTPException(
            status_code=400,
            detail=f"Subject '{subject}' is not supported. Supported subjects: {settings.SUBJECTS}",
        )


@router.get("/profile", response_model=LearningProfileResponse)
async def get_learning_profile(
    request: Request,
    subject: Optional[str] = Query(None, description="学科筛选（可选）"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if subject == "":
        subject = None

    # 选择学科：转发到对应子模块
    if subject:
        _validate_subject(subject)
        module = SUBJECT_TO_MODULE.get(subject)
        if module:
            return await _proxy_learning_get(
                request=request,
                module=module,
                path="/profile",
                params={"subject": subject},
            )

    # 未选择学科：default 直接全学科分析
    service = get_learning_advisor_service()
    await service.initialize()
    profile = await service.analyze_user_profile(current_user.id)

    return LearningProfileResponse(
        user_id=profile.user_id,
        total_questions=profile.total_questions,
        correct_count=profile.correct_count,
        overall_accuracy=profile.overall_accuracy,
        subject_stats=profile.subject_stats,
        weak_points=[
            WeakPointResponse(
                knowledge_point=wp.knowledge_point,
                subject=wp.subject,
                error_count=wp.error_count,
                error_rate=wp.error_rate,
                recent_trend=wp.recent_trend,
                suggested_actions=wp.suggested_actions,
            )
            for wp in profile.weak_points
        ],
        strong_points=profile.strong_points,
        learning_style=profile.learning_style,
        optimal_study_time=profile.optimal_study_time,
        streak_days=profile.streak_days,
    )


@router.get("/recommendations", response_model=List[RecommendationResponse])
async def get_recommendations(
    request: Request,
    goal: str = Query("improve_weak_points", description="学习目标类型"),
    limit: int = Query(5, ge=1, le=20, description="推荐数量"),
    subject: Optional[str] = Query(None, description="学科筛选（可选）"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if subject == "":
        subject = None

    if subject:
        _validate_subject(subject)
        module = SUBJECT_TO_MODULE.get(subject)
        if module:
            return await _proxy_learning_get(
                request=request,
                module=module,
                path="/recommendations",
                params={"goal": goal, "limit": limit, "subject": subject},
            )

    try:
        goal_type = LearningGoalType(goal)
    except ValueError:
        goal_type = LearningGoalType.IMPROVE_WEAK_POINTS

    service = get_learning_advisor_service()
    await service.initialize()
    recs = await service.generate_recommendations(
        user_id=current_user.id,
        goal_type=goal_type,
        max_recommendations=limit,
    )

    return [
        RecommendationResponse(
            title=r.title,
            description=r.description,
            priority=r.priority.value,
            subject=r.subject,
            knowledge_points=r.knowledge_points,
            estimated_time_minutes=r.estimated_time_minutes,
            resources=r.resources,
            related_question_ids=r.related_question_ids,
        )
        for r in recs
    ]


@router.get("/study-plan", response_model=StudyPlanResponse)
async def get_study_plan(
    request: Request,
    goal: str = Query("improve_weak_points", description="学习目标"),
    days: int = Query(7, ge=1, le=30, description="计划天数"),
    subject: Optional[str] = Query(None, description="学科筛选（可选）"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if subject == "":
        subject = None

    if subject:
        _validate_subject(subject)
        module = SUBJECT_TO_MODULE.get(subject)
        if module:
            return await _proxy_learning_get(
                request=request,
                module=module,
                path="/study-plan",
                params={"goal": goal, "days": days, "subject": subject},
            )

    try:
        goal_type = LearningGoalType(goal)
    except ValueError:
        goal_type = LearningGoalType.IMPROVE_WEAK_POINTS

    service = get_learning_advisor_service()
    await service.initialize()
    plan = await service.generate_study_plan(
        user_id=current_user.id,
        goal_type=goal_type,
        duration_days=days,
    )

    return StudyPlanResponse(
        user_id=plan.user_id,
        goal_type=plan.goal_type.value,
        start_date=plan.start_date.isoformat(),
        end_date=plan.end_date.isoformat(),
        daily_tasks=plan.daily_tasks,
        total_estimated_hours=plan.total_estimated_hours,
        progress_percentage=plan.progress_percentage,
    )


@router.get("/summary", response_model=LearningSummaryResponse)
async def get_learning_summary(
    request: Request,
    days: int = Query(7, ge=1, le=90, description="统计天数"),
    subject: Optional[str] = Query(None, description="学科筛选（可选）"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if subject == "":
        subject = None

    if subject:
        _validate_subject(subject)
        module = SUBJECT_TO_MODULE.get(subject)
        if module:
            return await _proxy_learning_get(
                request=request,
                module=module,
                path="/summary",
                params={"days": days, "subject": subject},
            )

    service = get_learning_advisor_service()
    await service.initialize()
    summary = await service.generate_learning_summary(
        user_id=current_user.id,
        period_days=days,
    )

    return LearningSummaryResponse(
        period=summary["period"],
        total_questions=summary["total_questions"],
        correct_rate=summary["correct_rate"],
        subject_performance=summary["subject_performance"],
        top_weak_points=summary["top_weak_points"],
        strong_points=summary["strong_points"],
        streak_days=summary["streak_days"],
        ai_comment=summary["ai_comment"],
    )


