"""
学习建议API (WZM模块 - 学生实现版本)

本文件为框架代码，需要学生完成核心业务逻辑的实现。
完整实现请参考: backend/modules/tony/api/endpoints/learning.py

WZM模块支持的学科: chemistry
"""

import logging
from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.modules.wzm.api.deps import get_current_user, get_db
from backend.core.services.learning_advisor_service import (
    get_learning_advisor_service,
    LearningGoalType,
    PriorityLevel,
)
from backend.core.db.models import User

logger = logging.getLogger(__name__)

router = APIRouter()

def validate_subject(subject: str) -> None:
    """验证学科是否属于WZM模块"""
    if subject not in settings.SUBJECTS:
        raise HTTPException(
            status_code=400,
            detail=f"Subject '{subject}' is not supported by WZM module. "
                   f"Supported subjects: {settings.SUBJECTS}"
        )

# ============ Response Models ============

class WeakPointResponse(BaseModel):
    """薄弱点响应"""
    knowledge_point: str
    subject: str
    error_count: int
    error_rate: float
    recent_trend: str
    suggested_actions: List[str]

class LearningProfileResponse(BaseModel):
    """学习画像响应"""
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
    """学习推荐响应"""
    title: str
    description: str
    priority: str
    subject: str
    knowledge_points: List[str]
    estimated_time_minutes: int
    resources: List[dict]
    related_question_ids: List[int]

class StudyPlanResponse(BaseModel):
    """学习计划响应"""
    user_id: int
    goal_type: str
    start_date: str
    end_date: str
    daily_tasks: List[dict]
    total_estimated_hours: float
    progress_percentage: float

class SimilarQuestionResponse(BaseModel):
    """相似题目响应"""
    question_id: str
    content: str
    similarity_score: float
    source: str
    metadata: dict

class LearningSummaryResponse(BaseModel):
    """学习总结响应"""
    period: str
    total_questions: int
    correct_rate: str
    subject_performance: dict
    top_weak_points: List[dict]
    strong_points: List[str]
    streak_days: int
    ai_comment: str

# ============ API Endpoints ============

@router.get("/profile", response_model=LearningProfileResponse)
async def get_learning_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    获取用户学习画像

    包含:
    - 总体学习统计
    - 各学科表现
    - 薄弱知识点
    - 学习风格分析
    """
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
    goal: str = Query("improve_weak_points", description="学习目标类型"),
    limit: int = Query(5, ge=1, le=20, description="推荐数量"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    获取个性化学习建议

    目标类型:
    - improve_weak_points: 强化薄弱点
    - prepare_exam: 备考复习
    - daily_practice: 每日练习
    - review_mistakes: 错题复习
    - expand_knowledge: 知识拓展
    """
    try:
        goal_type = LearningGoalType(goal)
    except ValueError:
        goal_type = LearningGoalType.IMPROVE_WEAK_POINTS

    service = get_learning_advisor_service()
    await service.initialize()

    recommendations = await service.generate_recommendations(
        user_id=current_user.id,
        goal_type=goal_type,
        max_recommendations=limit,
    )

    return [
        RecommendationResponse(
            title=rec.title,
            description=rec.description,
            priority=rec.priority.value,
            subject=rec.subject,
            knowledge_points=rec.knowledge_points,
            estimated_time_minutes=rec.estimated_time_minutes,
            resources=rec.resources,
            related_question_ids=rec.related_question_ids,
        )
        for rec in recommendations
    ]

@router.get("/study-plan", response_model=StudyPlanResponse)
async def get_study_plan(
    goal: str = Query("improve_weak_points", description="学习目标"),
    days: int = Query(7, ge=1, le=30, description="计划天数"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    生成个性化学习计划

    根据用户的学习画像和目标，生成每日学习任务
    """
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

@router.get("/similar-questions/{question_id}", response_model=List[SimilarQuestionResponse])
async def get_similar_questions(
    question_id: int,
    limit: int = Query(5, ge=1, le=20, description="推荐数量"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    获取相似题目推荐（举一反三）

    使用 FAISS + BM25 混合检索找到相似的题目
    """
    service = get_learning_advisor_service()
    await service.initialize()

    similar = await service.get_similar_questions(
        user_id=current_user.id,
        question_id=question_id,
        top_k=limit,
    )

    return [
        SimilarQuestionResponse(
            question_id=q["question_id"],
            content=q["content"],
            similarity_score=q["similarity_score"],
            source=q["source"],
            metadata=q["metadata"],
        )
        for q in similar
    ]

@router.get("/summary", response_model=LearningSummaryResponse)
async def get_learning_summary(
    days: int = Query(7, ge=1, le=90, description="统计天数"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    获取学习总结报告

    包含:
    - 学习统计
    - 进步分析
    - AI 个性化点评
    """
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

@router.post("/feedback")
async def submit_learning_feedback(
    recommendation_id: Optional[str] = None,
    helpful: bool = True,
    comment: Optional[str] = None,
    current_user: User = Depends(get_current_user),
):
    """
    提交学习建议反馈

    用于改进推荐算法
    """
    # 记录反馈用于后续优化
    logger.info(
        f"User {current_user.id} feedback: "
        f"recommendation={recommendation_id}, helpful={helpful}, comment={comment}"
    )

    return {
        "success": True,
        "message": "感谢你的反馈！我们会不断改进。",
    }
