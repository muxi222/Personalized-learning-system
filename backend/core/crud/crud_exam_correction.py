"""
Exam Correction CRUD Operations
AI批注记录数据库操作
"""

import logging
from typing import Optional, List, Tuple
from datetime import datetime, timedelta
from sqlalchemy import select, func, and_, extract
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ..db.models import ExamCorrection, Question, SubjectEnum, QuestionSourceEnum

logger = logging.getLogger(__name__)


async def create_exam_correction(
    db: AsyncSession,
    user_id: int,
    subject: SubjectEnum,
    original_image_id: int,
    corrected_image_id: Optional[int] = None,
    total_score: float = 0.0,
    max_score: float = 100.0,
    accuracy_rate: float = 0.0,
    question_count: int = 0,
    correct_count: int = 0,
    wrong_count: int = 0,
    overall_analysis: Optional[str] = None,
    weak_points: Optional[List[str]] = None,
    improvement_suggestions: Optional[List[str]] = None,
    questions_detail: Optional[List[dict]] = None,
    grade: Optional[str] = None,
    exam_title: Optional[str] = None,
) -> ExamCorrection:
    """创建AI批注记录（使用图片ID）"""
    correction = ExamCorrection(
        user_id=user_id,
        subject=subject,
        grade=grade,
        exam_title=exam_title,
        original_image_id=original_image_id,
        corrected_image_id=corrected_image_id,
        total_score=total_score,
        max_score=max_score,
        accuracy_rate=accuracy_rate,
        question_count=question_count,
        correct_count=correct_count,
        wrong_count=wrong_count,
        overall_analysis=overall_analysis,
        weak_points=weak_points or [],
        improvement_suggestions=improvement_suggestions or [],
        questions_detail=questions_detail or [],
    )
    db.add(correction)
    await db.flush()
    await db.refresh(correction)
    return correction


async def get_exam_correction(
    db: AsyncSession,
    correction_id: int,
    user_id: Optional[int] = None,
) -> Optional[ExamCorrection]:
    """获取单个批注记录（包含关联的图片）"""
    query = (
        select(ExamCorrection)
        .options(
            selectinload(ExamCorrection.original_image),
            selectinload(ExamCorrection.corrected_image),
        )
        .where(ExamCorrection.id == correction_id)
    )
    if user_id is not None:
        query = query.where(ExamCorrection.user_id == user_id)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_exam_corrections(
    db: AsyncSession,
    user_id: int,
    skip: int = 0,
    limit: int = 20,
    subject: Optional[str] = None,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> Tuple[List[ExamCorrection], int]:
    """获取批注记录列表（分页）"""
    logger.info(f"get_exam_corrections: user_id={user_id}, subject={subject}, skip={skip}, limit={limit}")
    
    # 基础查询（包含关联的图片）
    query = (
        select(ExamCorrection)
        .options(
            selectinload(ExamCorrection.original_image),
            selectinload(ExamCorrection.corrected_image),
        )
        .where(ExamCorrection.user_id == user_id)
    )
    
    # 学科筛选
    # 注意：数据库存储的是枚举的name（如MATH），而前端传入的是value（如math）
    if subject:
        # 统一转换为小写处理
        subject_lower = subject.lower()
        logger.info(f"Filtering by subject: {subject} (lowercase: {subject_lower})")
        
        # 查找匹配的枚举成员
        matched = False
        for enum_member in SubjectEnum:
            logger.debug(f"Checking enum: {enum_member.name} (value={enum_member.value})")
            if enum_member.value == subject_lower or enum_member.name.lower() == subject_lower:
                logger.info(f"Subject filter matched: {subject} -> {enum_member.name}")
                query = query.where(ExamCorrection.subject == enum_member)
                matched = True
                break
        
        if not matched:
            logger.warning(f"Invalid subject filter (no match): {subject}")
    
    # 时间范围筛选
    if start_date:
        query = query.where(ExamCorrection.created_at >= start_date)
    if end_date:
        query = query.where(ExamCorrection.created_at <= end_date)
    
    # 总数查询
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0
    
    # 分页查询
    query = query.order_by(ExamCorrection.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    corrections = result.scalars().all()
    
    logger.info(f"Query result: found {len(corrections)} corrections (total={total})")
    if len(corrections) > 0:
        logger.debug(f"First correction: id={corrections[0].id}, subject={corrections[0].subject.name}")
    
    return list(corrections), total


async def get_correction_statistics(
    db: AsyncSession,
    user_id: int,
    period: str = "week",  # week, month, quarter, year
    subject: str = None,  # 可选：筛选特定学科，None表示所有学科
) -> dict:
    """
    获取批注统计数据

    Args:
        user_id: 用户ID
        period: 统计周期 (week, month, quarter, year)
        subject: 可选，学科筛选（None表示所有学科）

    Returns:
        统计数据字典
    """
    # 计算时间范围
    now = datetime.utcnow()
    period_map = {
        "week": timedelta(days=7),
        "month": timedelta(days=30),
        "quarter": timedelta(days=90),
        "year": timedelta(days=365),
    }
    start_date = now - period_map.get(period, timedelta(days=7))

    # 构建基础查询条件
    base_conditions = [
        ExamCorrection.user_id == user_id,
        ExamCorrection.created_at >= start_date
    ]

    # 如果指定了学科，添加学科过滤
    if subject:
        from backend.core.db.models import SubjectEnum
        base_conditions.append(ExamCorrection.subject == SubjectEnum(subject))

    # 基础统计
    query = select(
        func.count(ExamCorrection.id).label("total_corrections"),
        func.sum(ExamCorrection.question_count).label("total_questions"),
        func.sum(ExamCorrection.correct_count).label("total_correct"),
        func.sum(ExamCorrection.wrong_count).label("total_wrong"),
        func.avg(ExamCorrection.accuracy_rate).label("avg_accuracy"),
        func.avg(ExamCorrection.total_score).label("avg_score"),
    ).where(and_(*base_conditions))
    
    result = await db.execute(query)
    stats = result.first()

    # 按学科统计
    subject_query = select(
        ExamCorrection.subject,
        func.count(ExamCorrection.id).label("count"),
        func.avg(ExamCorrection.accuracy_rate).label("avg_accuracy"),
        func.sum(ExamCorrection.wrong_count).label("wrong_count"),
    ).where(and_(*base_conditions)).group_by(ExamCorrection.subject)
    
    subject_result = await db.execute(subject_query)
    subject_stats = {
        row.subject.value: {
            "count": row.count,
            "avg_accuracy": float(row.avg_accuracy or 0),
            "wrong_count": row.wrong_count or 0,
        }
        for row in subject_result
    }
    
    # 按时间分组统计（用于趋势图）
    if period == "week":
        # 按天统计
        time_query = select(
            func.date(ExamCorrection.created_at).label("date"),
            func.count(ExamCorrection.id).label("count"),
            func.avg(ExamCorrection.accuracy_rate).label("avg_accuracy"),
        ).where(and_(*base_conditions)).group_by(
            func.date(ExamCorrection.created_at)
        ).order_by(func.date(ExamCorrection.created_at))
    else:
        # 按周统计
        time_query = select(
            extract('week', ExamCorrection.created_at).label("week"),
            func.count(ExamCorrection.id).label("count"),
            func.avg(ExamCorrection.accuracy_rate).label("avg_accuracy"),
        ).where(and_(*base_conditions)).group_by(
            extract('week', ExamCorrection.created_at)
        ).order_by(extract('week', ExamCorrection.created_at))
    
    time_result = await db.execute(time_query)
    time_series = [
        {
            "period": str(row[0]),
            "count": row.count,
            "avg_accuracy": float(row.avg_accuracy or 0),
        }
        for row in time_result
    ]
    
    return {
        "period": period,
        "start_date": start_date.isoformat(),
        "end_date": now.isoformat(),
        "total_corrections": stats.total_corrections or 0,
        "total_questions": stats.total_questions or 0,
        "total_correct": stats.total_correct or 0,
        "total_wrong": stats.total_wrong or 0,
        "avg_accuracy": float(stats.avg_accuracy or 0),
        "avg_score": float(stats.avg_score or 0),
        "subject_stats": subject_stats,
        "time_series": time_series,
    }


async def delete_exam_correction(
    db: AsyncSession,
    correction_id: int,
    user_id: int,
    delete_related_questions: bool = True,
) -> bool:
    """
    删除批注记录
    
    Args:
        db: 数据库会话
        correction_id: 批注记录ID
        user_id: 用户ID
        delete_related_questions: 是否同时删除关联的错题记录
    
    Returns:
        是否删除成功
    """
    import os
    import logging
    
    logger = logging.getLogger(__name__)
    
    correction = await get_exam_correction(db, correction_id, user_id)
    if not correction:
        return False
    
    # 删除关联的错题记录
    if delete_related_questions:
        from ..db.models import Question
        questions_query = select(Question).where(Question.exam_correction_id == correction_id)
        questions_result = await db.execute(questions_query)
        related_questions = questions_result.scalars().all()
        
        for question in related_questions:
            # 删除错题图片文件
            if question.image_urls:
                for img_url in question.image_urls:
                    try:
                        # 从URL提取文件路径
                        if img_url.startswith('/api/v1/'):
                            file_path = img_url.replace('/api/v1/ocr/images/', './data/uploads/')
                            if os.path.exists(file_path):
                                os.remove(file_path)
                                logger.info(f"Deleted question image: {file_path}")
                    except Exception as e:
                        logger.warning(f"Failed to delete question image: {e}")
            
            await db.delete(question)
        
        logger.info(f"Deleted {len(related_questions)} related questions")
    
    # 删除批注记录（不删除图片文件，图片文件由错题图片管理功能统一管理）
    # 减少图片文件的引用计数
    if correction.original_image:
        from ..crud import crud_image_file
        await crud_image_file.decrement_reference_count(db, correction.original_image.file_hash)
    if correction.corrected_image:
        from ..crud import crud_image_file
        await crud_image_file.decrement_reference_count(db, correction.corrected_image.file_hash)
    
    # 删除批注记录
    await db.delete(correction)
    logger.info(f"Deleted exam correction {correction_id} (images preserved)")
    
    return True


async def update_exam_correction(
    db: AsyncSession,
    correction_id: int,
    user_id: int,
    **kwargs,
) -> Optional[ExamCorrection]:
    """更新批注记录"""
    correction = await get_exam_correction(db, correction_id, user_id)
    if not correction:
        return None
    
    for field, value in kwargs.items():
        if value is not None and hasattr(correction, field):
            setattr(correction, field, value)
    
    await db.flush()
    await db.refresh(correction)
    return correction

