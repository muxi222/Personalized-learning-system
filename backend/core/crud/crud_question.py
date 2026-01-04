"""
Question CRUD Operations
错题数据库操作
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import InvalidRequestError

from ..db.models import Question, SubjectEnum, DifficultyEnum
from ..schemas.question import QuestionCreate, QuestionUpdate

async def create_question(
    db: AsyncSession,
    question_data: Optional[QuestionCreate] = None,
    user_id: Optional[int] = None,
    **kwargs
) -> Question:
    """
    创建新错题
    
    支持两种调用方式：
    1. 使用 QuestionCreate schema: create_question(db, question_data, user_id)
    2. 使用关键字参数: create_question(db, user_id=1, content="...", subject=SubjectEnum.MATH, ...)
    """
    if question_data:
        # 使用 schema 方式
        db_question = Question(
            user_id=user_id,
            title=question_data.title,
            content=question_data.content,
            subject=SubjectEnum(question_data.subject.value),
            difficulty=DifficultyEnum(question_data.difficulty.value),
            image_urls=question_data.image_urls,
            source_image_id=getattr(question_data, "source_image_id", None),
            student_answer=question_data.student_answer,
            correct_answer=question_data.correct_answer,
            explanation=question_data.explanation,
            is_correct=getattr(question_data, "is_correct", None),
            score=getattr(question_data, "score", None),
            max_score=getattr(question_data, "max_score", None),
            source=question_data.source,
            chapter=question_data.chapter,
            tags=question_data.tags,
            upload_group_id=getattr(question_data, "upload_group_id", None),
            upload_index=getattr(question_data, "upload_index", None),
        )
    else:
        # 使用关键字参数方式
        # 注意：user_id 可能被函数签名中的 user_id 参数捕获，也可能在 kwargs 中
        # 优先使用函数参数中的 user_id，如果没有则从 kwargs 中获取
        final_user_id = user_id if user_id is not None else kwargs.get("user_id")
        
        subject = kwargs.get("subject")
        difficulty = kwargs.get("difficulty")
        
        # 调试日志
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"[create_question] user_id param: {user_id}, kwargs user_id: {kwargs.get('user_id')}, final_user_id: {final_user_id}")
        
        if isinstance(subject, str):
            subject = SubjectEnum(subject)
        if isinstance(difficulty, str):
            difficulty = DifficultyEnum(difficulty)
        
        if final_user_id is None:
            logger.error(f"[create_question] user_id is None! user_id param: {user_id}, kwargs: {kwargs}")
            raise ValueError("user_id is required but was None")
        
        db_question = Question(
            user_id=final_user_id,
            title=kwargs.get("title"),
            content=kwargs.get("content", ""),
            subject=subject or SubjectEnum.OTHER,
            grade=kwargs.get("grade"),
            difficulty=difficulty or DifficultyEnum.MEDIUM,
            image_urls=kwargs.get("image_urls", []),
            source_image_id=kwargs.get("source_image_id"),
            student_answer=kwargs.get("student_answer"),
            correct_answer=kwargs.get("correct_answer"),
            explanation=kwargs.get("explanation"),
            is_correct=kwargs.get("is_correct"),
            score=kwargs.get("score"),
            max_score=kwargs.get("max_score"),
            source=kwargs.get("source"),
            source_description=kwargs.get("source_description"),
            chapter=kwargs.get("chapter"),
            tags=kwargs.get("tags", []),
            knowledge_points=kwargs.get("knowledge_points", []),
            error_analysis=kwargs.get("error_analysis"),
            suggested_questions=kwargs.get("suggested_questions", []),
            original_input=kwargs.get("original_input"),
            summarized_input=kwargs.get("summarized_input"),
            upload_group_id=kwargs.get("upload_group_id"),
            upload_index=kwargs.get("upload_index"),
        )
    
    db.add(db_question)
    await db.flush()
    try:
        await db.refresh(db_question)
    except InvalidRequestError:
        # Legacy sqlite schemas may not support refresh reliably; treat as best-effort.
        import logging
        logging.getLogger(__name__).warning("[crud_question] refresh(Question) failed; returning unrefreshed instance", exc_info=True)
    return db_question

async def get_question(
    db: AsyncSession,
    question_id: int,
    user_id: Optional[int] = None,
) -> Optional[Question]:
    """获取单个错题"""
    query = select(Question).where(Question.id == question_id)
    if user_id is not None:
        query = query.where(Question.user_id == user_id)
    result = await db.execute(query)
    return result.scalar_one_or_none()

async def get_questions(
    db: AsyncSession,
    user_id: int,
    skip: int = 0,
    limit: int = 20,
    subject: Optional[str] = None,
    difficulty: Optional[str] = None,
    tags: Optional[List[str]] = None,
    chapter: Optional[str] = None,
    search: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> tuple[List[Question], int]:
    """获取错题列表 (分页)"""
    # Base query
    query = select(Question).where(Question.user_id == user_id)

    # Apply filters
    if subject:
        query = query.where(Question.subject == SubjectEnum(subject))
    if difficulty:
        query = query.where(Question.difficulty == DifficultyEnum(difficulty))
    if chapter:
        query = query.where(Question.chapter == chapter)
    if search:
        query = query.where(Question.content.ilike(f"%{search}%"))
    if start_date:
        query = query.where(Question.created_at >= start_date)
    if end_date:
        query = query.where(Question.created_at <= end_date)

    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Apply pagination and ordering
    query = query.order_by(desc(Question.created_at)).offset(skip).limit(limit)
    result = await db.execute(query)
    questions = list(result.scalars().all())

    return questions, total

async def update_question(
    db: AsyncSession,
    question_id: int,
    question_data: QuestionUpdate,
    user_id: Optional[int] = None,
) -> Optional[Question]:
    """更新错题"""
    question = await get_question(db, question_id, user_id)
    if not question:
        return None

    update_data = question_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if value is not None:
            if field == "subject":
                value = SubjectEnum(value.value)
            elif field == "difficulty":
                value = DifficultyEnum(value.value)
            setattr(question, field, value)

    question.updated_at = datetime.utcnow()
    await db.flush()
    await db.refresh(question)
    return question

async def delete_question(
    db: AsyncSession,
    question_id: int,
    user_id: Optional[int] = None,
) -> bool:
    """删除错题"""
    question = await get_question(db, question_id, user_id)
    if not question:
        return False

    await db.delete(question)
    await db.flush()
    return True

async def update_question_analysis(
    db: AsyncSession,
    question_id: int,
    error_analysis: Optional[str] = None,
    suggested_questions: Optional[List[Dict[str, Any]]] = None,
    knowledge_points: Optional[List[str]] = None,
) -> Optional[Question]:
    """更新错题的AI分析结果"""
    question = await get_question(db, question_id)
    if not question:
        return None

    if error_analysis is not None:
        question.error_analysis = error_analysis
    if suggested_questions is not None:
        question.suggested_questions = suggested_questions
    if knowledge_points is not None:
        question.knowledge_points = knowledge_points

    question.updated_at = datetime.utcnow()
    await db.flush()
    await db.refresh(question)
    return question

async def update_review_status(
    db: AsyncSession,
    question_id: int,
    mastery_level: Optional[float] = None,
    next_review_at: Optional[datetime] = None,
) -> Optional[Question]:
    """更新复习状态 (用于艾宾浩斯遗忘曲线)"""
    question = await get_question(db, question_id)
    if not question:
        return None

    question.review_count += 1
    question.last_reviewed_at = datetime.utcnow()

    if mastery_level is not None:
        question.mastery_level = max(0.0, min(1.0, mastery_level))
    if next_review_at is not None:
        question.next_review_at = next_review_at

    await db.flush()
    await db.refresh(question)
    return question

async def get_questions_for_review(
    db: AsyncSession,
    user_id: int,
    limit: int = 10,
) -> List[Question]:
    """获取需要复习的错题 (基于艾宾浩斯遗忘曲线)"""
    now = datetime.utcnow()
    query = (
        select(Question)
        .where(Question.user_id == user_id)
        .where(
            (Question.next_review_at <= now) | (Question.next_review_at.is_(None))
        )
        .where(Question.mastery_level < 0.9)  # 未完全掌握的题目
        .order_by(Question.mastery_level.asc(), Question.next_review_at.asc())
        .limit(limit)
    )
    result = await db.execute(query)
    return list(result.scalars().all())
