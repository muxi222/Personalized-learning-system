
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Query, Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel, Field

from backend.core.db.session import get_db
from backend.core.crud import crud_question, crud_exam_correction, crud_task
from backend.modules.rpj.api.deps import get_current_user_id
from backend.modules.rpj.config import settings

# NOTE(student/TODO): RPJ 模块的“学习建议 Agent”需要学生自行实现。
# 为避免模块启动时报错，这里不再依赖不存在的 wzy.learning_advisor。
# 现有接口会在调用 Agent 失败时走“备用方案”，因此设置为 None 即可安全降级。
LearningAdvisorAgent = None  # type: ignore

# 相似题推荐：RPJ 模块已有实现（如未来需要学生实现，也可改为 try/except + TODO）
from backend.modules.rpj.agents.similar_question_agent import SimilarQuestionAgent

logger = logging.getLogger(__name__)

router = APIRouter()

def validate_subject(subject: str) -> None:
    """验证学科是否属于RPJ模块"""
    if subject not in settings.SUBJECTS:
        raise HTTPException(
            status_code=400,
            detail=f"Subject '{subject}' is not supported by RPJ module. "
                   f"Supported subjects: {settings.SUBJECTS}"
        )

# ============ Enums ============

class LearningGoalType(str, Enum):
    """学习目标类型"""
    IMPROVE_WEAK_POINTS = "improve_weak_points"
    PREPARE_EXAM = "prepare_exam"
    DAILY_PRACTICE = "daily_practice"
    REVIEW_MISTAKES = "review_mistakes"
    EXPAND_KNOWLEDGE = "expand_knowledge"
    FOCUS_SUBJECT = "focus_subject"

class PriorityLevel(str, Enum):
    """优先级级别"""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

class SubjectType(str, Enum):
    """学科类型"""
    CHINESE = "chinese"
    ENGLISH = "english"
    MORALITY = "morality"

# ============ Response Models ============

class WeakPointResponse(BaseModel):
    """薄弱点响应"""
    knowledge_point: str
    subject: str
    error_count: int
    error_rate: float
    recent_trend: str
    suggested_actions: List[str]
    related_question_ids: List[int] = []

class LearningProfileResponse(BaseModel):
    """学习画像响应"""
    user_id: int
    total_questions: int
    total_corrections: int
    correct_count: int
    overall_accuracy: float
    subject_stats: Dict[str, Dict[str, Any]]
    weak_points: List[WeakPointResponse]
    strong_points: List[str]
    learning_style: Optional[str] = None
    optimal_study_time: Optional[str] = None
    streak_days: int = 0
    mastery_overview: Dict[str, float] = {}

class RecommendationResponse(BaseModel):
    """学习推荐响应"""
    id: str
    title: str
    description: str
    priority: str
    subject: str
    knowledge_points: List[str]
    estimated_time_minutes: int
    resources: List[Dict[str, str]]
    related_question_ids: List[int]
    action_type: str
    difficulty_level: str

class StudyPlanResponse(BaseModel):
    """学习计划响应"""
    user_id: int
    goal_type: str
    start_date: str
    end_date: str
    daily_tasks: List[Dict[str, Any]]
    total_estimated_hours: float
    progress_percentage: float
    focus_subjects: List[str]
    key_milestones: List[Dict[str, str]]

class SimilarQuestionResponse(BaseModel):
    """相似题目响应"""
    question_id: int
    content: str
    similarity_score: float
    source: str
    subject: str
    difficulty: str
    knowledge_points: List[str]
    is_attempted: bool = False
    correct_answer: Optional[str] = None

class LearningSummaryResponse(BaseModel):
    """学习总结响应"""
    period: str
    total_questions: int
    total_corrections: int
    correct_rate: float
    subject_performance: Dict[str, Dict[str, Any]]
    top_weak_points: List[Dict[str, Any]]
    strong_points: List[str]
    streak_days: int
    ai_comment: str
    improvement_rate: Optional[float] = None
    next_week_goals: List[str] = []

class LearningProgressResponse(BaseModel):
    """学习进度响应"""
    user_id: int
    current_week: Dict[str, Any]
    weekly_progress: List[Dict[str, Any]]
    subject_trends: Dict[str, List[float]]
    upcoming_deadlines: List[Dict[str, Any]]

class LearningFeedbackRequest(BaseModel):
    """学习反馈请求"""
    recommendation_id: Optional[str] = None
    helpful: bool = True
    comment: Optional[str] = None
    rating: Optional[int] = Field(None, ge=1, le=5, description="评分 1-5")

# ============ Helper Functions ============

async def _get_subject_knowledge_points(subject: str) -> List[str]:
    """获取学科知识点"""
    subject_knowledge_map = {
        "chinese": [
            "基础知识", "古诗文阅读", "现代文阅读", "作文", "文言文",
            "词语运用", "病句修改", "标点符号", "修辞手法", "文学常识"
        ],
        "english": [
            "词汇", "语法", "阅读理解", "完形填空", "作文",
            "听力", "口语", "翻译", "时态", "句型结构"
        ],
        "morality": [
            "道德修养", "法律常识", "心理健康", "社会公德", "公民意识",
            "社会主义核心价值观", "传统文化", "时事政治", "法治观念", "国情教育"
        ]
    }
    return subject_knowledge_map.get(subject, [])

async def _get_subject_specific_suggestions(subject: str) -> List[str]:
    """获取学科特定的学习建议"""
    suggestions_map = {
        "chinese": [
            "多阅读经典文学作品",
            "积累好词好句",
            "练习写作技巧",
            "背诵古诗文",
            "分析文章结构"
        ],
        "english": [
            "每天记忆新单词",
            "练习英语听力",
            "阅读英文文章",
            "练习口语表达",
            "学习语法规则"
        ],
        "morality": [
            "关注时事新闻",
            "学习法律法规",
            "理解道德规范",
            "参加社会实践",
            "讨论社会问题"
        ]
    }
    return suggestions_map.get(subject, [])

async def _get_learning_profile_data(db: AsyncSession, user_id: int, subjects: List[str] = None) -> Dict[str, Any]:
    """获取学习画像数据"""
    if subjects is None:
        subjects = settings.SUBJECTS

    profile = {
        "user_id": user_id,
        "total_questions": 0,
        "total_corrections": 0,
        "correct_count": 0,
        "subject_stats": {},
        "weak_points": [],
        "strong_points": [],
        "learning_style": None,
        "optimal_study_time": None,
        "streak_days": 0,
        "mastery_overview": {},
    }

    try:
        # 统计题目数据
        for subject in subjects:
            # 获取该学科的题目
            questions_query = select(crud_question.model).where(
                crud_question.model.user_id == user_id,
                crud_question.model.subject == subject
            )
            questions_result = await db.execute(questions_query)
            subject_questions = questions_result.scalars().all()

            total = len(subject_questions)
            correct = sum(1 for q in subject_questions if hasattr(q, 'is_correct') and q.is_correct)

            if total > 0:
                accuracy = correct / total
                profile["total_questions"] += total
                profile["correct_count"] += correct

                # 按知识点统计
                knowledge_points_stats = {}
                for q in subject_questions:
                    if hasattr(q, 'knowledge_points') and q.knowledge_points:
                        for kp in q.knowledge_points:
                            if kp not in knowledge_points_stats:
                                knowledge_points_stats[kp] = {"total": 0, "correct": 0}
                            knowledge_points_stats[kp]["total"] += 1
                            if hasattr(q, 'is_correct') and q.is_correct:
                                knowledge_points_stats[kp]["correct"] += 1

                profile["subject_stats"][subject] = {
                    "total_questions": total,
                    "correct_count": correct,
                    "accuracy": accuracy,
                    "knowledge_points_stats": knowledge_points_stats,
                    "question_ids": [q.id for q in subject_questions][:10]
                }

                # 识别薄弱知识点（准确率低于60%的知识点）
                for kp, stats in knowledge_points_stats.items():
                    if stats["total"] >= 3:  # 至少有3道题才统计
                        kp_accuracy = stats["correct"] / stats["total"] if stats["total"] > 0 else 0
                        if kp_accuracy < 0.6:
                            subject_suggestions = await _get_subject_specific_suggestions(subject)
                            profile["weak_points"].append({
                                "knowledge_point": kp,
                                "subject": subject,
                                "error_count": stats["total"] - stats["correct"],
                                "error_rate": 1 - kp_accuracy,
                                "recent_trend": "需加强",
                                "suggested_actions": subject_suggestions[:3],
                                "related_question_ids": [q.id for q in subject_questions
                                                        if hasattr(q, 'knowledge_points') and
                                                        kp in getattr(q, 'knowledge_points', [])]
                            })

                # 识别优势知识点（准确率高于80%的知识点）
                strong_points = []
                for kp, stats in knowledge_points_stats.items():
                    if stats["total"] >= 5:  # 至少有5道题才统计
                        kp_accuracy = stats["correct"] / stats["total"] if stats["total"] > 0 else 0
                        if kp_accuracy > 0.8:
                            strong_points.append(f"{subject}:{kp}")

                if strong_points:
                    profile["strong_points"].extend(strong_points)

        # 统计批改记录数据
        for subject in subjects:
            corrections_query = select(crud_exam_correction.model).where(
                crud_exam_correction.model.user_id == user_id,
                crud_exam_correction.model.subject == subject
            )
            corrections_result = await db.execute(corrections_query)
            subject_corrections = corrections_result.scalars().all()

            total_corrections = len(subject_corrections)
            profile["total_corrections"] += total_corrections

            if total_corrections > 0:
                avg_accuracy = sum(c.accuracy_rate for c in subject_corrections if hasattr(c, 'accuracy_rate')) / total_corrections

                if subject not in profile["subject_stats"]:
                    profile["subject_stats"][subject] = {}

                profile["subject_stats"][subject]["total_corrections"] = total_corrections
                profile["subject_stats"][subject]["avg_accuracy"] = avg_accuracy

        # 计算总体准确率
        if profile["total_questions"] > 0:
            profile["overall_accuracy"] = profile["correct_count"] / profile["total_questions"]
        else:
            profile["overall_accuracy"] = 0.0

        # 调用Agent获取学习风格分析
        try:
            advisor = LearningAdvisorAgent()
            style_analysis = await advisor.analyze_learning_style(user_id, subjects)
            profile["learning_style"] = style_analysis.get("learning_style")
            profile["optimal_study_time"] = style_analysis.get("optimal_study_time")
        except Exception as e:
            logger.error(f"学习风格分析失败: {str(e)}")
            # 默认设置
            profile["learning_style"] = "综合型"
            profile["optimal_study_time"] = "晚上"

        # 计算连续学习天数
        try:
            streak = 0
            for day in range(7):
                check_date = datetime.utcnow() - timedelta(days=day)

                # 检查该天是否有题目或批改记录
                questions_check = await db.execute(
                    select(func.count(crud_question.model.id)).where(
                        crud_question.model.user_id == user_id,
                        func.date(crud_question.model.created_at) == check_date.date()
                    )
                )
                questions_count = questions_check.scalar() or 0

                corrections_check = await db.execute(
                    select(func.count(crud_exam_correction.model.id)).where(
                        crud_exam_correction.model.user_id == user_id,
                        func.date(crud_exam_correction.model.created_at) == check_date.date()
                    )
                )
                corrections_count = corrections_check.scalar() or 0

                if questions_count > 0 or corrections_count > 0:
                    streak += 1
                else:
                    break

            profile["streak_days"] = streak
        except Exception as e:
            logger.error(f"计算学习连续天数失败: {str(e)}")
            profile["streak_days"] = 0

        # 计算掌握度概览
        for subject in subjects:
            if subject in profile["subject_stats"]:
                stats = profile["subject_stats"][subject]
                if "accuracy" in stats:
                    profile["mastery_overview"][subject] = stats["accuracy"]

    except Exception as e:
        logger.error(f"获取学习画像数据失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取学习画像数据失败: {str(e)}")

    return profile

async def _generate_subject_recommendation(subject: str, user_id: int, goal_type: LearningGoalType) -> Dict[str, Any]:
    """生成学科特定推荐"""
    base_recommendations = {
        "chinese": {
            "improve_weak_points": {
                "title": "语文薄弱点专项提升",
                "description": "针对语文知识薄弱环节进行专项训练",
                "action_type": "practice",
                "difficulty_level": "medium",
                "resources": [
                    {"type": "article", "title": "语文基础知识大全", "url": "#"},
                    {"type": "video", "title": "文言文解析技巧", "url": "#"}
                ]
            },
            "prepare_exam": {
                "title": "语文考试备考",
                "description": "全面复习语文考试重点内容",
                "action_type": "review",
                "difficulty_level": "high",
                "resources": [
                    {"type": "practice", "title": "历年真题", "url": "#"},
                    {"type": "article", "title": "考试技巧", "url": "#"}
                ]
            },
            "daily_practice": {
                "title": "语文日常练习",
                "description": "每日语文基础知识练习",
                "action_type": "practice",
                "difficulty_level": "beginner",
                "resources": [
                    {"type": "practice", "title": "每日一练", "url": "#"}
                ]
            }
        },
        "english": {
            "improve_weak_points": {
                "title": "英语薄弱点专项提升",
                "description": "针对英语知识薄弱环节进行专项训练",
                "action_type": "practice",
                "difficulty_level": "medium",
                "resources": [
                    {"type": "article", "title": "英语语法总结", "url": "#"},
                    {"type": "audio", "title": "听力训练", "url": "#"}
                ]
            },
            "prepare_exam": {
                "title": "英语考试备考",
                "description": "全面复习英语考试重点内容",
                "action_type": "review",
                "difficulty_level": "high",
                "resources": [
                    {"type": "practice", "title": "模拟试题", "url": "#"},
                    {"type": "article", "title": "写作模板", "url": "#"}
                ]
            },
            "daily_practice": {
                "title": "英语日常练习",
                "description": "每日英语词汇和语法练习",
                "action_type": "practice",
                "difficulty_level": "beginner",
                "resources": [
                    {"type": "practice", "title": "每日单词", "url": "#"}
                ]
            }
        },
        "morality": {
            "improve_weak_points": {
                "title": "道法薄弱点专项提升",
                "description": "针对道德与法治知识薄弱环节进行专项训练",
                "action_type": "practice",
                "difficulty_level": "medium",
                "resources": [
                    {"type": "article", "title": "法律常识", "url": "#"},
                    {"type": "video", "title": "道德规范讲解", "url": "#"}
                ]
            },
            "prepare_exam": {
                "title": "道法考试备考",
                "description": "全面复习道德与法治考试重点内容",
                "action_type": "review",
                "difficulty_level": "high",
                "resources": [
                    {"type": "practice", "title": "案例分析", "url": "#"},
                    {"type": "article", "title": "时事政治", "url": "#"}
                ]
            },
            "daily_practice": {
                "title": "道法日常学习",
                "description": "每日道德与法治知识学习",
                "action_type": "study",
                "difficulty_level": "beginner",
                "resources": [
                    {"type": "article", "title": "每日新闻", "url": "#"}
                ]
            }
        }
    }

    # 获取基础推荐配置
    subject_config = base_recommendations.get(subject, {})
    goal_config = subject_config.get(goal_type.value, {})

    # 获取学科知识点
    knowledge_points = await _get_subject_knowledge_points(subject)

    # 构建推荐
    recommendation = {
        "id": f"{subject}_{goal_type.value}_{user_id}_{datetime.now().timestamp()}",
        "title": goal_config.get("title", f"{subject}学习计划"),
        "description": goal_config.get("description", f"{subject}学习计划"),
        "priority": "medium",
        "subject": subject,
        "knowledge_points": knowledge_points[:3],  # 取前3个知识点
        "estimated_time_minutes": 45,
        "resources": goal_config.get("resources", []),
        "related_question_ids": [],
        "action_type": goal_config.get("action_type", "practice"),
        "difficulty_level": goal_config.get("difficulty_level", "medium"),
    }

    return recommendation

# ============ API Endpoints ============

@router.get("/profile", response_model=LearningProfileResponse)
async def get_learning_profile(
    subject: Optional[str] = Query(None, description="学科筛选"),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    获取用户学习画像

    包含:
    - 总体学习统计
    - 各学科表现
    - 薄弱知识点
    - 学习风格分析
    """
    # 验证学科是否属于WZY模块
    if subject:
        validate_subject(subject)
        subjects = [subject]
    else:
        subjects = settings.SUBJECTS

    # 获取学习画像数据
    profile_data = await _get_learning_profile_data(db, user_id, subjects)

    # 转换薄弱点格式
    weak_points = []
    for wp in profile_data.get("weak_points", []):
        weak_points.append(WeakPointResponse(
            knowledge_point=wp["knowledge_point"],
            subject=wp["subject"],
            error_count=wp["error_count"],
            error_rate=wp["error_rate"],
            recent_trend=wp["recent_trend"],
            suggested_actions=wp["suggested_actions"],
            related_question_ids=wp.get("related_question_ids", [])[:5]  # 只取前5个
        ))

    return LearningProfileResponse(
        user_id=profile_data["user_id"],
        total_questions=profile_data["total_questions"],
        total_corrections=profile_data["total_corrections"],
        correct_count=profile_data["correct_count"],
        overall_accuracy=profile_data.get("overall_accuracy", 0.0),
        subject_stats=profile_data.get("subject_stats", {}),
        weak_points=weak_points,
        strong_points=profile_data.get("strong_points", []),
        learning_style=profile_data.get("learning_style"),
        optimal_study_time=profile_data.get("optimal_study_time"),
        streak_days=profile_data.get("streak_days", 0),
        mastery_overview=profile_data.get("mastery_overview", {}),
    )

@router.get("/recommendations", response_model=List[RecommendationResponse])
async def get_recommendations(
    goal: str = Query("improve_weak_points", description="学习目标类型"),
    subject: Optional[str] = Query(None, description="学科筛选"),
    limit: int = Query(5, ge=1, le=20, description="推荐数量"),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    获取个性化学习建议

    目标类型:
    - improve_weak_points: 强化薄弱点
    - prepare_exam: 备考复习
    - daily_practice: 每日练习
    - review_mistakes: 错题复习
    - expand_knowledge: 知识拓展
    - focus_subject: 专注特定学科
    """
    # 验证学科是否属于WZY模块
    if subject:
        validate_subject(subject)
        subjects = [subject]
    else:
        subjects = settings.SUBJECTS

    # 验证目标类型
    try:
        goal_type = LearningGoalType(goal)
    except ValueError:
        goal_type = LearningGoalType.IMPROVE_WEAK_POINTS

    try:
        # 尝试调用学习建议Agent
        try:
            advisor = LearningAdvisorAgent()
            recommendations = await advisor.generate_recommendations(
                user_id=user_id,
                goal_type=goal_type,
                subjects=subjects,
                max_recommendations=limit,
            )
        except Exception as e:
            logger.warning(f"调用学习建议Agent失败，使用备用方案: {str(e)}")
            recommendations = None

        if not recommendations:
            # 如果没有推荐，使用备用方案生成推荐
            recommendations = []
            for subj in subjects:
                rec = await _generate_subject_recommendation(subj, user_id, goal_type)
                recommendations.append(rec)

        # 转换响应格式
        response_list = []
        for rec in recommendations[:limit]:  # 限制数量
            response_list.append(RecommendationResponse(
                id=rec.get("id", f"rec_{datetime.now().timestamp()}"),
                title=rec.get("title", ""),
                description=rec.get("description", ""),
                priority=rec.get("priority", "medium"),
                subject=rec.get("subject", subjects[0] if subjects else "chinese"),
                knowledge_points=rec.get("knowledge_points", []),
                estimated_time_minutes=rec.get("estimated_time_minutes", 30),
                resources=rec.get("resources", []),
                related_question_ids=rec.get("related_question_ids", []),
                action_type=rec.get("action_type", "practice"),
                difficulty_level=rec.get("difficulty_level", "medium"),
            ))

        return response_list

    except Exception as e:
        logger.error(f"获取学习建议失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取学习建议失败: {str(e)}")

@router.get("/study-plan", response_model=StudyPlanResponse)
async def get_study_plan(
    goal: str = Query("improve_weak_points", description="学习目标"),
    subject: Optional[str] = Query(None, description="学科筛选"),
    days: int = Query(7, ge=1, le=30, description="计划天数"),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    生成个性化学习计划

    根据用户的学习画像和目标，生成每日学习任务
    """
    # 验证学科是否属于WZY模块
    if subject:
        validate_subject(subject)
        subjects = [subject]
    else:
        subjects = settings.SUBJECTS

    # 验证目标类型
    try:
        goal_type = LearningGoalType(goal)
    except ValueError:
        goal_type = LearningGoalType.IMPROVE_WEAK_POINTS

    try:
        # 尝试调用学习建议Agent生成学习计划
        try:
            advisor = LearningAdvisorAgent()
            study_plan = await advisor.generate_study_plan(
                user_id=user_id,
                goal_type=goal_type,
                subjects=subjects,
                duration_days=days,
            )
        except Exception as e:
            logger.warning(f"调用学习计划Agent失败，使用备用方案: {str(e)}")
            study_plan = None

        # 如果没有生成计划，返回一个基本计划
        if not study_plan:
            start_date = datetime.utcnow().date()
            end_date = start_date + timedelta(days=days-1)

            # 学科每日任务模板
            subject_task_templates = {
                "chinese": [
                    {"title": "古诗文背诵", "type": "memory", "estimated_time": 20},
                    {"title": "阅读理解练习", "type": "practice", "estimated_time": 25},
                    {"title": "作文练习", "type": "writing", "estimated_time": 30}
                ],
                "english": [
                    {"title": "单词记忆", "type": "memory", "estimated_time": 20},
                    {"title": "语法练习", "type": "practice", "estimated_time": 25},
                    {"title": "听力练习", "type": "listening", "estimated_time": 15}
                ],
                "morality": [
                    {"title": "法律知识学习", "type": "study", "estimated_time": 20},
                    {"title": "案例分析", "type": "analysis", "estimated_time": 25},
                    {"title": "时事讨论", "type": "discussion", "estimated_time": 15}
                ]
            }

            daily_tasks = []
            for i in range(days):
                day = start_date + timedelta(days=i)
                tasks = []

                # 为每个学科分配任务
                for subj in subjects:
                    if subj in subject_task_templates:
                        # 每天为每个学科分配1-2个任务
                        day_tasks = subject_task_templates[subj][:2]  # 取前2个任务
                        for task_template in day_tasks:
                            tasks.append({
                                "title": f"{subj} - {task_template['title']}",
                                "subject": subj,
                                "estimated_time": task_template["estimated_time"],
                                "type": task_template["type"]
                            })

                daily_tasks.append({
                    "day": day.strftime("%Y-%m-%d"),
                    "tasks": tasks
                })

            # 计算总预估时间
            total_estimated_minutes = sum(
                sum(task.get("estimated_time", 0) for task in day_tasks["tasks"])
                for day_tasks in daily_tasks
            )
            total_estimated_hours = total_estimated_minutes / 60

            # 设置关键里程碑
            key_milestones = []
            if days >= 3:
                key_milestones.append({
                    "date": (start_date + timedelta(days=2)).strftime("%Y-%m-%d"),
                    "milestone": "完成第一阶段学习"
                })
            if days >= 7:
                key_milestones.append({
                    "date": (start_date + timedelta(days=6)).strftime("%Y-%m-%d"),
                    "milestone": "完成一周学习计划"
                })

            study_plan = {
                "user_id": user_id,
                "goal_type": goal_type.value,
                "start_date": start_date,
                "end_date": end_date,
                "daily_tasks": daily_tasks,
                "total_estimated_hours": total_estimated_hours,
                "progress_percentage": 0.0,
                "focus_subjects": subjects,
                "key_milestones": key_milestones
            }

        return StudyPlanResponse(
            user_id=study_plan.get("user_id", user_id),
            goal_type=study_plan.get("goal_type", goal_type.value),
            start_date=study_plan.get("start_date", datetime.utcnow().date()).isoformat(),
            end_date=study_plan.get("end_date", datetime.utcnow().date() + timedelta(days=days)).isoformat(),
            daily_tasks=study_plan.get("daily_tasks", []),
            total_estimated_hours=study_plan.get("total_estimated_hours", 0.0),
            progress_percentage=study_plan.get("progress_percentage", 0.0),
            focus_subjects=study_plan.get("focus_subjects", subjects),
            key_milestones=study_plan.get("key_milestones", []),
        )

    except Exception as e:
        logger.error(f"生成学习计划失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"生成学习计划失败: {str(e)}")

@router.get("/similar-questions/{question_id}", response_model=List[SimilarQuestionResponse])
async def get_similar_questions(
    question_id: int = Path(..., description="原题ID"),
    limit: int = Query(5, ge=1, le=20, description="推荐数量"),
    subject: Optional[str] = Query(None, description="学科筛选"),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    获取相似题目推荐（举一反三）

    使用向量检索找到相似的题目
    """
    try:
        # 获取原题信息
        question = await crud_question.get_question(db, question_id, user_id)
        if not question:
            raise HTTPException(status_code=404, detail="题目不存在")

        # 验证学科是否属于WZY模块
        if question.subject not in settings.SUBJECTS:
            raise HTTPException(
                status_code=400,
                detail=f"题目学科'{question.subject}'不属于WZY模块支持的范围"
            )

        # 如果指定了学科，验证是否匹配
        if subject and question.subject != subject:
            raise HTTPException(
                status_code=400,
                detail=f"题目学科'{question.subject}'与指定学科'{subject}'不匹配"
            )

        try:
            # 调用相似题目Agent
            agent = SimilarQuestionAgent(question.subject)
            similar_questions = await agent.find_similar(
                question_content=question.content,
                subject=question.subject,
                user_id=user_id,
                top_k=limit,
            )
        except Exception as e:
            logger.warning(f"调用相似题目Agent失败: {str(e)}")
            similar_questions = {"similar_questions": []}

        # 如果没有找到相似题目，返回数据库中的同类题目
        if not similar_questions.get("similar_questions"):
            # 从数据库获取同类型题目
            backup_query = select(crud_question.model).where(
                crud_question.model.subject == question.subject,
                crud_question.model.user_id == user_id,
                crud_question.model.id != question_id
            ).order_by(func.random()).limit(limit)

            backup_result = await db.execute(backup_query)
            backup_questions = backup_result.scalars().all()

            similar_questions["similar_questions"] = []
            for q in backup_questions:
                similar_questions["similar_questions"].append({
                    "id": q.id,
                    "content": q.content,
                    "similarity_score": 0.5,  # 默认相似度
                    "source": "database",
                    "subject": q.subject,
                    "difficulty": getattr(q, 'difficulty', 'medium'),
                    "knowledge_points": getattr(q, 'knowledge_points', []),
                    "correct_answer": getattr(q, 'correct_answer', None)
                })

        # 转换响应格式
        response_list = []
        for sq in similar_questions.get("similar_questions", []):
            # 检查用户是否已尝试过该题目
            is_attempted = False
            if sq.get("id"):
                existing_question = await crud_question.get_question(db, sq["id"], user_id)
                if existing_question:
                    is_attempted = True

            response_list.append(SimilarQuestionResponse(
                question_id=sq.get("id", 0),
                content=sq.get("content", ""),
                similarity_score=sq.get("similarity_score", 0.0),
                source=sq.get("source", "database"),
                subject=sq.get("subject", question.subject),
                difficulty=sq.get("difficulty", "medium"),
                knowledge_points=sq.get("knowledge_points", []),
                is_attempted=is_attempted,
                correct_answer=sq.get("correct_answer"),
            ))

        return response_list

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取相似题目失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取相似题目失败: {str(e)}")

@router.get("/summary", response_model=LearningSummaryResponse)
async def get_learning_summary(
    days: int = Query(7, ge=1, le=90, description="统计天数"),
    subject: Optional[str] = Query(None, description="学科筛选"),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    获取学习总结报告

    包含:
    - 学习统计
    - 进步分析
    - AI 个性化点评
    """
    # 验证学科是否属于WZY模块
    if subject:
        validate_subject(subject)
        subjects = [subject]
    else:
        subjects = settings.SUBJECTS

    try:
        # 尝试调用学习建议Agent生成总结
        try:
            advisor = LearningAdvisorAgent()
            summary = await advisor.generate_learning_summary(
                user_id=user_id,
                subjects=subjects,
                period_days=days,
            )
        except Exception as e:
            logger.warning(f"调用学习总结Agent失败，使用备用方案: {str(e)}")
            summary = None

        # 如果没有生成总结，生成一个基本总结
        if not summary:
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=days)

            # 统计题目
            total_questions = 0
            correct_count = 0
            subject_performance = {}

            for subj in subjects:
                questions_query = select(crud_question.model).where(
                    crud_question.model.user_id == user_id,
                    crud_question.model.subject == subj,
                    crud_question.model.created_at >= start_date,
                    crud_question.model.created_at <= end_date
                )
                questions_result = await db.execute(questions_query)
                subject_questions = questions_result.scalars().all()

                subject_total = len(subject_questions)
                subject_correct = sum(1 for q in subject_questions if hasattr(q, 'is_correct') and q.is_correct)

                total_questions += subject_total
                correct_count += subject_correct

                if subject_total > 0:
                    accuracy = subject_correct / subject_total
                    subject_performance[subj] = {
                        "total_questions": subject_total,
                        "correct_count": subject_correct,
                        "accuracy": accuracy
                    }

            correct_rate = correct_count / total_questions if total_questions > 0 else 0.0

            # 生成AI评语
            if correct_rate > 0.8:
                ai_comment = "学习效果很好，继续保持！"
            elif correct_rate > 0.6:
                ai_comment = "学习效果不错，继续努力！"
            else:
                ai_comment = "需要加强学习，建议多练习薄弱知识点。"

            summary = {
                "period": f"最近{days}天",
                "total_questions": total_questions,
                "total_corrections": 0,
                "correct_rate": correct_rate,
                "subject_performance": subject_performance,
                "top_weak_points": [],
                "strong_points": [subj for subj, perf in subject_performance.items()
                                if perf.get("accuracy", 0) > 0.7],
                "streak_days": 0,
                "ai_comment": ai_comment,
                "improvement_rate": None,
                "next_week_goals": [
                    "保持每日学习习惯",
                    "重点复习薄弱知识点",
                    "完成至少3套练习题"
                ]
            }

        return LearningSummaryResponse(
            period=summary.get("period", f"最近{days}天"),
            total_questions=summary.get("total_questions", 0),
            total_corrections=summary.get("total_corrections", 0),
            correct_rate=summary.get("correct_rate", 0.0),
            subject_performance=summary.get("subject_performance", {}),
            top_weak_points=summary.get("top_weak_points", []),
            strong_points=summary.get("strong_points", []),
            streak_days=summary.get("streak_days", 0),
            ai_comment=summary.get("ai_comment", "继续努力学习！"),
            improvement_rate=summary.get("improvement_rate"),
            next_week_goals=summary.get("next_week_goals", []),
        )

    except Exception as e:
        logger.error(f"生成学习总结失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"生成学习总结失败: {str(e)}")

@router.post("/feedback")
async def submit_learning_feedback(
    feedback: LearningFeedbackRequest,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    提交学习建议反馈

    用于改进推荐算法
    """
    try:
        # 记录反馈用于后续优化
        logger.info(
            f"用户 {user_id} 反馈: "
            f"recommendation={feedback.recommendation_id}, "
            f"helpful={feedback.helpful}, "
            f"rating={feedback.rating}, "
            f"comment={feedback.comment}"
        )

        # 尝试调用学习建议Agent处理反馈
        try:
            advisor = LearningAdvisorAgent()
            await advisor.process_feedback(
                user_id=user_id,
                recommendation_id=feedback.recommendation_id,
                helpful=feedback.helpful,
                rating=feedback.rating,
                comment=feedback.comment,
            )
        except Exception as e:
            logger.warning(f"处理反馈Agent失败: {str(e)}")
            # 即使Agent失败，也要记录反馈

        return {
            "success": True,
            "message": "感谢你的反馈！我们会不断改进。",
        }

    except Exception as e:
        logger.error(f"处理学习反馈失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"处理反馈失败: {str(e)}")

@router.get("/progress", response_model=LearningProgressResponse)
async def get_learning_progress(
    subject: Optional[str] = Query(None, description="学科筛选"),
    weeks: int = Query(4, ge=1, le=12, description="统计周数"),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    获取学习进度报告

    包含:
    - 本周学习情况
    - 每周进度趋势
    - 学科趋势
    - 即将到期的任务
    """
    # 验证学科是否属于WZY模块
    if subject:
        validate_subject(subject)
        subjects = [subject]
    else:
        subjects = settings.SUBJECTS

    try:
        # 尝试调用学习建议Agent获取进度报告
        try:
            advisor = LearningAdvisorAgent()
            progress_report = await advisor.get_learning_progress(
                user_id=user_id,
                subjects=subjects,
                weeks=weeks,
            )
        except Exception as e:
            logger.warning(f"调用学习进度Agent失败，使用备用方案: {str(e)}")
            progress_report = None

        # 如果没有报告，生成一个基本报告
        if not progress_report:
            now = datetime.utcnow()
            week_start = now - timedelta(days=now.weekday())
            week_end = week_start + timedelta(days=6)

            # 统计本周数据
            current_week_questions = {}
            for subj in subjects:
                questions_query = select(crud_question.model).where(
                    crud_question.model.user_id == user_id,
                    crud_question.model.subject == subj,
                    crud_question.model.created_at >= week_start,
                    crud_question.model.created_at <= week_end
                )
                questions_result = await db.execute(questions_query)
                week_questions = questions_result.scalars().all()

                total = len(week_questions)
                correct = sum(1 for q in week_questions if hasattr(q, 'is_correct') and q.is_correct)

                current_week_questions[subj] = {
                    "total": total,
                    "correct": correct,
                    "accuracy": correct / total if total > 0 else 0
                }

            # 计算本周总学习时间（假设每道题平均5分钟）
            total_study_time = sum(stats["total"] for stats in current_week_questions.values()) * 5

            current_week = {
                "week_start": week_start.strftime("%Y-%m-%d"),
                "week_end": week_end.strftime("%Y-%m-%d"),
                "total_study_time": total_study_time,
                "completed_tasks": sum(stats["total"] for stats in current_week_questions.values()),
                "total_tasks": sum(stats["total"] for stats in current_week_questions.values()) + 5,  # 额外任务
                "accuracy_rate": (
                    sum(stats["correct"] for stats in current_week_questions.values()) /
                    sum(stats["total"] for stats in current_week_questions.values())
                ) if sum(stats["total"] for stats in current_week_questions.values()) > 0 else 0.0,
            }

            # 生成每周进度数据
            weekly_progress = []
            for i in range(weeks):
                week_date = now - timedelta(weeks=i)
                # 简化处理：随机生成数据
                weekly_progress.append({
                    "week": week_date.strftime("%Y-%W"),
                    "study_time": max(0, 300 - i * 20),  # 递减
                    "completed_tasks": max(0, 20 - i * 2),
                    "accuracy": 0.6 + i * 0.05,  # 递增
                })

            # 生成学科趋势
            subject_trends = {}
            for subj in subjects:
                subject_trends[subj] = [0.5 + i * 0.1 for i in range(weeks)]  # 递增趋势

            # 获取即将到期的任务
            upcoming_deadlines = []
            try:
                tasks_query = select(crud_task.model).where(
                    crud_task.model.user_id == user_id,
                    crud_task.model.status.in_(["pending", "processing"])
                ).order_by(crud_task.model.created_at).limit(5)

                tasks_result = await db.execute(tasks_query)
                tasks = tasks_result.scalars().all()

                for task in tasks:
                    if hasattr(task, 'deadline') and task.deadline:
                        upcoming_deadlines.append({
                            "task_id": str(getattr(task, 'task_id', getattr(task, 'id', ''))),
                            "title": getattr(task, 'task_type', '学习任务'),
                            "deadline": task.deadline.isoformat(),
                            "subject": getattr(task, 'subject', subjects[0] if subjects else 'chinese'),
                        })
            except Exception as e:
                logger.warning(f"获取任务失败: {str(e)}")

            progress_report = {
                "user_id": user_id,
                "current_week": current_week,
                "weekly_progress": weekly_progress,
                "subject_trends": subject_trends,
                "upcoming_deadlines": upcoming_deadlines,
            }

        return LearningProgressResponse(
            user_id=progress_report.get("user_id", user_id),
            current_week=progress_report.get("current_week", {}),
            weekly_progress=progress_report.get("weekly_progress", []),
            subject_trends=progress_report.get("subject_trends", {}),
            upcoming_deadlines=progress_report.get("upcoming_deadlines", []),
        )

    except Exception as e:
        logger.error(f"获取学习进度失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取学习进度失败: {str(e)}")

@router.get("/weak-points/detailed")
async def get_detailed_weak_points(
    subject: Optional[str] = Query(None, description="学科筛选"),
    limit: int = Query(10, ge=1, le=50, description="返回数量"),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    获取详细薄弱点分析

    包括:
    - 薄弱知识点列表
    - 每个知识点的错误率
    - 相关题目
    - 改进建议
    """
    # 验证学科是否属于WZY模块
    if subject:
        validate_subject(subject)
        subjects = [subject]
    else:
        subjects = settings.SUBJECTS

    try:
        # 尝试调用学习建议Agent获取详细薄弱点分析
        try:
            advisor = LearningAdvisorAgent()
            weak_points = await advisor.get_detailed_weak_points(
                user_id=user_id,
                subjects=subjects,
                limit=limit,
            )
        except Exception as e:
            logger.warning(f"调用薄弱点分析Agent失败，使用备用方案: {str(e)}")
            weak_points = None

        # 如果没有分析结果，生成基本分析
        if not weak_points:
            weak_points = []

            # 获取用户的错题
            for subj in subjects:
                # 获取该学科的所有题目
                questions_query = select(crud_question.model).where(
                    crud_question.model.user_id == user_id,
                    crud_question.model.subject == subj
                )
                questions_result = await db.execute(questions_query)
                all_questions = questions_result.scalars().all()

                # 按知识点分组统计
                kp_stats = {}
                for q in all_questions:
                    if hasattr(q, 'knowledge_points') and q.knowledge_points:
                        for kp in q.knowledge_points:
                            if kp not in kp_stats:
                                kp_stats[kp] = {"total": 0, "correct": 0}
                            kp_stats[kp]["total"] += 1
                            if hasattr(q, 'is_correct') and q.is_correct:
                                kp_stats[kp]["correct"] += 1

                # 生成薄弱点分析
                for kp, stats in kp_stats.items():
                    if stats["total"] >= 3:  # 至少有3道题才统计
                        accuracy = stats["correct"] / stats["total"]
                        if accuracy < 0.6:  # 准确率低于60%视为薄弱点
                            # 获取相关知识点的错题
                            wrong_questions = [
                                q.id for q in all_questions
                                if hasattr(q, 'knowledge_points') and
                                kp in q.knowledge_points and
                                hasattr(q, 'is_correct') and
                                not q.is_correct
                            ]

                            # 获取学科特定的改进建议
                            subject_suggestions = await _get_subject_specific_suggestions(subj)

                            weak_points.append({
                                "knowledge_point": kp,
                                "subject": subj,
                                "total_questions": stats["total"],
                                "correct_count": stats["correct"],
                                "accuracy": accuracy,
                                "error_rate": 1 - accuracy,
                                "related_question_ids": wrong_questions[:5],
                                "improvement_suggestions": subject_suggestions,
                                "recommended_resources": [
                                    {"type": "article", "title": f"{kp}知识点总结", "url": "#"},
                                    {"type": "practice", "title": f"{kp}专项练习", "url": "#"}
                                ]
                            })

        return {
            "total": len(weak_points),
            "weak_points": weak_points[:limit],
            "subjects": subjects,
        }

    except Exception as e:
        logger.error(f"获取详细薄弱点失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"获取详细薄弱点失败: {str(e)}")
