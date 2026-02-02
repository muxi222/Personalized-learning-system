 """
RPJ模块API端点 - 针对语文、英语、道法的阅读理解与解答
RPJ (Reading Comprehension & Answer Justification) Module
对应设计文档6.1节 - RPJ模块实现
"""

import logging
import time
from typing import Optional, List, Dict, Any
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field, validator

from backend.core.db.session import get_db
from backend.core.crud import crud_rpj_question  # 新的RPJ题目CRUD
from backend.modules.tony.api.deps import get_current_user_id

logger = logging.getLogger(__name__)

router = APIRouter()

# ============ Enums ============

class RPJSubject(str, Enum):
    """RPJ支持的学科"""
    CHINESE = "chinese"
    ENGLISH = "english"
    MORALITY = "morality"  # 道法

class QuestionType(str, Enum):
    """RPJ题型"""
    READING_COMPREHENSION = "reading_comprehension"  # 阅读理解
    CLOZE_TEST = "cloze_test"  # 完形填空
    WRITING = "writing"  # 写作
    SHORT_ANSWER = "short_answer"  # 简答/论述
    MULTIPLE_CHOICE = "multiple_choice"  # 选择题

class DifficultyLevel(str, Enum):
    """难度级别"""
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"

# ============ Schemas ============

class RPJQuestionRequest(BaseModel):
    """RPJ题目请求基类"""
    content: str = Field(..., description="题目内容或文章")
    subject: RPJSubject = Field(..., description="学科")
    question_type: QuestionType = Field(..., description="题型")
    difficulty: DifficultyLevel = Field(DifficultyLevel.MEDIUM, description="难度")
    knowledge_points: List[str] = Field(default_factory=list, description="知识点")
    options: Optional[List[str]] = Field(None, description="选择题选项")
    standard_answer: Optional[str] = Field(None, description="参考答案")
    
    @validator('options')
    def validate_options(cls, v, values):
        if values.get('question_type') == QuestionType.MULTIPLE_CHOICE and (not v or len(v) < 2):
            raise ValueError('选择题必须提供至少2个选项')
        return v

class RPJAnswerRequest(BaseModel):
    """学生答案提交"""
    question_id: int = Field(..., description="题目ID")
    student_answer: str = Field(..., description="学生答案")
    confidence_level: float = Field(0.5, ge=0.0, le=1.0, description="自信度")
    time_spent: Optional[int] = Field(None, description="答题耗时(秒)")

class RPJAnswerFeedback(BaseModel):
    """答案反馈"""
    score: float = Field(..., ge=0.0, le=100.0, description="得分")
    correctness: str = Field(..., description="正确性评价")
    detailed_feedback: str = Field(..., description="详细反馈")
    improvement_suggestions: List[str] = Field(default_factory=list, description="改进建议")
    model_analysis: str = Field(..., description="AI分析过程")
    
    # 各学科特有反馈
    language_points: Optional[List[str]] = Field(None, description="语文-语言点")
    grammar_errors: Optional[List[str]] = Field(None, description="英语-语法错误")
    moral_lessons: Optional[List[str]] = Field(None, description="道法-道德启示")

class RPJSimilarQuestionRequest(BaseModel):
    """RPJ相似题目请求"""
    question_id: int = Field(..., description="原题ID")
    subject: Optional[RPJSubject] = Field(None, description="指定学科")
    top_k: int = Field(3, ge=1, le=10, description="返回数量")

class RPJSimilarQuestionItem(BaseModel):
    """RPJ相似题目项"""
    id: int
    content: str
    subject: RPJSubject
    question_type: QuestionType
    difficulty: DifficultyLevel
    excerpt: Optional[str] = Field(None, description="文章节选")
    similarity_score: float
    reasoning_path: Optional[str] = Field(None, description="解题思路相似性说明")

class RPJSimilarQuestionResponse(BaseModel):
    """RPJ相似题目响应"""
    original_question_id: int
    guidance_text: str = Field(..., description="学习指导文本")
    similar_questions: List[RPJSimilarQuestionItem]
    comparison_analysis: Optional[str] = Field(None, description="题目对比分析")

class RPJLearningPlanRequest(BaseModel):
    """RPJ学习计划请求"""
    subject_focus: Optional[RPJSubject] = Field(None, description="重点学科")
    skill_focus: List[str] = Field(default_factory=list, description="技能重点")
    days: int = Field(7, ge=1, le=30, description="计划天数")
    include_writing: bool = Field(True, description="是否包含写作训练")
    include_reading: bool = Field(True, description="是否包含阅读训练")

class RPJLearningPlanResponse(BaseModel):
    """RPJ学习计划响应"""
    plan_text: str
    daily_tasks: Dict[str, List[Dict[str, Any]]]  # 按天分类的任务
    skill_breakdown: Dict[str, float]  # 技能掌握度分析
    recommended_materials: List[Dict[str, str]]  # 推荐阅读材料

class RPJStudentProfile(BaseModel):
    """RPJ学生画像"""
    user_id: int
    subjects_stats: Dict[RPJSubject, Dict[str, Any]]
    reading_speed: Optional[float] = Field(None, description="阅读速度(字/分钟)")
    vocabulary_size: Optional[int] = Field(None, description="词汇量估计")
    common_errors: Dict[str, int]  # 常见错误类型统计
    writing_improvement_areas: List[str]  # 写作需要改进的方面

# ============ Endpoints ============

@router.post("/questions/submit-answer", response_model=RPJAnswerFeedback)
async def submit_rpj_answer(
    request: RPJAnswerRequest,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
    background_tasks: BackgroundTasks = None,
):
    """
    提交RPJ题目答案并获取反馈
    
    针对语文、英语、道法的阅读理解、写作等题型提供专业反馈
    使用专门训练的RPJ评估模型
    """
    from backend.modules.tony.agents.rpj_evaluation_agent import RPJEvaluationAgent
    
    # 验证题目存在
    question = await crud_rpj_question.get_question(db, request.question_id)
    if not question:
        raise HTTPException(status_code=404, detail="题目不存在")
    
    # 获取题目详细信息
    subject = question.subject
    question_type = question.question_type
    
    # 调用RPJ评估Agent
    evaluation_agent = RPJEvaluationAgent()
    
    try:
        feedback = await evaluation_agent.evaluate_answer(
            question_id=request.question_id,
            student_answer=request.student_answer,
            user_id=user_id,
            confidence_level=request.confidence_level,
            time_spent=request.time_spent,
        )
        
        # 异步保存答题记录和分析结果
        if background_tasks:
            background_tasks.add_task(
                _save_answer_analysis,
                db, user_id, request.question_id,
                request.student_answer, feedback
            )
        
        # 记录评估事件
        try:
            from backend.core.services.metrics_service import get_metrics_service
            await get_metrics_service().log_event(
                event_type="rpj",
                event_name="answer_evaluated",
                ok=True,
                user_id=user_id,
                module="tony",
                subject=subject,
                question_id=request.question_id,
                payload={
                    "score": feedback.score,
                    "question_type": question_type,
                    "time_spent": request.time_spent,
                },
            )
        except Exception:
            pass
        
        return feedback
        
    except Exception as e:
        logger.error(f"RPJ answer evaluation failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"答案评估失败: {str(e)}"
        )


@router.post("/questions/{question_id}/similar", response_model=RPJSimilarQuestionResponse)
async def get_rpj_similar_questions(
    question_id: int,
    request: RPJSimilarQuestionRequest,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    获取RPJ相似题目（举一反三）
    
    基于语义相似度和题型匹配，为文科题目推荐相似练习
    支持跨学科知识迁移
    """
    from backend.modules.tony.agents.rpj_similar_question_agent import RPJSimilarQuestionAgent
    
    # 验证原题
    question = await crud_rpj_question.get_question(db, question_id)
    if not question:
        raise HTTPException(status_code=404, detail="题目不存在")
    
    # 使用指定学科或原题学科
    target_subject = request.subject or question.subject
    
    # 获取学生在该学科的学习情况
    subject_stats = await _get_subject_stats(db, user_id, target_subject)
    
    # 调用RPJ相似题目Agent
    agent = RPJSimilarQuestionAgent()
    
    try:
        result = await agent.find_similar_questions(
            original_question_id=question_id,
            subject=target_subject,
            question_type=question.question_type,
            top_k=request.top_k,
            user_profile=subject_stats,
        )
        
        # 构建响应
        similar_questions = []
        for q in result.get("similar_questions", []):
            similar_questions.append(RPJSimilarQuestionItem(
                id=q["id"],
                content=q["content"],
                subject=q["subject"],
                question_type=q["question_type"],
                difficulty=q["difficulty"],
                excerpt=q.get("excerpt"),
                similarity_score=q["similarity_score"],
                reasoning_path=q.get("reasoning_path"),
            ))
        
        # 记录推荐事件
        try:
            from backend.core.services.metrics_service import get_metrics_service
            await get_metrics_service().log_event(
                event_type="rpj",
                event_name="similar_questions_recommended",
                ok=True,
                user_id=user_id,
                module="tony",
                subject=target_subject,
                question_id=question_id,
                payload={
                    "recommended_count": len(similar_questions),
                    "question_types": [q.question_type for q in similar_questions],
                },
            )
        except Exception:
            pass
        
        return RPJSimilarQuestionResponse(
            original_question_id=question_id,
            guidance_text=result.get("guidance_text", ""),
            similar_questions=similar_questions,
            comparison_analysis=result.get("comparison_analysis"),
        )
        
    except Exception as e:
        logger.error(f"RPJ similar questions search failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"相似题目搜索失败: {str(e)}"
        )


@router.post("/learning-plan", response_model=RPJLearningPlanResponse)
async def get_rpj_learning_plan(
    request: RPJLearningPlanRequest,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    获取RPJ个性化学习计划
    
    针对语文、英语、道法的学习特点制定专项计划
    包括阅读训练、写作练习、道德思辨等
    """
    from backend.modules.tony.agents.rpj_learning_plan_agent import RPJLearningPlanAgent
    
    # 获取学生RPJ学习画像
    student_profile = await _get_rpj_student_profile(db, user_id)
    
    # 调用RPJ学习计划Agent
    agent = RPJLearningPlanAgent()
    
    try:
        plan = await agent.generate_learning_plan(
            user_id=user_id,
            student_profile=student_profile,
            subject_focus=request.subject_focus,
            skill_focus=request.skill_focus,
            days=request.days,
            include_writing=request.include_writing,
            include_reading=request.include_reading,
        )
        
        return RPJLearningPlanResponse(
            plan_text=plan["plan_text"],
            daily_tasks=plan["daily_tasks"],
            skill_breakdown=plan["skill_breakdown"],
            recommended_materials=plan["recommended_materials"],
        )
        
    except Exception as e:
        logger.error(f"RPJ learning plan generation failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"学习计划生成失败: {str(e)}"
        )


@router.get("/profile", response_model=RPJStudentProfile)
async def get_rpj_student_profile(
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    获取RPJ学生专项画像
    
    分析学生在语文、英语、道法学科的学习情况
    包括阅读能力、写作水平、道德认知等
    """
    profile = await _get_rpj_student_profile(db, user_id)
    return profile


@router.post("/questions/generate")
async def generate_rpj_question(
    subject: RPJSubject = Query(..., description="学科"),
    question_type: QuestionType = Query(..., description="题型"),
    difficulty: DifficultyLevel = Query(DifficultyLevel.MEDIUM, description="难度"),
    theme: Optional[str] = Query(None, description="主题/文章主题"),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    动态生成RPJ题目
    
    根据学科、题型、难度和主题生成定制化的阅读理解或写作题目
    使用大模型生成文章和问题
    """
    from backend.modules.tony.agents.rpj_question_generator import RPJQuestionGenerator
    
    agent = RPJQuestionGenerator()
    
    try:
        question_data = await agent.generate_question(
            subject=subject,
            question_type=question_type,
            difficulty=difficulty,
            theme=theme,
            user_id=user_id,
        )
        
        # 保存生成的题目到数据库
        question_id = await crud_rpj_question.create_question(
            db=db,
            user_id=user_id,
            **question_data,
        )
        
        return {
            "question_id": question_id,
            "content": question_data["content"],
            "article": question_data.get("article"),
            "questions": question_data.get("questions", []),
            "metadata": question_data.get("metadata", {}),
        }
        
    except Exception as e:
        logger.error(f"RPJ question generation failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"题目生成失败: {str(e)}"
        )


# ============ Helper Functions ============

async def _save_answer_analysis(
    db: AsyncSession,
    user_id: int,
    question_id: int,
    student_answer: str,
    feedback: RPJAnswerFeedback,
):
    """异步保存答案分析和学习记录"""
    try:
        from backend.core.db.models import RPJAnswerRecord
        from sqlalchemy import insert
        
        record = {
            "user_id": user_id,
            "question_id": question_id,
            "student_answer": student_answer,
            "score": feedback.score,
            "correctness": feedback.correctness,
            "detailed_feedback": feedback.detailed_feedback,
            "improvement_suggestions": feedback.improvement_suggestions,
            "analysis_data": {
                "language_points": feedback.language_points,
                "grammar_errors": feedback.grammar_errors,
                "moral_lessons": feedback.moral_lessons,
                "model_analysis": feedback.model_analysis,
            },
        }
        
        await db.execute(
            insert(RPJAnswerRecord).values(**record)
        )
        await db.commit()
        
    except Exception as e:
        logger.error(f"Failed to save RPJ answer record: {e}")
        # 不抛出异常，避免影响主流程


async def _get_subject_stats(
    db: AsyncSession,
    user_id: int,
    subject: RPJSubject,
) -> Dict[str, Any]:
    """获取学生在指定学科的统计信息"""
    try:
        from sqlalchemy import select, func
        from backend.core.db.models import RPJAnswerRecord, RPJQuestion
        
        # 获取答题统计
        stats_result = await db.execute(
            select(
                func.count(RPJAnswerRecord.id).label("total_answers"),
                func.avg(RPJAnswerRecord.score).label("avg_score"),
                func.count().filter(RPJAnswerRecord.score >= 60).label("pass_count"),
            )
            .join(RPJQuestion, RPJAnswerRecord.question_id == RPJQuestion.id)
            .where(RPJAnswerRecord.user_id == user_id)
            .where(RPJQuestion.subject == subject)
        )
        
        stats = stats_result.fetchone()
        
        return {
            "total_answers": stats.total_answers or 0,
            "avg_score": float(stats.avg_score or 0),
            "pass_rate": (stats.pass_count or 0) / max(stats.total_answers or 1, 1),
            "subject": subject,
        }
        
    except Exception as e:
        logger.error(f"Failed to get subject stats: {e}")
        return {
            "total_answers": 0,
            "avg_score": 0,
            "pass_rate": 0,
            "subject": subject,
        }


async def _get_rpj_student_profile(
    db: AsyncSession,
    user_id: int,
) -> RPJStudentProfile:
    """构建RPJ学生专项画像"""
    from sqlalchemy import select, func, desc
    from backend.core.db.models import RPJAnswerRecord, RPJQuestion, User
    
    profile = {
        "user_id": user_id,
        "subjects_stats": {},
        "common_errors": {},
        "writing_improvement_areas": [],
    }
    
    try:
        # 获取用户基本信息
        user_result = await db.execute(
            select(User).where(User.id == user_id)
        )
        user = user_result.scalar_one_or_none()
        
        # 按学科统计
        for subject in RPJSubject:
            stats = await _get_subject_stats(db, user_id, subject)
            profile["subjects_stats"][subject] = stats
            
        # 分析常见错误
        errors_result = await db.execute(
            select(RPJAnswerRecord.correctness, func.count().label("count"))
            .where(RPJAnswerRecord.user_id == user_id)
            .group_by(RPJAnswerRecord.correctness)
            .order_by(desc("count"))
            .limit(10)
        )
        
        for row in errors_result.fetchall():
            profile["common_errors"][row.correctness] = row.count
            
        # 获取需要改进的写作方面
        # 这里可以添加更复杂的分析逻辑
        
    except Exception as e:
        logger.error(f"Failed to build RPJ student profile: {e}")
    
    return RPJStudentProfile(**profile)


@router.get("/writing-samples")
async def get_writing_samples(
    subject: RPJSubject = Query(..., description="学科"),
    grade_level: str = Query("middle", description="年级水平"),
    limit: int = Query(5, ge=1, le=20, description="返回数量"),
):
    """
    获取优秀作文样例
    
    提供不同学科、不同水平的写作范文
    用于学习参考和模仿
    """
    from backend.modules.tony.agents.rpj_writing_mentor import RPJWritingMentor
    
    mentor = RPJWritingMentor()
    
    try:
        samples = await mentor.get_writing_samples(
            subject=subject,
            grade_level=grade_level,
            limit=limit,
        )
        
        return {
            "samples": samples,
            "metadata": {
                "subject": subject,
                "grade_level": grade_level,
                "total_samples": len(samples),
            },
        }
        
    except Exception as e:
        logger.error(f"Failed to get writing samples: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"获取写作样例失败: {str(e)}"
        )


@router.post("/questions/import")
async def import_rpj_questions(
    file_url: str = Query(..., description="题目文件URL"),
    subject: RPJSubject = Query(..., description="学科"),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    批量导入RPJ题目
    
    支持从标准格式文件导入阅读理解、写作等题目
    """
    from backend.modules.tony.agents.rpj_question_importer import RPJQuestionImporter
    
    importer = RPJQuestionImporter()
    
    try:
        results = await importer.import_from_file(
            file_url=file_url,
            subject=subject,
            db=db,
            user_id=user_id,
        )
        
        return {
            "success": True,
            "imported_count": results["imported_count"],
            "failed_count": results["failed_count"],
            "errors": results.get("errors", []),
            "summary": results.get("summary", ""),
        }
        
    except Exception as e:
        logger.error(f"RPJ question import failed: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"题目导入失败: {str(e)}"
        )