"""
Learning Advisor Service - 智能学习建议服务

功能:
1. 分析用户的错题历史和学习记录
2. 识别知识薄弱点
3. 生成个性化学习建议
4. 推荐相关题目进行巩固
5. 制定学习计划

参考实现:
- Khan Academy: 自适应学习路径
- Duolingo: 间隔重复系统 (Spaced Repetition)
- Google AutoML: 个性化推荐
- Facebook DLRM: 深度学习推荐模型
"""

import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum
from collections import Counter

from ..base_config import get_base_settings

settings = get_base_settings()

logger = logging.getLogger(__name__)

class LearningGoalType(str, Enum):
    """学习目标类型"""
    IMPROVE_WEAK_POINTS = "improve_weak_points"
    PREPARE_EXAM = "prepare_exam"
    DAILY_PRACTICE = "daily_practice"
    REVIEW_MISTAKES = "review_mistakes"
    EXPAND_KNOWLEDGE = "expand_knowledge"

class PriorityLevel(str, Enum):
    """优先级"""
    URGENT = "urgent"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

@dataclass
class LearningRecommendation:
    """学习推荐项"""
    title: str
    description: str
    priority: PriorityLevel
    subject: str
    knowledge_points: List[str]
    estimated_time_minutes: int
    resources: List[Dict[str, str]] = field(default_factory=list)  # type, url, title
    related_question_ids: List[int] = field(default_factory=list)

@dataclass
class WeakPointAnalysis:
    """薄弱点分析"""
    knowledge_point: str
    subject: str
    error_count: int
    error_rate: float
    recent_trend: str  # improving, declining, stable
    suggested_actions: List[str]

@dataclass
class StudyPlan:
    """学习计划"""
    user_id: int
    goal_type: LearningGoalType
    start_date: datetime
    end_date: datetime
    daily_tasks: List[Dict[str, Any]]
    total_estimated_hours: float
    progress_percentage: float = 0.0

@dataclass
class LearningProfile:
    """学习画像"""
    user_id: int
    total_questions: int
    correct_count: int
    overall_accuracy: float
    subject_stats: Dict[str, Dict[str, Any]]
    weak_points: List[WeakPointAnalysis]
    strong_points: List[str]
    learning_style: str  # visual, auditory, kinesthetic
    optimal_study_time: str
    streak_days: int
    last_active: datetime

class LearningAdvisorService:
    """
    智能学习建议服务

    基于用户的学习数据提供个性化建议:
    1. 错题分析 → 识别薄弱知识点
    2. 混合检索 → 推荐相关练习题
    3. LLM 生成 → 个性化学习建议
    4. 间隔重复 → 优化复习时间
    """

    def __init__(self):
        self._initialized = False

    async def initialize(self) -> bool:
        """初始化服务"""
        self._initialized = True
        return True

    async def analyze_user_profile(self, user_id: int) -> LearningProfile:
        """
        分析用户学习画像

        整合用户的所有学习数据，生成综合画像
        """
        from ..db.session import async_session_maker
        from sqlalchemy import select, func, case
        from ..db.models import Question, User

        async with async_session_maker() as session:
            # 获取用户的所有题目统计
            stmt = select(
                Question.subject,
                func.count(Question.id).label('total'),
                func.sum(
                    case((Question.mastery_level > 0.5, 1), else_=0)
                ).label('mastered'),
            ).where(Question.user_id == user_id).group_by(Question.subject)

            result = await session.execute(stmt)
            stats = result.all()

            # 构建学科统计
            subject_stats = {}
            total_questions = 0
            correct_count = 0

            for row in stats:
                subject_name = row.subject.value if hasattr(row.subject, 'value') else str(row.subject)
                subject_stats[subject_name] = {
                    'total': row.total,
                    'mastered': row.mastered or 0,
                    'accuracy': (row.mastered or 0) / row.total if row.total > 0 else 0,
                }
                total_questions += row.total
                correct_count += row.mastered or 0

            # 分析薄弱点
            weak_points = await self._analyze_weak_points(user_id, session)

            # 识别强项
            strong_points = [
                subject for subject, data in subject_stats.items()
                if data['accuracy'] > 0.8
            ]

            return LearningProfile(
                user_id=user_id,
                total_questions=total_questions,
                correct_count=correct_count,
                overall_accuracy=correct_count / total_questions if total_questions > 0 else 0,
                subject_stats=subject_stats,
                weak_points=weak_points,
                strong_points=strong_points,
                learning_style="visual",  # 可通过用户行为分析
                optimal_study_time="晚上 7-9 点",  # 可通过活跃时间分析
                streak_days=0,
                last_active=datetime.now(),
            )

    async def _analyze_weak_points(
        self,
        user_id: int,
        session,
    ) -> List[WeakPointAnalysis]:
        """分析用户的薄弱知识点"""
        from sqlalchemy import select
        from ..db.models import Question

        # 获取用户的错题
        stmt = select(Question).where(
            Question.user_id == user_id,
            Question.mastery_level < 0.5,
        ).order_by(Question.created_at.desc()).limit(100)

        result = await session.execute(stmt)
        questions = result.scalars().all()

        # 统计知识点错误频率
        knowledge_point_errors = Counter()
        subject_map = {}

        for q in questions:
            for kp in (q.tags or []):
                knowledge_point_errors[kp] += 1
                subject_map[kp] = q.subject.value if hasattr(q.subject, 'value') else str(q.subject)

        # 构建薄弱点分析
        weak_points = []
        total_errors = sum(knowledge_point_errors.values()) or 1

        for kp, count in knowledge_point_errors.most_common(10):
            weak_points.append(WeakPointAnalysis(
                knowledge_point=kp,
                subject=subject_map.get(kp, 'other'),
                error_count=count,
                error_rate=count / total_errors,
                recent_trend='stable',  # 可通过时间序列分析
                suggested_actions=[
                    f"复习「{kp}」的基础概念",
                    f"完成 5 道「{kp}」相关练习题",
                    f"观看「{kp}」讲解视频",
                ],
            ))

        return weak_points

    async def generate_recommendations(
        self,
        user_id: int,
        goal_type: LearningGoalType = LearningGoalType.IMPROVE_WEAK_POINTS,
        max_recommendations: int = 5,
    ) -> List[LearningRecommendation]:
        """
        生成个性化学习建议

        基于用户画像和学习目标，生成针对性建议
        """
        # 获取用户画像
        profile = await self.analyze_user_profile(user_id)

        recommendations = []

        if goal_type == LearningGoalType.IMPROVE_WEAK_POINTS:
            # 针对薄弱点生成建议
            for wp in profile.weak_points[:max_recommendations]:
                recommendations.append(LearningRecommendation(
                    title=f"强化练习: {wp.knowledge_point}",
                    description=f"您在「{wp.knowledge_point}」方面有 {wp.error_count} 次错误，建议重点复习。",
                    priority=PriorityLevel.HIGH if wp.error_rate > 0.2 else PriorityLevel.MEDIUM,
                    subject=wp.subject,
                    knowledge_points=[wp.knowledge_point],
                    estimated_time_minutes=30,
                    resources=[
                        {"type": "video", "title": f"{wp.knowledge_point} 讲解", "url": "#"},
                        {"type": "practice", "title": f"{wp.knowledge_point} 练习", "url": "#"},
                    ],
                ))

        elif goal_type == LearningGoalType.REVIEW_MISTAKES:
            # 复习错题建议
            recommendations.append(LearningRecommendation(
                title="今日错题复习",
                description=f"您有 {profile.total_questions - profile.correct_count} 道题需要复习",
                priority=PriorityLevel.HIGH,
                subject="综合",
                knowledge_points=[wp.knowledge_point for wp in profile.weak_points[:3]],
                estimated_time_minutes=45,
            ))

        elif goal_type == LearningGoalType.DAILY_PRACTICE:
            # 每日练习建议
            for subject, stats in profile.subject_stats.items():
                if stats['accuracy'] < 0.7:
                    recommendations.append(LearningRecommendation(
                        title=f"{subject} 每日练习",
                        description=f"当前正确率 {stats['accuracy']:.1%}，建议每天练习 10 道题",
                        priority=PriorityLevel.MEDIUM,
                        subject=subject,
                        knowledge_points=[],
                        estimated_time_minutes=20,
                    ))

        return recommendations[:max_recommendations]

    async def generate_study_plan(
        self,
        user_id: int,
        goal_type: LearningGoalType,
        duration_days: int = 7,
    ) -> StudyPlan:
        """
        生成学习计划

        根据用户目标和时间安排，生成每日学习任务
        """
        profile = await self.analyze_user_profile(user_id)
        recommendations = await self.generate_recommendations(user_id, goal_type)

        daily_tasks = []
        start_date = datetime.now()

        for day in range(duration_days):
            day_tasks = []

            # 分配任务到每一天
            for i, rec in enumerate(recommendations):
                if i % duration_days == day % len(recommendations):
                    day_tasks.append({
                        "title": rec.title,
                        "subject": rec.subject,
                        "knowledge_points": rec.knowledge_points,
                        "estimated_minutes": rec.estimated_time_minutes,
                        "completed": False,
                    })

            # 添加每日复习任务
            if profile.weak_points:
                wp = profile.weak_points[day % len(profile.weak_points)]
                day_tasks.append({
                    "title": f"复习: {wp.knowledge_point}",
                    "subject": wp.subject,
                    "knowledge_points": [wp.knowledge_point],
                    "estimated_minutes": 15,
                    "completed": False,
                })

            daily_tasks.append({
                "date": (start_date + timedelta(days=day)).isoformat(),
                "tasks": day_tasks,
            })

        total_hours = sum(
            task["estimated_minutes"]
            for day in daily_tasks
            for task in day["tasks"]
        ) / 60

        return StudyPlan(
            user_id=user_id,
            goal_type=goal_type,
            start_date=start_date,
            end_date=start_date + timedelta(days=duration_days),
            daily_tasks=daily_tasks,
            total_estimated_hours=total_hours,
        )

    async def get_similar_questions(
        self,
        user_id: int,
        question_id: int,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        使用混合检索获取相似题目

        结合 FAISS 向量检索和 BM25 关键词检索
        """
        from .hybrid_search_service import get_hybrid_search_service
        from .embedding_service import get_embedding_service
        from ..db.session import async_session_maker
        from sqlalchemy import select
        from ..db.models import Question

        # 获取原题目
        async with async_session_maker() as session:
            stmt = select(Question).where(Question.id == question_id)
            result = await session.execute(stmt)
            question = result.scalar_one_or_none()

            if not question:
                return []

            # 生成查询 embedding
            embedding_service = get_embedding_service()
            query_embedding = await embedding_service.embed_text(question.content)

            if not query_embedding:
                return []

            # 混合检索
            search_service = get_hybrid_search_service()
            await search_service.initialize()

            results = await search_service.hybrid_search(
                query_text=question.content,
                query_embedding=query_embedding,
                top_k=top_k + 1,  # 多取一个，排除自己
                filter_metadata={"subject": question.subject.value},
            )

            # 过滤掉原题目
            similar_questions = []
            for r in results:
                if r.doc_id != str(question_id):
                    similar_questions.append({
                        "question_id": r.doc_id,
                        "content": r.document,
                        "similarity_score": r.score,
                        "source": r.source,
                        "metadata": r.metadata,
                    })

            return similar_questions[:top_k]

    async def generate_learning_summary(
        self,
        user_id: int,
        period_days: int = 7,
    ) -> Dict[str, Any]:
        """
        生成学习总结报告

        包含:
        - 学习时间统计
        - 题目完成情况
        - 进步与不足
        - AI 点评
        """
        from ..services.llm_service import get_llm_service

        profile = await self.analyze_user_profile(user_id)

        # 构建总结数据
        summary_data = {
            "period": f"最近 {period_days} 天",
            "total_questions": profile.total_questions,
            "correct_rate": f"{profile.overall_accuracy:.1%}",
            "subject_performance": profile.subject_stats,
            "top_weak_points": [
                {"name": wp.knowledge_point, "error_count": wp.error_count}
                for wp in profile.weak_points[:5]
            ],
            "strong_points": profile.strong_points,
            "streak_days": profile.streak_days,
        }

        # 使用 LLM 生成个性化点评
        llm = get_llm_service()
        prompt = f"""
作为学习小书童，请根据以下学习数据，为学生生成一份温暖鼓励的学习总结:

学习数据:
- 总做题数: {profile.total_questions}
- 正确率: {profile.overall_accuracy:.1%}
- 薄弱知识点: {', '.join([wp.knowledge_point for wp in profile.weak_points[:3]])}
- 擅长领域: {', '.join(profile.strong_points) if profile.strong_points else '继续探索中'}

请生成:
1. 本周亮点 (2-3 点)
2. 需要加油的地方 (1-2 点)
3. 下周学习建议 (具体可执行)
4. 一句鼓励的话

语气要求: 温暖、鼓励、像朋友一样
"""

        ai_comment = await llm.generate(
            prompt=prompt,
            system_prompt="你是学习小书童，一位温暖有耐心的学习伙伴。",
            temperature=0.7,
            max_tokens=500,
        )

        summary_data["ai_comment"] = ai_comment or "继续加油，你做得很棒！"

        return summary_data

# Singleton instance
_learning_advisor_service = None

def get_learning_advisor_service() -> LearningAdvisorService:
    """Get singleton learning advisor service instance"""
    global _learning_advisor_service
    if _learning_advisor_service is None:
        _learning_advisor_service = LearningAdvisorService()
    return _learning_advisor_service
