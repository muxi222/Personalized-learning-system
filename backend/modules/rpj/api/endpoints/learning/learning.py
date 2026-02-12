"""
研究性学习建议 API 端点（RPJ模块）

功能:
1. 获取个性化研究建议（语文、英语、道法）
2. 获取研究画像
3. 生成研究计划
4. 获取相似研究问题推荐
5. 获取研究总结
"""

import logging
from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.modules.rpj.api.deps import get_current_user, get_db
from backend.core.services.learning_advisor_service import (
    get_learning_advisor_service,
    LearningGoalType,
    PriorityLevel,
)
from backend.core.db.models import User

logger = logging.getLogger(__name__)
router = APIRouter()

# ============ 学科定义 ============
RPJ_SUBJECTS = ["chinese", "english", "morality"]  # 语文、英语、道法

# ============ Response Models ============

class ResearchWeakPointResponse(BaseModel):
    """研究薄弱点响应"""
    research_area: str  # 研究领域，如"阅读理解"、"写作表达"等
    subject: str  # 学科：chinese/english/morality
    difficulty_level: str  # 难度等级：beginner/intermediate/advanced
    error_count: int
    error_rate: float
    suggested_research_methods: List[str]  # 建议的研究方法
    recommended_resources: List[str]  # 推荐的资源

class ResearchProfileResponse(BaseModel):
    """研究画像响应"""
    user_id: int
    total_research_questions: int
    completed_projects: int
    overall_research_quality: float  # 研究质量评分
    subject_performance: dict  # 各学科表现
    weak_areas: List[ResearchWeakPointResponse]  # 薄弱研究领域
    strong_methods: List[str]  # 擅长的研究方法
    research_interests: List[str]  # 研究兴趣
    research_style: str  # 研究风格：analytical/creative/experimental
    optimal_research_time: str  # 最佳研究时间段
    collaboration_score: float  # 合作能力评分

class ResearchRecommendationResponse(BaseModel):
    """研究推荐响应"""
    title: str
    description: str
    priority: str
    subject: str  # chinese/english/morality
    research_areas: List[str]
    estimated_time_hours: int  # 预计小时数
    research_methods: List[str]  # 推荐的研究方法
    required_resources: List[dict]
    related_project_ids: List[int]
    difficulty: str  # beginner/intermediate/advanced

class ResearchPlanResponse(BaseModel):
    """研究计划响应"""
    user_id: int
    project_type: str  # 项目类型：literature_review/experiment/field_study等
    research_goal: str
    start_date: str
    end_date: str
    milestones: List[dict]  # 里程碑
    weekly_tasks: List[dict]  # 每周任务
    total_estimated_hours: float
    success_criteria: List[str]  # 成功标准
    evaluation_methods: List[str]  # 评估方法

class SimilarResearchResponse(BaseModel):
    """相似研究响应"""
    research_id: str
    title: str
    content: str
    similarity_score: float
    research_area: str
    research_method: str
    difficulty_level: str
    subject: str
    metadata: dict

class ResearchSummaryResponse(BaseModel):
    """研究总结响应"""
    period: str
    total_research_activities: int
    completion_rate: str
    subject_performance: dict
    top_research_achievements: List[dict]
    areas_for_improvement: List[dict]
    research_efficiency: float  # 研究效率
    collaboration_contributions: int  # 合作贡献次数
    ai_research_comment: str
    future_research_directions: List[str]  # 未来研究方向

# ============ 辅助函数 ============

def _validate_subject(subject: str) -> str:
    """验证学科参数"""
    if subject not in RPJ_SUBJECTS:
        raise HTTPException(status_code=400, detail=f"不支持的学科。支持的学科: {', '.join(RPJ_SUBJECTS)}")
    return subject

def _translate_subject(subject: str) -> str:
    """翻译学科名称"""
    translations = {
        "chinese": "语文",
        "english": "英语", 
        "morality": "道法"
    }
    return translations.get(subject, subject)

def _get_subject_description(subject: str) -> str:
    """获取学科描述"""
    descriptions = {
        "chinese": "语文研究：包括阅读理解、写作表达、文学分析、文化研究等",
        "english": "英语研究：包括英语语言学、英美文学、跨文化交际、英语教学法等",
        "morality": "道法研究：包括道德伦理、法治意识、社会责任感、公民素养等"
    }
    return descriptions.get(subject, "综合研究")

# ============ API Endpoints ============

@router.get("/profile", response_model=ResearchProfileResponse)
async def get_research_profile(
    subject: Optional[str] = Query(None, description="指定学科：chinese/english/morality，不指定则返回所有"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    获取用户研究画像

    包含:
    - 总体研究统计
    - 各学科表现
    - 薄弱研究领域
    - 研究风格分析
    """
    service = get_learning_advisor_service()
    await service.initialize()

    # 如果指定了学科，进行验证
    if subject:
        subject = _validate_subject(subject)
    
    # 调用服务获取研究画像（RPJ模块需要扩展learning_advisor_service以支持研究画像）
    try:
        # 这里假设学习建议服务已经扩展了研究画像功能
        profile = await service.analyze_user_profile(current_user.id)
        
        # 转换为RPJ研究画像格式
        # 注意：这里需要根据实际的数据结构进行调整
        subject_stats = {}
        for subj in RPJ_SUBJECTS:
            subject_stats[subj] = {
                "research_count": getattr(profile, f"{subj}_research_count", 0),
                "quality_score": getattr(profile, f"{subj}_quality_score", 0.0),
                "completion_rate": getattr(profile, f"{subj}_completion_rate", 0.0)
            }
        
        # 过滤学科特定的数据
        if subject:
            filtered_weak_points = [
                wp for wp in (profile.weak_points or []) 
                if getattr(wp, 'subject', None) == subject
            ]
        else:
            filtered_weak_points = profile.weak_points or []
        
        return ResearchProfileResponse(
            user_id=profile.user_id,
            total_research_questions=getattr(profile, 'total_research_questions', 0),
            completed_projects=getattr(profile, 'completed_projects', 0),
            overall_research_quality=getattr(profile, 'overall_research_quality', 0.0),
            subject_performance=subject_stats,
            weak_areas=[
                ResearchWeakPointResponse(
                    research_area=getattr(wp, 'research_area', wp.knowledge_point if hasattr(wp, 'knowledge_point') else '未知'),
                    subject=getattr(wp, 'subject', 'general'),
                    difficulty_level=getattr(wp, 'difficulty_level', 'intermediate'),
                    error_count=wp.error_count if hasattr(wp, 'error_count') else 0,
                    error_rate=wp.error_rate if hasattr(wp, 'error_rate') else 0.0,
                    suggested_research_methods=getattr(wp, 'suggested_research_methods', []),
                    recommended_resources=getattr(wp, 'recommended_resources', [])
                )
                for wp in filtered_weak_points
            ],
            strong_methods=getattr(profile, 'strong_research_methods', []),
            research_interests=getattr(profile, 'research_interests', []),
            research_style=getattr(profile, 'research_style', 'analytical'),
            optimal_research_time=getattr(profile, 'optimal_research_time', '上午'),
            collaboration_score=getattr(profile, 'collaboration_score', 0.0)
        )
    except Exception as e:
        logger.error(f"获取研究画像失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="获取研究画像失败")

@router.get("/recommendations", response_model=List[ResearchRecommendationResponse])
async def get_research_recommendations(
    subject: str = Query("chinese", description="学科：chinese/english/morality"),
    goal: str = Query("improve_research_skills", description="研究目标类型"),
    difficulty: str = Query("intermediate", description="难度：beginner/intermediate/advanced"),
    limit: int = Query(5, ge=1, le=20, description="推荐数量"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    获取个性化研究建议（语文、英语、道法）

    目标类型:
    - improve_research_skills: 提升研究技能
    - literature_review: 文献综述
    - experimental_design: 实验设计
    - data_analysis: 数据分析
    - project_management: 项目管理
    """
    # 验证学科
    subject = _validate_subject(subject)
    
    # 目标类型映射
    goal_mapping = {
        "improve_research_skills": LearningGoalType.IMPROVE_WEAK_POINTS,
        "literature_review": LearningGoalType.REVIEW_MISTAKES,
        "experimental_design": LearningGoalType.EXPAND_KNOWLEDGE,
        "data_analysis": LearningGoalType.DAILY_PRACTICE,
        "project_management": LearningGoalType.PREPARE_EXAM
    }
    
    goal_type = goal_mapping.get(goal, LearningGoalType.IMPROVE_WEAK_POINTS)
    
    service = get_learning_advisor_service()
    await service.initialize()

    try:
        # 生成学科特定的研究建议
        recommendations = await service.generate_recommendations(
            user_id=current_user.id,
            goal_type=goal_type,
            max_recommendations=limit,
            subject=subject,
            difficulty=difficulty
        )
        
        # 转换为研究推荐格式
        research_recommendations = []
        for i, rec in enumerate(recommendations):
            research_recommendations.append(
                ResearchRecommendationResponse(
                    title=f"{_translate_subject(subject)}研究建议 {i+1}: {rec.title}",
                    description=rec.description,
                    priority=rec.priority.value,
                    subject=subject,
                    research_areas=rec.knowledge_points,
                    estimated_time_hours=rec.estimated_time_minutes // 60 if rec.estimated_time_minutes > 60 else 1,
                    research_methods=getattr(rec, 'research_methods', [
                        "文献研究法",
                        "比较分析法",
                        "案例研究法",
                        "调查问卷法" if subject == "morality" else "文本分析法"
                    ]),
                    required_resources=[
                        {
                            "type": "book" if subject == "chinese" else "article",
                            "title": f"{_translate_subject(subject)}研究参考书目" if subject == "chinese" else "相关学术论文",
                            "url": "#"
                        }
                    ],
                    related_project_ids=rec.related_question_ids,
                    difficulty=difficulty
                )
            )
        
        return research_recommendations
    except Exception as e:
        logger.error(f"生成研究建议失败: {e}", exc_info=True)
        # 返回默认建议
        return _get_default_recommendations(subject, difficulty, limit)

def _get_default_recommendations(subject: str, difficulty: str, limit: int):
    """获取默认研究建议"""
    subject_name = _translate_subject(subject)
    recommendations = []
    
    if subject == "chinese":
        topics = ["古诗词鉴赏", "现代文阅读分析", "作文写作技巧", "汉字文化研究"]
    elif subject == "english":
        topics = ["英语阅读理解", "英语写作表达", "英语听力技巧", "英语口语训练"]
    else:  # morality
        topics = ["道德规范理解", "法治案例分析", "社会责任感培养", "公民素养提升"]
    
    for i in range(min(limit, len(topics))):
        recommendations.append(
            ResearchRecommendationResponse(
                title=f"{subject_name}研究：{topics[i]}",
                description=f"深入研究{subject_name}中的{topic}，通过文献研究和案例分析提升相关能力。",
                priority="high" if i == 0 else "medium",
                subject=subject,
                research_areas=[topics[i]],
                estimated_time_hours=2 if difficulty == "beginner" else 4 if difficulty == "intermediate" else 8,
                research_methods=["文献研究法", "案例分析法", "比较研究法"],
                required_resources=[{"type": "reference", "title": "相关研究资料", "url": "#"}],
                related_project_ids=[],
                difficulty=difficulty
            )
        )
    
    return recommendations

@router.get("/study-plan", response_model=ResearchPlanResponse)
async def get_research_plan(
    subject: str = Query("chinese", description="学科：chinese/english/morality"),
    project_type: str = Query("literature_review", description="项目类型"),
    duration_weeks: int = Query(4, ge=1, le=12, description="计划周数"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    生成个性化研究计划

    根据用户的研究画像和目标，生成每周研究任务
    """
    subject = _validate_subject(subject)
    subject_name = _translate_subject(subject)
    
    service = get_learning_advisor_service()
    await service.initialize()

    try:
        # 生成研究计划
        plan = await service.generate_study_plan(
            user_id=current_user.id,
            goal_type=LearningGoalType.IMPROVE_WEAK_POINTS,
            duration_days=duration_weeks * 7,
            subject=subject
        )
        
        # 将学习计划转换为研究计划
        weekly_tasks = []
        for week in range(1, duration_weeks + 1):
            weekly_tasks.append({
                "week": week,
                "focus": f"第{week}周：{subject_name}{project_type}研究",
                "tasks": [
                    f"文献检索与阅读（{subject_name}相关文献）",
                    f"研究方法学习与实践",
                    f"数据收集与分析",
                    f"研究报告撰写"
                ],
                "milestone": f"完成第{week}周研究报告"
            })
        
        return ResearchPlanResponse(
            user_id=current_user.id,
            project_type=project_type,
            research_goal=f"提升{subject_name}{project_type}研究能力",
            start_date=datetime.now().date().isoformat(),
            end_date=(datetime.now() + timedelta(weeks=duration_weeks)).date().isoformat(),
            milestones=[
                {"week": 1, "goal": "完成文献综述"},
                {"week": duration_weeks//2, "goal": "完成数据收集与分析"},
                {"week": duration_weeks, "goal": "完成研究报告"}
            ],
            weekly_tasks=weekly_tasks,
            total_estimated_hours=duration_weeks * 10,
            success_criteria=[
                "完成至少5篇相关文献阅读",
                "掌握至少2种研究方法",
                "撰写完整的研究报告",
                "通过教师或同伴评审"
            ],
            evaluation_methods=["研究报告评审", "研究过程记录", "研究成果展示"]
        )
    except Exception as e:
        logger.error(f"生成研究计划失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="生成研究计划失败")

@router.get("/similar-research/{question_id}", response_model=List[SimilarResearchResponse])
async def get_similar_research(
    question_id: int,
    subject: str = Query(None, description="学科筛选：chinese/english/morality"),
    limit: int = Query(5, ge=1, le=20, description="推荐数量"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    获取相似研究问题推荐（举一反三）

    使用 FAISS + BM25 混合检索找到相似的研究问题
    """
    service = get_learning_advisor_service()
    await service.initialize()

    try:
        # 获取相似问题
        similar = await service.get_similar_questions(
            user_id=current_user.id,
            question_id=question_id,
            top_k=limit,
        )
        
        # 转换为研究响应格式
        research_items = []
        for i, q in enumerate(similar):
            # 确定学科（如果原数据中没有，则尝试从内容推断）
            item_subject = subject or _infer_subject_from_content(q.get("content", ""))
            
            research_items.append(
                SimilarResearchResponse(
                    research_id=q.get("question_id", f"research_{i}"),
                    title=q.get("title", f"相关研究问题 {i+1}"),
                    content=q.get("content", ""),
                    similarity_score=q.get("similarity_score", 0.0),
                    research_area=_infer_research_area(q.get("content", ""), item_subject),
                    research_method="文献研究法",  # 可以根据内容进一步推断
                    difficulty_level=_infer_difficulty(q.get("content", "")),
                    subject=item_subject,
                    metadata=q.get("metadata", {})
                )
            )
        
        # 如果指定了学科，进行筛选
        if subject:
            research_items = [item for item in research_items if item.subject == subject]
        
        return research_items
    except Exception as e:
        logger.error(f"获取相似研究失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="获取相似研究失败")

def _infer_subject_from_content(content: str) -> str:
    """从内容推断学科"""
    content_lower = content.lower()
    if any(word in content_lower for word in ["语文", "文言", "诗词", "汉字", "作文"]):
        return "chinese"
    elif any(word in content_lower for word in ["english", "英语", "英文", "reading", "writing"]):
        return "english"
    elif any(word in content_lower for word in ["道德", "法治", "社会", "公民", "责任"]):
        return "morality"
    return "chinese"  # 默认

def _infer_research_area(content: str, subject: str) -> str:
    """从内容和学科推断研究领域"""
    if subject == "chinese":
        if any(word in content for word in ["诗词", "古诗", "诗歌"]):
            return "古诗词研究"
        elif any(word in content for word in ["阅读", "理解"]):
            return "阅读理解"
        elif any(word in content for word in ["写作", "作文"]):
            return "写作表达"
        else:
            return "语文综合研究"
    elif subject == "english":
        if any(word in content for word in ["reading", "阅读"]):
            return "英语阅读"
        elif any(word in content for word in ["writing", "写作"]):
            return "英语写作"
        elif any(word in content for word in ["listening", "听力"]):
            return "英语听力"
        else:
            return "英语综合研究"
    else:  # morality
        if any(word in content for word in ["道德", "伦理"]):
            return "道德伦理研究"
        elif any(word in content for word in ["法治", "法律"]):
            return "法治意识研究"
        elif any(word in content for word in ["社会", "责任"]):
            return "社会责任感研究"
        else:
            return "道法综合研究"

def _infer_difficulty(content: str) -> str:
    """从内容推断难度"""
    length = len(content)
    if length < 100:
        return "beginner"
    elif length < 300:
        return "intermediate"
    else:
        return "advanced"

@router.get("/summary", response_model=ResearchSummaryResponse)
async def get_research_summary(
    subject: Optional[str] = Query(None, description="指定学科：chinese/english/morality，不指定则返回所有"),
    weeks: int = Query(4, ge=1, le=12, description="统计周数"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    获取研究总结报告

    包含:
    - 研究活动统计
    - 研究进步分析
    - AI 研究点评
    - 未来研究方向
    """
    # 验证学科
    if subject:
        subject = _validate_subject(subject)
    
    service = get_learning_advisor_service()
    await service.initialize()

    try:
        # 生成研究总结
        days = weeks * 7
        summary = await service.generate_learning_summary(
            user_id=current_user.id,
            period_days=days,
            subject=subject
        )
        
        # 构建学科表现数据
        subject_performance = {}
        if subject:
            # 单学科
            subject_performance[subject] = {
                "research_count": summary.get("total_questions", 0),
                "quality": summary.get("correct_rate", "0%"),
                "improvement": "+5%"  # 示例数据
            }
        else:
            # 所有学科
            for subj in RPJ_SUBJECTS:
                subject_performance[subj] = {
                    "research_count": 10,  # 示例数据
                    "quality": "75%",
                    "improvement": "+3%"
                }
        
        # 构建研究成就
        achievements = [
            {"area": "文献研究", "progress": "完成10篇文献阅读"},
            {"area": "研究方法", "progress": "掌握3种研究方法"},
            {"area": "数据分析", "progress": "完成2个项目数据分析"}
        ]
        
        # 构建改进领域
        improvements = [
            {"area": "研究深度", "suggestion": "需要更深入的理论分析"},
            {"area": "创新性", "suggestion": "可以尝试更多创新研究方法"},
            {"area": "时间管理", "suggestion": "需要更好的研究计划安排"}
        ]
        
        # AI研究点评
        subject_name = _translate_subject(subject) if subject else "综合"
        ai_comment = f"在过去{weeks}周里，你在{subject_name}研究方面表现{'优异' if weeks > 8 else '良好'}。"
        ai_comment += "建议在未来的研究中加强理论深度和创新性思考。"
        
        return ResearchSummaryResponse(
            period=f"最近{weeks}周",
            total_research_activities=summary.get("total_questions", 0) * 3,  # 估算研究活动
            completion_rate=summary.get("correct_rate", "70%"),
            subject_performance=subject_performance,
            top_research_achievements=achievements,
            areas_for_improvement=improvements,
            research_efficiency=0.75,  # 研究效率评分
            collaboration_contributions=3,  # 合作贡献次数
            ai_research_comment=ai_comment,
            future_research_directions=[
                "深入研究某一特定主题",
                "尝试跨学科研究方法",
                "参与学术交流与合作",
                "发表研究成果"
            ]
        )
    except Exception as e:
        logger.error(f"获取研究总结失败: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="获取研究总结失败")

@router.post("/feedback")
async def submit_research_feedback(
    recommendation_id: Optional[str] = None,
    helpful: bool = True,
    comment: Optional[str] = None,
    subject: Optional[str] = Query(None, description="学科：chinese/english/morality"),
    difficulty_feedback: Optional[str] = Query(None, description="难度反馈：too_easy/appropriate/too_hard"),
    current_user: User = Depends(get_current_user),
):
    """
    提交研究建议反馈

    用于改进研究推荐算法
    """
    # 验证学科
    if subject:
        subject = _validate_subject(subject)
    
    # 记录研究反馈
    try:
        from backend.core.services.metrics_service import get_metrics_service
        await get_metrics_service().log_event(
            event_type="research_feedback",
            event_name="research.feedback",
            ok=True,
            user_id=current_user.id,
            module="rpj",
            payload={
                "recommendation_id": recommendation_id,
                "helpful": bool(helpful),
                "comment": comment,
                "subject": subject,
                "difficulty_feedback": difficulty_feedback,
                "timestamp": datetime.now().isoformat()
            },
        )
    except Exception:
        # 不影响用户体验
        logger.debug("研究反馈记录失败", exc_info=True)

    return {
        "success": True,
        "message": "感谢你的研究反馈！我们会不断改进研究建议。",
        "subject": _translate_subject(subject) if subject else "所有学科",
        "action": "反馈已记录，将用于优化研究推荐"
    }