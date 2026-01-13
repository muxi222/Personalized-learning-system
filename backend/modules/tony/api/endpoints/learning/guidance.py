"""
Learning Guidance API Endpoints
学习指导相关API (根据设计文档6.1节)
"""

import logging
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field

from backend.core.db.session import get_db
from backend.core.crud import crud_question
from backend.modules.tony.api.deps import get_current_user_id

logger = logging.getLogger(__name__)

router = APIRouter()

# ============ Schemas ============

class SimilarQuestionRequest(BaseModel):
    """举一反三请求"""
    question_id: int = Field(..., description="原题ID")
    top_k: int = Field(5, ge=1, le=20, description="返回数量")

class SimilarQuestionItem(BaseModel):
    """相似题目项"""
    id: int
    content: str
    subject: str
    difficulty: str
    correct_answer: Optional[str] = None
    knowledge_points: List[str] = []
    similarity_score: Optional[float] = None

class SimilarQuestionResponse(BaseModel):
    """举一反三响应"""
    question_id: int
    guidance_text: str = Field(..., description="引导文本")
    similar_questions: List[SimilarQuestionItem] = []

class SimilarQuestionAcceptRequest(BaseModel):
    """用户对推荐题目的接受/点击等行为"""
    recommended_question_id: int = Field(..., description="被接受/点击的推荐题目ID")
    action: str = Field("open", description="行为类型，如 open/answer/like")

class LearningPlanRequest(BaseModel):
    """学习计划请求"""
    learning_goal: Optional[str] = Field(None, description="学习目标")
    focus_subjects: List[str] = Field(default_factory=list, description="重点学科")
    days: int = Field(7, ge=1, le=30, description="计划天数")

class LearningPlanResponse(BaseModel):
    """学习计划响应"""
    plan_text: str
    weak_knowledge_points: List[str] = []
    recommended_review_questions: List[int] = []

class StudentProfileResponse(BaseModel):
    """学生画像响应"""
    user_id: int
    grade: Optional[str] = None
    total_questions: int = 0
    weak_subjects: List[str] = []
    weak_knowledge_points: List[str] = []
    recent_errors_summary: Optional[str] = None
    mastery_overview: dict = {}

# ============ Endpoints ============

@router.post("/similar-questions", response_model=SimilarQuestionResponse)
async def get_similar_questions(
    request: SimilarQuestionRequest,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    举一反三 - 获取相似题目

    基于RAG技术，根据原题向量检索相似题目，
    并使用LLM生成引导文本。

    对应设计文档4.2节
    """
    from backend.modules.tony.agents.learning.similar_question_agent import SimilarQuestionAgent

    # 验证原题存在
    question = await crud_question.get_question(db, request.question_id, user_id)
    if not question:
        raise HTTPException(status_code=404, detail="题目不存在")

    # 获取学生画像 (用于个性化)
    student_profile = await _get_student_profile(db, user_id)

    # 调用举一反三Agent
    agent = SimilarQuestionAgent()
    result = await agent.find_similar(
        question_id=request.question_id,
        user_id=user_id,
        top_k=request.top_k,
        student_profile=student_profile,
    )

    if result.get("errors"):
        logger.warning(f"Similar question agent errors: {result['errors']}")

    # 格式化响应
    similar_questions = []
    for q in result.get("similar_questions", []):
        similar_questions.append(SimilarQuestionItem(
            id=q.get("id"),
            content=q.get("content", ""),
            subject=q.get("subject", ""),
            difficulty=q.get("difficulty", "medium"),
            correct_answer=q.get("correct_answer"),
            knowledge_points=q.get("knowledge_points", []),
        ))

    # Telemetry: recommendation shown (for acceptance rate / retrieval usefulness)
    try:
        from backend.core.services.metrics_service import get_metrics_service
        await get_metrics_service().log_event(
            event_type="reco",
            event_name="similar_questions.shown",
            ok=True,
            user_id=user_id,
            module="tony",
            subject=(question.subject.value if getattr(question, "subject", None) else None),
            question_id=request.question_id,
            payload={
                "top_k": request.top_k,
                "recommended_ids": [q.id for q in similar_questions],
            },
        )
    except Exception:
        pass

    return SimilarQuestionResponse(
        question_id=request.question_id,
        guidance_text=result.get("guidance_text", ""),
        similar_questions=similar_questions,
    )


@router.post("/similar-questions/{question_id}/accept")
async def accept_similar_question(
    question_id: int,
    body: SimilarQuestionAcceptRequest,
    user_id: int = Depends(get_current_user_id),
):
    """
    记录用户对“举一反三”推荐题的接受/点击行为（用于评估：推荐题接受率）。

    前端可在用户点击某道推荐题、或查看答案/开始练习时调用此接口。
    """
    try:
        from backend.core.services.metrics_service import get_metrics_service
        await get_metrics_service().log_event(
            event_type="reco",
            event_name="similar_questions.accept",
            ok=True,
            user_id=user_id,
            module="tony",
            question_id=question_id,
            payload={
                "recommended_question_id": int(body.recommended_question_id),
                "action": body.action,
            },
        )
    except Exception:
        pass
    return {"success": True}

@router.get("/learning-plan", response_model=LearningPlanResponse)
async def get_learning_plan(
    learning_goal: Optional[str] = Query(None, description="学习目标"),
    days: int = Query(7, ge=1, le=30, description="计划天数"),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    获取个性化学习计划

    根据学生的错题历史和薄弱知识点，
    动态生成学习计划。

    对应设计文档7.3节 - 长期记忆与个性化
    """
    from backend.core.services.llm_service import get_llm_service
    from backend.modules.tony.agents.prompts import LEARNING_PLAN_PROMPT

    # 获取学生画像
    profile = await _get_student_profile(db, user_id)

    # 获取待复习题目
    review_questions = await crud_question.get_questions_for_review(db, user_id, limit=10)
    recommended_ids = [q.id for q in review_questions]

    # Optional GraphRAG-based expansion: fetch more practice questions by weak knowledge points.
    try:
        from backend.modules.tony.config import settings
        if getattr(settings, "GRAPHRAG_ENABLED", False):
            from backend.core.services.graphrag_service import get_graphrag_service
            graphrag = get_graphrag_service()
            await graphrag.initialize(graph_path=settings.module_graphrag_graph_path)
            extra = graphrag.find_questions_by_knowledge_points(
                subject=(profile.get("weak_subjects") or ["other"])[0],
                knowledge_points=profile.get("weak_knowledge_points", []),
                top_k=20,
                exclude_question_ids=set(recommended_ids),
            )
            recommended_ids.extend(extra)
    except Exception as _e:
        logger.debug(f"GraphRAG expansion skipped in learning-plan: {_e}")

    # 生成学习计划
    llm = get_llm_service()

    prompt = LEARNING_PLAN_PROMPT.format(
        grade=profile.get("grade", "未知"),
        weak_subjects=", ".join(profile.get("weak_subjects", [])) or "暂无",
        weak_knowledge_points=", ".join(profile.get("weak_knowledge_points", [])) or "暂无",
        recent_errors_summary=profile.get("recent_errors_summary", "暂无"),
        learning_goal=learning_goal or "提高整体学习成绩",
    )

    plan_text = await llm.generate(
        prompt=prompt,
        system_prompt="你是学习小书童，一位贴心的学习规划师。",
        temperature=0.7,
        max_tokens=2000,
    )

    return LearningPlanResponse(
        plan_text=plan_text or "暂时无法生成学习计划，请稍后再试。",
        weak_knowledge_points=profile.get("weak_knowledge_points", []),
        recommended_review_questions=recommended_ids,
    )

@router.get("/student-profile", response_model=StudentProfileResponse)
async def get_student_profile_api(
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    获取学生画像

    返回学生的学习统计、薄弱点分析等信息。
    用于个性化推荐和学习规划。

    对应设计文档7.3节
    """
    profile = await _get_student_profile(db, user_id)

    return StudentProfileResponse(
        user_id=user_id,
        grade=profile.get("grade"),
        total_questions=profile.get("total_questions", 0),
        weak_subjects=profile.get("weak_subjects", []),
        weak_knowledge_points=profile.get("weak_knowledge_points", []),
        recent_errors_summary=profile.get("recent_errors_summary"),
        mastery_overview=profile.get("mastery_overview", {}),
    )

# ============ Helper Functions ============

async def _get_student_profile(db: AsyncSession, user_id: int) -> dict:
    """
    获取学生画像
    根据设计文档7.3节 - 长期记忆与个性化演进
    """
    from sqlalchemy import select, func
    from backend.core.db.models import Question, User

    profile = {
        "user_id": user_id,
        "grade": None,
        "total_questions": 0,
        "weak_subjects": [],
        "weak_knowledge_points": [],
        "recent_errors_summary": None,
        "mastery_overview": {},
    }

    try:
        # 获取用户信息
        user_result = await db.execute(
            select(User).where(User.id == user_id)
        )
        user = user_result.scalar_one_or_none()
        if user:
            profile["grade"] = user.grade

        # 统计错题数量
        count_result = await db.execute(
            select(func.count(Question.id)).where(Question.user_id == user_id)
        )
        profile["total_questions"] = count_result.scalar() or 0

        # 分析薄弱学科 (按错题数量)
        subject_result = await db.execute(
            select(Question.subject, func.count(Question.id).label("count"))
            .where(Question.user_id == user_id)
            .group_by(Question.subject)
            .order_by(func.count(Question.id).desc())
            .limit(3)
        )
        weak_subjects = [row[0].value if row[0] else "other" for row in subject_result.fetchall()]
        profile["weak_subjects"] = weak_subjects

        # 分析薄弱知识点 (统计所有knowledge_points)
        questions_result = await db.execute(
            select(Question.knowledge_points)
            .where(Question.user_id == user_id)
            .where(Question.knowledge_points.isnot(None))
            .order_by(Question.created_at.desc())
            .limit(50)
        )

        kp_count = {}
        for row in questions_result.fetchall():
            if row[0]:
                for kp in row[0]:
                    kp_count[kp] = kp_count.get(kp, 0) + 1

        # 取出现最多的知识点作为薄弱点
        sorted_kps = sorted(kp_count.items(), key=lambda x: x[1], reverse=True)
        profile["weak_knowledge_points"] = [kp for kp, _ in sorted_kps[:5]]

        # 计算各学科掌握度
        mastery_result = await db.execute(
            select(
                Question.subject,
                func.avg(Question.mastery_level).label("avg_mastery")
            )
            .where(Question.user_id == user_id)
            .group_by(Question.subject)
        )
        for row in mastery_result.fetchall():
            subject = row[0].value if row[0] else "other"
            profile["mastery_overview"][subject] = round(float(row[1] or 0), 2)

    except Exception as e:
        logger.error(f"Error building student profile: {e}")

    return profile
