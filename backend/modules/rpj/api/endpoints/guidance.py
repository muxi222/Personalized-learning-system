"""
学习指导API (RPJ模块 - 学生实现版本)

本文件为框架代码，需要学生完成核心业务逻辑的实现。
完整实现请参考: backend/modules/tony/api/endpoints/guidance.py

RPJ模块支持的学科: chinese, english, politics (语文, 英语, 道法)
"""

import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel, Field

from backend.core.db.session import get_db
from backend.core.crud import crud_question, crud_exam_correction
from backend.modules.rpj.api.deps import get_current_user_id
from backend.modules.rpj.config import settings
from backend.modules.rpj.agents.similar_question_agent import SimilarQuestionAgent

# NOTE(student/TODO):
# RPJ 模块的“学科路由 BaseAgent”与“LearningPlanAgent”由学生实现。
# 为避免模块启动时因缺失文件而崩溃，这里先用 None 占位，并在运行时走安全降级逻辑。
BaseAgent = None  # type: ignore
LearningPlanAgent = None  # type: ignore

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

# ============ Schemas ============

class SimilarQuestionRequest(BaseModel):
    """举一反三请求"""
    question_id: Optional[int] = Field(None, description="原题ID")
    correction_id: Optional[int] = Field(None, description="批改记录ID")
    subject: str = Field(..., description="学科")
    question_content: Optional[str] = Field(None, description="题目内容（当没有question_id时使用）")
    top_k: int = Field(5, ge=1, le=20, description="返回数量")

    def validate_input(self):
        """验证输入"""
        if not self.question_id and not self.correction_id and not self.question_content:
            raise HTTPException(
                status_code=400,
                detail="必须提供question_id、correction_id或question_content之一"
            )
        if self.question_id and self.correction_id:
            raise HTTPException(
                status_code=400,
                detail="只能提供question_id或correction_id之一，不能同时提供"
            )

        # 验证学科是否属于RPJ模块
        validate_subject(self.subject)

class SimilarQuestionItem(BaseModel):
    """相似题目项"""
    id: Optional[int] = None
    content: str
    subject: str
    difficulty: str
    correct_answer: Optional[str] = None
    knowledge_points: List[str] = []
    similarity_score: Optional[float] = None

class SimilarQuestionResponse(BaseModel):
    """举一反三响应"""
    original_question_id: Optional[int] = None
    original_correction_id: Optional[int] = None
    guidance_text: str = Field(..., description="引导文本")
    similar_questions: List[SimilarQuestionItem] = []

class LearningPlanRequest(BaseModel):
    """学习计划请求"""
    learning_goal: Optional[str] = Field(None, description="学习目标")
    focus_subjects: List[str] = Field(default_factory=list, description="重点学科")
    days: int = Field(7, ge=1, le=30, description="计划天数")

    def __init__(self, **data):
        super().__init__(**data)
        # 验证所有学科是否属于RPJ模块
        for subject in self.focus_subjects:
            validate_subject(subject)

class LearningPlanResponse(BaseModel):
    """学习计划响应"""
    plan_text: str
    plan_summary: Dict[str, str] = {}
    daily_schedule: List[Dict[str, str]] = []
    weak_knowledge_points: List[str] = []
    recommended_questions: List[int] = []

class StudentProfileResponse(BaseModel):
    """学生画像响应"""
    user_id: int
    grade: Optional[str] = None
    total_questions: int = 0
    total_corrections: int = 0
    weak_subjects: List[str] = []
    weak_knowledge_points: List[str] = []
    recent_errors_summary: Optional[str] = None
    mastery_overview: Dict[str, float] = {}
    learning_trend: Dict[str, List[float]] = {}

class KnowledgePointRequest(BaseModel):
    """知识点分析请求"""
    subject: str = Field(..., description="学科")
    knowledge_points: List[str] = Field(..., description="知识点列表")

    def __init__(self, **data):
        super().__init__(**data)
        validate_subject(self.subject)

class KnowledgePointResponse(BaseModel):
    """知识点分析响应"""
    subject: str
    knowledge_points_analysis: Dict[str, Dict[str, Any]] = {}
    recommended_resources: List[Dict[str, str]] = []
    learning_path: List[str] = []

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
        "politics": [
            "道德修养", "法律常识", "心理健康", "社会公德", "公民意识",
            "社会主义核心价值观", "传统文化", "时事政治", "法治观念", "国情教育"
        ]
    }
    return subject_knowledge_map.get(subject, [])

async def _get_subject_specific_guidance(subject: str) -> str:
    """获取学科特定引导文本"""
    guidance_map = {
        "chinese": "学习语文要注重积累，多读多写。建议：\n"
                  "1. 每天阅读30分钟优秀文章\n"
                  "2. 每周背诵1-2篇古诗文\n"
                  "3. 坚持写日记或周记\n"
                  "4. 注意积累好词好句\n"
                  "5. 多练习阅读理解题",
        "english": "学习英语要重视听说读写全面发展。建议：\n"
                  "1. 每天记忆10个新单词\n"
                  "2. 每天听15分钟英语音频\n"
                  "3. 每周练习2-3篇英语作文\n"
                  "4. 多读英语文章提高阅读能力\n"
                  "5. 尝试用英语进行简单对话",
        "politics": "学习道法要理论联系实际。建议：\n"
                   "1. 关注时事新闻和社会热点\n"
                   "2. 理解法律法规和道德规范\n"
                   "3. 参加社会实践活动\n"
                   "4. 学会用所学知识分析现实问题\n"
                   "5. 培养公民意识和社会责任感"
    }
    return guidance_map.get(subject, "请根据题目特点进行针对性练习。")

async def _get_student_profile(db: AsyncSession, user_id: int, subjects: List[str] = None) -> dict:
    """
    获取学生画像
    根据设计文档7.3节 - 长期记忆与个性化演进
    """
    from backend.core.db.models import Question, User, ExamCorrection

    if subjects is None:
        subjects = settings.SUBJECTS

    profile = {
        "user_id": user_id,
        "grade": None,
        "total_questions": 0,
        "total_corrections": 0,
        "weak_subjects": [],
        "weak_knowledge_points": [],
        "recent_errors_summary": None,
        "mastery_overview": {},
        "learning_trend": {},
    }

    try:
        # 获取用户信息
        user_result = await db.execute(
            select(User).where(User.id == user_id)
        )
        user = user_result.scalar_one_or_none()
        if user:
            profile["grade"] = user.grade

        # 统计题目数量（只统计指定学科的题目）
        count_result = await db.execute(
            select(func.count(Question.id)).where(
                Question.user_id == user_id,
                Question.subject.in_(subjects)
            )
        )
        profile["total_questions"] = count_result.scalar() or 0

        # 统计批改记录数量
        correction_result = await db.execute(
            select(func.count(ExamCorrection.id)).where(
                ExamCorrection.user_id == user_id,
                ExamCorrection.subject.in_(subjects)
            )
        )
        profile["total_corrections"] = correction_result.scalar() or 0

        # 分析各学科表现
        subject_stats = {}
        for subject in subjects:
            # 统计该学科的题目
            subject_questions_result = await db.execute(
                select(Question).where(
                    Question.user_id == user_id,
                    Question.subject == subject
                )
            )
            subject_questions = subject_questions_result.scalars().all()

            total = len(subject_questions)
            correct = sum(1 for q in subject_questions if hasattr(q, 'is_correct') and q.is_correct)

            if total > 0:
                accuracy = correct / total
                subject_stats[subject] = {
                    "total": total,
                    "correct": correct,
                    "accuracy": accuracy
                }

                # 如果准确率低于60%，视为薄弱学科
                if accuracy < 0.6:
                    profile["weak_subjects"].append(subject)

            # 计算掌握度
            if subject_questions:
                mastery_sum = 0
                count = 0
                for q in subject_questions:
                    if hasattr(q, 'mastery_level') and q.mastery_level is not None:
                        mastery_sum += q.mastery_level
                        count += 1
                if count > 0:
                    avg_mastery = mastery_sum / count
                    profile["mastery_overview"][subject] = round(avg_mastery, 2)

        # 分析薄弱知识点
        all_questions_result = await db.execute(
            select(Question).where(
                Question.user_id == user_id,
                Question.subject.in_(subjects)
            ).order_by(Question.created_at.desc()).limit(100)
        )
        recent_questions = all_questions_result.scalars().all()

        kp_count = {}
        kp_wrong = {}

        for question in recent_questions:
            if hasattr(question, 'knowledge_points') and question.knowledge_points:
                for kp in question.knowledge_points:
                    kp_count[kp] = kp_count.get(kp, 0) + 1
                    if hasattr(question, 'is_correct') and not question.is_correct:
                        kp_wrong[kp] = kp_wrong.get(kp, 0) + 1

        # 计算知识点错误率
        kp_error_rate = {}
        for kp, total in kp_count.items():
            wrong = kp_wrong.get(kp, 0)
            if total >= 3:  # 至少有3道题才统计
                error_rate = wrong / total
                kp_error_rate[kp] = error_rate

        # 取错误率最高的知识点
        sorted_kps = sorted(kp_error_rate.items(), key=lambda x: x[1], reverse=True)
        profile["weak_knowledge_points"] = [kp for kp, _ in sorted_kps[:10]]

        # 生成近期错误总结
        recent_wrong = [q for q in recent_questions if hasattr(q, 'is_correct') and not q.is_correct]
        if recent_wrong:
            wrong_subjects = list(set([q.subject for q in recent_wrong if hasattr(q, 'subject')]))
            profile["recent_errors_summary"] = (
                f"最近在{len(recent_wrong)}道题中出现错误，"
                f"涉及学科：{', '.join(wrong_subjects)}。"
            )

        # 计算学习趋势（近7天的正确率变化）
        seven_days_ago = datetime.utcnow() - timedelta(days=7)

        for subject in subjects:
            daily_accuracy = []

            for day in range(7):
                day_start = seven_days_ago + timedelta(days=day)
                day_end = day_start + timedelta(days=1)

                day_questions_result = await db.execute(
                    select(Question).where(
                        Question.user_id == user_id,
                        Question.subject == subject,
                        Question.created_at >= day_start,
                        Question.created_at < day_end
                    )
                )
                day_questions = day_questions_result.scalars().all()

                if day_questions:
                    day_correct = sum(1 for q in day_questions if hasattr(q, 'is_correct') and q.is_correct)
                    accuracy = day_correct / len(day_questions)
                    daily_accuracy.append(accuracy)
                else:
                    daily_accuracy.append(0)

            profile["learning_trend"][subject] = daily_accuracy

    except Exception as e:
        logger.error(f"构建学生画像失败: {e}")

    return profile

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
    # 验证输入
    request.validate_input()

    # 获取原题内容
    question_content = ""
    original_question_id = None
    original_correction_id = None

    if request.question_id:
        # 从问题表中获取题目
        question = await crud_question.get_question(db, request.question_id, user_id)
        if not question:
            raise HTTPException(status_code=404, detail="题目不存在")

        # 验证学科是否属于RPJ模块
        if question.subject not in settings.SUBJECTS:
            raise HTTPException(
                status_code=400,
                detail=f"题目学科'{question.subject}'不属于RPJ模块支持的范围"
            )

        question_content = question.content or ""
        original_question_id = request.question_id

    elif request.correction_id:
        # 从批改记录中获取题目
        correction = await crud_exam_correction.get_exam_correction(db, request.correction_id, user_id)
        if not correction:
            raise HTTPException(status_code=404, detail="批改记录不存在")

        # 验证学科是否属于RPJ模块
        if correction.subject.value not in settings.SUBJECTS:
            raise HTTPException(
                status_code=400,
                detail=f"批改记录学科'{correction.subject.value}'不属于RPJ模块支持的范围"
            )

        # 从批改记录中提取题目内容（假设有questions_detail字段）
        if hasattr(correction, 'questions_detail') and correction.questions_detail:
            # 取第一个题目作为示例
            question_content = correction.questions_detail[0].get("content", "") if correction.questions_detail else ""
        original_correction_id = request.correction_id

    else:
        # 使用提供的题目内容
        question_content = request.question_content or ""

    # 获取学生画像 (用于个性化)
    student_profile = await _get_student_profile(db, user_id, [request.subject])

    try:
        # 调用RPJ模块的举一反三Agent
        agent = SimilarQuestionAgent(request.subject)
        result = await agent.find_similar(
            question_content=question_content,
            subject=request.subject,
            user_id=user_id,
            top_k=request.top_k,
            student_profile=student_profile,
        )

        if not result:
            raise HTTPException(status_code=500, detail="无法获取相似题目")

        if result.get("error"):
            logger.error(f"Similar question agent error: {result['error']}")
            raise HTTPException(status_code=500, detail=result['error'])

    except Exception as e:
        logger.error(f"获取相似题目失败: {str(e)}")
        # 返回一个基本的响应
        guidance_text = await _get_subject_specific_guidance(request.subject)
        result = {
            "guidance_text": f"以下是一些相似题目，供你练习巩固：\n\n{guidance_text}",
            "similar_questions": []
        }

    # 格式化响应
    similar_questions = []
    for q in result.get("similar_questions", []):
        similar_questions.append(SimilarQuestionItem(
            id=q.get("id"),
            content=q.get("content", ""),
            subject=q.get("subject", request.subject),
            difficulty=q.get("difficulty", "medium"),
            correct_answer=q.get("correct_answer"),
            knowledge_points=q.get("knowledge_points", []),
            similarity_score=q.get("similarity_score"),
        ))

    return SimilarQuestionResponse(
        original_question_id=original_question_id,
        original_correction_id=original_correction_id,
        guidance_text=result.get("guidance_text", "以下是一些相似题目，供你练习巩固："),
        similar_questions=similar_questions,
    )

@router.post("/learning-plan", response_model=LearningPlanResponse)
async def get_learning_plan(
    request: LearningPlanRequest,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    获取个性化学习计划

    根据学生的错题历史和薄弱知识点，
    动态生成学习计划。

    对应设计文档7.3节 - 长期记忆与个性化
    """
    # 如果没有指定学科，则使用RPJ模块支持的所有学科
    focus_subjects = request.focus_subjects or settings.SUBJECTS

    # 获取学生画像
    profile = await _get_student_profile(db, user_id, focus_subjects)

    # 获取待复习题目
    review_questions = []
    for subject in focus_subjects:
        # 获取该学科的错题
        questions_result = await db.execute(
            select(crud_question.model).where(
                crud_question.model.user_id == user_id,
                crud_question.model.subject == subject,
                crud_question.model.is_correct == False
            ).order_by(func.random()).limit(3)
        )
        subject_questions = questions_result.scalars().all()
        review_questions.extend(subject_questions)

    try:
        # TODO(student): 实装 LearningPlanAgent（可参考 tony 模块实现风格）
        # 当前先走降级逻辑（避免缺失 agent 导致运行时报错/服务无法启动）
        if LearningPlanAgent is None:
            raise RuntimeError("TODO(student): LearningPlanAgent is not implemented in RPJ module yet")

        agent = LearningPlanAgent()
        result = await agent.generate_plan(
            user_id=user_id,
            student_profile=profile,
            learning_goal=request.learning_goal or f"提高{', '.join(focus_subjects)}成绩",
            days=request.days,
            focus_subjects=focus_subjects,
        )

        if not result:
            raise HTTPException(status_code=500, detail="无法生成学习计划")

        if result.get("error"):
            logger.error(f"Learning plan agent error: {result['error']}")
            raise HTTPException(status_code=500, detail=result['error'])

    except Exception as e:
        logger.error(f"生成学习计划失败: {str(e)}")
        # 返回一个基本的学习计划
        subject_plans = []
        for subject in focus_subjects:
            if subject == "chinese":
                subject_plans.append("语文：每天阅读30分钟，每周写一篇作文")
            elif subject == "english":
                subject_plans.append("英语：每天记忆10个单词，练习听力15分钟")
            elif subject == "politics":
                subject_plans.append("道法：关注时事新闻，学习法律法规")

        plan_text = f"根据你的学习情况，建议你在这{request.days}天内：\n"
        plan_text += "\n".join([f"{i+1}. {plan}" for i, plan in enumerate(subject_plans)])
        plan_text += f"\n\n每日学习时间建议：\n"
        plan_text += f"早上：记忆重点知识\n"
        plan_text += f"下午：完成练习题\n"
        plan_text += f"晚上：复习错题和总结"

        result = {
            "plan_text": plan_text,
            "plan_summary": {
                "total_days": str(request.days),
                "daily_time": "60分钟",
                "focus_subjects": ", ".join(focus_subjects)
            },
            "daily_schedule": [],
            "weak_knowledge_points": profile.get("weak_knowledge_points", []),
        }

    return LearningPlanResponse(
        plan_text=result.get("plan_text", ""),
        plan_summary=result.get("plan_summary", {}),
        daily_schedule=result.get("daily_schedule", []),
        weak_knowledge_points=profile.get("weak_knowledge_points", []),
        recommended_questions=[q.id for q in review_questions if hasattr(q, 'id')],
    )

@router.get("/student-profile", response_model=StudentProfileResponse)
async def get_student_profile_api(
    subject: Optional[str] = Query(None, description="学科筛选"),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    获取学生画像

    返回学生的学习统计、薄弱点分析等信息。
    用于个性化推荐和学习规划。

    对应设计文档7.3节
    """
    # 验证学科是否属于RPJ模块
    if subject:
        validate_subject(subject)
        focus_subjects = [subject]
    else:
        focus_subjects = settings.SUBJECTS

    profile = await _get_student_profile(db, user_id, focus_subjects)

    return StudentProfileResponse(
        user_id=user_id,
        grade=profile.get("grade"),
        total_questions=profile.get("total_questions", 0),
        total_corrections=profile.get("total_corrections", 0),
        weak_subjects=profile.get("weak_subjects", []),
        weak_knowledge_points=profile.get("weak_knowledge_points", []),
        recent_errors_summary=profile.get("recent_errors_summary"),
        mastery_overview=profile.get("mastery_overview", {}),
        learning_trend=profile.get("learning_trend", {}),
    )

@router.post("/knowledge-points", response_model=KnowledgePointResponse)
async def analyze_knowledge_points(
    request: KnowledgePointRequest,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    知识点深度分析

    分析学生在特定知识点上的掌握情况，
    提供学习资源和学习路径建议。
    """
    # 获取学生在这些知识点上的表现
    knowledge_points_analysis = {}

    for kp in request.knowledge_points:
        # 查询相关题目
        kp_questions = await crud_question.get_questions_by_knowledge_point(
            db, user_id, request.subject, kp
        )

        # 计算掌握情况
        total = len(kp_questions)
        correct = sum(1 for q in kp_questions if hasattr(q, 'is_correct') and q.is_correct) if kp_questions else 0
        mastery_rate = correct / total if total > 0 else 0

        # 获取常见错误类型
        common_errors = []
        if kp_questions:
            # 根据学科和知识点提供特定的错误分析
            if request.subject == "chinese":
                common_errors = ["理解偏差", "表达不准确", "知识点混淆"]
            elif request.subject == "english":
                common_errors = ["语法错误", "词汇用法不当", "理解错误"]
            elif request.subject == "politics":
                common_errors = ["概念理解不清", "案例分析不透彻", "时事联系不足"]

        knowledge_points_analysis[kp] = {
            "total_questions": total,
            "correct_count": correct,
            "mastery_rate": mastery_rate,
            "common_errors": common_errors[:2],  # 只取前2个
            "recommended_practice_count": max(10 - total, 3)  # 建议练习数量
        }

    try:
        # TODO(student): 实装 RPJ BaseAgent 学科路由 + get_learning_resources
        # 当前走降级逻辑：由下方默认资源/路径兜底
        resources = []
        learning_path = []
    except Exception as e:
        logger.error(f"获取学习资源失败: {str(e)}")
        resources = []
        learning_path = []

    # 如果没有资源，提供默认资源
    if not resources:
        for kp in request.knowledge_points:
            resources.append({
                "type": "article",
                "title": f"{kp}知识点总结",
                "description": f"{kp}相关知识点的详细讲解",
                "url": "#"
            })
            resources.append({
                "type": "practice",
                "title": f"{kp}专项练习",
                "description": f"针对{kp}的练习题",
                "url": "#"
            })

    # 如果没有学习路径，提供默认路径
    if not learning_path:
        learning_path = [
            "复习相关基础知识",
            "学习典型例题",
            "完成专项练习",
            "总结易错点",
            "进行自我测试"
        ]

    return KnowledgePointResponse(
        subject=request.subject,
        knowledge_points_analysis=knowledge_points_analysis,
        recommended_resources=resources[:5],  # 最多返回5个资源
        learning_path=learning_path,
    )

@router.get("/weak-points")
async def get_weak_points(
    subject: Optional[str] = Query(None, description="学科筛选"),
    limit: int = Query(10, ge=1, le=50, description="返回数量"),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    获取薄弱知识点列表

    根据错误率统计学生的薄弱知识点
    """
    # 验证学科是否属于RPJ模块
    if subject:
        validate_subject(subject)
        subjects = [subject]
    else:
        subjects = settings.SUBJECTS

    weak_points = []

    for subj in subjects:
        # 获取该学科的所有题目
        questions_result = await db.execute(
            select(crud_question.model).where(
                crud_question.model.user_id == user_id,
                crud_question.model.subject == subj
            )
        )
        questions = questions_result.scalars().all()

        # 统计知识点错误率
        kp_stats = {}
        for question in questions:
            if hasattr(question, 'knowledge_points') and question.knowledge_points:
                for kp in question.knowledge_points:
                    if kp not in kp_stats:
                        kp_stats[kp] = {"total": 0, "wrong": 0}
                    kp_stats[kp]["total"] += 1
                    if hasattr(question, 'is_correct') and not question.is_correct:
                        kp_stats[kp]["wrong"] += 1

        # 计算错误率并排序
        for kp, stats in kp_stats.items():
            if stats["total"] >= 3:  # 至少有3道题才统计
                error_rate = stats["wrong"] / stats["total"]

                # 根据学科提供改进建议
                if subj == "chinese":
                    suggestions = ["多阅读相关文章", "积累好词好句", "练习写作"]
                elif subj == "english":
                    suggestions = ["记忆相关词汇", "练习语法", "加强听说训练"]
                elif subj == "politics":
                    suggestions = ["关注时事新闻", "学习相关法律法规", "分析案例"]
                else:
                    suggestions = ["加强练习", "复习相关知识点", "寻求老师帮助"]

                weak_points.append({
                    "subject": subj,
                    "knowledge_point": kp,
                    "total_questions": stats["total"],
                    "wrong_count": stats["wrong"],
                    "error_rate": round(error_rate, 2),
                    "priority": "高" if error_rate > 0.7 else "中" if error_rate > 0.4 else "低",
                    "suggestions": suggestions
                })

    # 按错误率排序
    weak_points.sort(key=lambda x: x["error_rate"], reverse=True)

    return {
        "total": len(weak_points),
        "weak_points": weak_points[:limit]
    }

@router.get("/study-guide")
async def get_study_guide(
    subject: str = Query(..., description="学科"),
    knowledge_point: Optional[str] = Query(None, description="知识点"),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    获取学习指导

    提供学科或知识点的学习指导
    """
    validate_subject(subject)

    # 获取学科学习指南
    study_guides = {
        "chinese": {
            "title": "语文学习指南",
            "description": "语文学习需要长期积累和系统训练",
            "key_points": [
                "注重基础知识积累：字词句的掌握是语文学习的基础",
                "加强阅读理解：多读经典文章，学习阅读技巧",
                "提高写作能力：勤于练笔，学习写作方法",
                "重视文言文：理解文言实词虚词，掌握特殊句式",
                "培养文学素养：欣赏优秀文学作品，提高审美能力"
            ],
            "daily_practice": [
                "每天阅读30分钟优秀文章",
                "每周背诵1-2篇古诗文",
                "每天练习5道基础知识题",
                "每周写一篇作文或随笔",
                "每月阅读一本课外书"
            ]
        },
        "english": {
            "title": "英语学习指南",
            "description": "英语学习需要听说读写全面发展",
            "key_points": [
                "扩大词汇量：每天记忆新单词，复习旧单词",
                "掌握语法规则：系统学习英语语法知识",
                "提高听力能力：多听英语材料，培养语感",
                "加强口语表达：大胆开口说英语，练习发音",
                "提升写作水平：学习英语写作技巧，多写多练"
            ],
            "daily_practice": [
                "每天记忆10个新单词",
                "每天听15分钟英语音频",
                "每天朗读英语课文10分钟",
                "每周完成2-3篇阅读练习",
                "每周写一篇英语作文"
            ]
        },
        "politics": {
            "title": "道法学习指南",
            "description": "道法学习需要理论联系实际",
            "key_points": [
                "理解基本概念：掌握道德、法律等基本概念",
                "关注时事政治：了解国内外大事，理论联系实际",
                "学习法律法规：掌握基本的法律知识和法规",
                "培养公民意识：增强社会责任感和公民意识",
                "提高分析能力：学会用所学知识分析现实问题"
            ],
            "daily_practice": [
                "每天阅读新闻10分钟",
                "每周学习一个法律案例",
                "每月参加一次社会实践活动",
                "定期复习重要概念和理论",
                "关注社会热点问题并进行思考"
            ]
        }
    }

    guide = study_guides.get(subject, {})

    # 如果指定了知识点，添加知识点特定指导
    if knowledge_point:
        guide["knowledge_point_guide"] = {
            "point": knowledge_point,
            "learning_strategies": [
                "理解基本概念和定义",
                "学习相关例题和案例",
                "完成针对性练习",
                "总结易错点和注意事项",
                "进行拓展学习和思考"
            ]
        }

    return guide

@router.get("/progress-analysis")
async def get_progress_analysis(
    subject: Optional[str] = Query(None, description="学科"),
    days: int = Query(7, ge=1, le=90, description="分析天数"),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    获取学习进度分析

    分析学生的学习进度和变化趋势
    """
    # 验证学科是否属于RPJ模块
    if subject:
        validate_subject(subject)
        subjects = [subject]
    else:
        subjects = settings.SUBJECTS

    analysis_results = {}

    end_date = datetime.utcnow()
    start_date = end_date - timedelta(days=days)

    for subj in subjects:
        # 获取该学科在这段时间内的题目
        questions_result = await db.execute(
            select(crud_question.model).where(
                crud_question.model.user_id == user_id,
                crud_question.model.subject == subj,
                crud_question.model.created_at >= start_date,
                crud_question.model.created_at <= end_date
            ).order_by(crud_question.model.created_at)
        )
        questions = questions_result.scalars().all()

        # 分析进度
        total = len(questions)
        correct = sum(1 for q in questions if hasattr(q, 'is_correct') and q.is_correct)
        accuracy = correct / total if total > 0 else 0

        # 按时间段分析
        weekly_accuracy = []
        for week in range(0, days, 7):
            week_start = start_date + timedelta(days=week)
            week_end = week_start + timedelta(days=7) if week + 7 <= days else end_date

            week_questions = [q for q in questions if week_start <= q.created_at <= week_end]
            week_total = len(week_questions)
            week_correct = sum(1 for q in week_questions if hasattr(q, 'is_correct') and q.is_correct)
            week_accuracy = week_correct / week_total if week_total > 0 else 0

            weekly_accuracy.append({
                "week": week // 7 + 1,
                "start_date": week_start.date().isoformat(),
                "end_date": week_end.date().isoformat(),
                "total_questions": week_total,
                "accuracy": round(week_accuracy, 2)
            })

        # 生成分析报告
        progress_rate = 0
        if len(weekly_accuracy) > 1:
            progress_rate = weekly_accuracy[-1]["accuracy"] - weekly_accuracy[0]["accuracy"]

        analysis_results[subj] = {
            "period": f"{start_date.date()} 至 {end_date.date()}",
            "total_questions": total,
            "total_correct": correct,
            "overall_accuracy": round(accuracy, 2),
            "weekly_accuracy": weekly_accuracy,
            "progress_rate": round(progress_rate, 2),
            "progress_evaluation": "进步明显" if progress_rate > 0.1 else "稳步提升" if progress_rate > 0 else "需要加强"
        }

    return {
        "user_id": user_id,
        "analysis_period": days,
        "subjects": subjects,
        "results": analysis_results
    }
