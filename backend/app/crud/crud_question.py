"""
Question CRUD Operations
错题数据库操作
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Question, SubjectEnum, DifficultyEnum
from ..schemas.question import QuestionCreate, QuestionUpdate


async def create_question(
    db: AsyncSession,
    question_data: QuestionCreate,
    user_id: int,
) -> Question:
    """创建新错题"""
    db_question = Question(
        user_id=user_id,
        title=question_data.title,
        content=question_data.content,
        subject=SubjectEnum(question_data.subject.value),
        difficulty=DifficultyEnum(question_data.difficulty.value),
        image_urls=question_data.image_urls,
        student_answer=question_data.student_answer,
        correct_answer=question_data.correct_answer,
        explanation=question_data.explanation,
        source=question_data.source,
        chapter=question_data.chapter,
        tags=question_data.tags,
    )
    db.add(db_question)
    await db.flush()
    await db.refresh(db_question)
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
    search: Optional[str] = None,
) -> tuple[List[Question], int]:
    """获取错题列表 (分页)"""
    # Base query
    query = select(Question).where(Question.user_id == user_id)

    # Apply filters
    if subject:
        query = query.where(Question.subject == SubjectEnum(subject))
    if difficulty:
        query = query.where(Question.difficulty == DifficultyEnum(difficulty))
    if search:
        query = query.where(Question.content.ilike(f"%{search}%"))

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

