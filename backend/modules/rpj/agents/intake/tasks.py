"""
RPJ Agents - Intake Tasks (Celery)

Intake module: "录入错题" + reanalyze.
RPJ 只处理语文、英语和道法学科。
"""

import logging
from typing import Optional, List

from backend.modules.rpj.celery_app import celery_app
from backend.modules.rpj.agents.shared.celery_utils import run_async, update_task_status, mark_task_failed

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3)
def process_question_task(
    self,
    task_id: str,
    raw_input: str,
    user_id: int,
    image_urls: Optional[List[str]] = None,
    student_answer: Optional[str] = None,
    subject: str = None,  # 新增 subject 参数，只能为 '语文'、'英语' 或 '道法'
):
    """
    处理错题的Celery任务
    RPJ 只处理语文、英语和道法学科
    """
    logger.info(f"[Celery] Starting RPJ question intake task {task_id} for user {user_id}")
    
    # 学科验证
    if subject not in ['语文', '英语', '道法']:
        error_msg = f"RPJ only supports chinese, english and morality, got {subject}"
        logger.error(f"[Celery] Task {task_id} failed: {error_msg}")
        run_async(mark_task_failed(task_id, error_msg))
        raise ValueError(error_msg)

    try:
        result = run_async(_process_question_async(task_id, raw_input, user_id, image_urls, student_answer, subject))
        logger.info(f"[Celery] RPJ task {task_id} completed successfully")
        return result
    except Exception as e:
        logger.error(f"[Celery] RPJ task {task_id} failed: {e}")
        run_async(mark_task_failed(task_id, str(e)))
        raise self.retry(exc=e, countdown=60)


async def _process_question_async(
    task_id: str,
    raw_input: str,
    user_id: int,
    image_urls: Optional[List[str]] = None,
    student_answer: Optional[str] = None,
    subject: str = None,
) -> dict:
    """异步处理错题 - RPJ版本，只处理语文、英语和道法"""
    from .question_intake_agent import QuestionIntakeAgent

    await update_task_status(task_id, "processing", 5.0, f"initializing for {subject}")

    agent = QuestionIntakeAgent()
    result = await agent.process(
        raw_input=raw_input,
        user_id=user_id,
        task_id=task_id,
        image_urls=image_urls,
        student_answer=student_answer,
        subject=subject,  # 传递学科信息
    )
    return result


@celery_app.task(bind=True, max_retries=2)
def reanalyze_question_task(
    self,
    task_id: str,
    question_id: int,
):
    """重新分析已有错题的Celery任务 - RPJ版本"""
    logger.info(f"[Celery] Starting RPJ reanalysis task {task_id} for question {question_id}")

    try:
        result = run_async(_reanalyze_async(task_id, question_id))
        logger.info(f"[Celery] RPJ reanalysis task {task_id} completed")
        return result
    except Exception as e:
        logger.error(f"[Celery] RPJ reanalysis task {task_id} failed: {e}")
        run_async(mark_task_failed(task_id, str(e)))
        raise self.retry(exc=e, countdown=30)


async def _reanalyze_async(task_id: str, question_id: int) -> dict:
    """异步重新分析 - RPJ版本"""
    from backend.core.db.session import async_session_maker
    from backend.core.crud.crud_question import get_question
    from .question_intake_agent import RpjQuestionIntakeAgent

    async with async_session_maker() as session:
        question = await get_question(session, question_id)
        if not question:
            raise ValueError(f"Question {question_id} not found")
        
        # 检查学科是否为语文、英语或道法
        if question.subject not in ['语文', '英语', '道法']:
            error_msg = f"RPJ only supports chinese, english and morality, question has {question.subject}"
            await mark_task_failed(task_id, error_msg)
            raise ValueError(error_msg)

    await update_task_status(task_id, "processing", 50.0, f"reanalyzing {question.subject} question")

    agent = RpjQuestionIntakeAgent()
    result = await agent.process(
        raw_input=question.content,
        user_id=question.user_id,
        task_id=task_id,
        student_answer=question.student_answer,
        subject=question.subject,  # 传递学科信息
    )
    return result


@celery_app.task(bind=True, max_retries=3)
def process_question_intake_ocr_task(
    self,
    task_id: str,
    user_id: int,
    input_type: str,
    subject: str,
    grade: str = "",
    difficulty: str = "medium",
    image_path: Optional[str] = None,
    text_data: Optional[dict] = None,
    source_image_id: Optional[int] = None,
):
    """
    处理OCR录入错题的Celery任务
    RPJ 只处理语文、英语和道法学科
    """
    logger.info(f"[Celery] Starting RPJ OCR intake task {task_id} for user {user_id}, type={input_type}, subject={subject}")
    
    # 学科验证
    if subject not in ['语文', '英语', '道法']:
        error_msg = f"RPJ only supports chinese, english and morality, got {subject}"
        logger.error(f"[Celery] Task {task_id} failed: {error_msg}")
        run_async(mark_task_failed(task_id, error_msg))
        raise ValueError(error_msg)
    
    # 输入类型验证
    if input_type not in ['image', 'text']:
        error_msg = f"Input type must be 'image' or 'text', got {input_type}"
        logger.error(f"[Celery] Task {task_id} failed: {error_msg}")
        run_async(mark_task_failed(task_id, error_msg))
        raise ValueError(error_msg)
    
    # 图片模式需要image_path
    if input_type == 'image' and not image_path:
        error_msg = "Image mode requires image_path"
        logger.error(f"[Celery] Task {task_id} failed: {error_msg}")
        run_async(mark_task_failed(task_id, error_msg))
        raise ValueError(error_msg)
    
    # 文字模式需要text_data
    if input_type == 'text' and not text_data:
        error_msg = "Text mode requires text_data"
        logger.error(f"[Celery] Task {task_id} failed: {error_msg}")
        run_async(mark_task_failed(task_id, error_msg))
        raise ValueError(error_msg)

    try:
        result = run_async(_process_question_intake_ocr_async(
            task_id, user_id, input_type, subject, grade, difficulty, image_path, text_data, source_image_id
        ))
        logger.info(f"[Celery] RPJ OCR task {task_id} completed successfully")
        return result
    except Exception as e:
        logger.error(f"[Celery] RPJ OCR task {task_id} failed: {e}")
        run_async(mark_task_failed(task_id, str(e)))
        raise self.retry(exc=e, countdown=60)


async def _process_question_intake_ocr_async(
    task_id: str,
    user_id: int,
    input_type: str,
    subject: str,
    grade: str = "",
    difficulty: str = "medium",
    image_path: Optional[str] = None,
    text_data: Optional[dict] = None,
    source_image_id: Optional[int] = None,
) -> dict:
    """异步处理OCR录入错题 - RPJ版本"""
    from .question_intake_ocr_agent import QuestionIntakeOCRAgent

    await update_task_status(task_id, "processing", 10.0, f"initializing OCR intake for {subject}")

    agent = QuestionIntakeOCRAgent()
    
    if input_type == 'image':
        result = await agent.process(
            input_type=input_type,
            user_id=user_id,
            task_id=task_id,
            subject=subject,
            difficulty=difficulty,
            grade=grade,
            source_image_id=source_image_id,
            image_path=image_path,
        )
    else:  # text mode
        result = await agent.process(
            input_type=input_type,
            user_id=user_id,
            task_id=task_id,
            subject=subject,
            difficulty=difficulty,
            grade=grade,
            text_data=text_data,
        )
    
    return result