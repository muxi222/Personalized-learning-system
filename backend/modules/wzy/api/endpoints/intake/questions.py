"""
Questions API Endpoints
错题相关API - WZY模块（数学和物理）
"""

import os
import uuid
import json
import logging
import time
import asyncio
from typing import Optional, List, Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.db.session import get_db, async_session_maker
from backend.core.crud import crud_question, crud_task, crud_user, crud_image_file
from backend.core.schemas.question import (
    QuestionCreate,
    QuestionUpdate,
    QuestionResponse,
    QuestionDetail,
    QuestionListResponse,
    SimilarQuestionQuery,
    SuggestedQuestion,
)
from backend.core.schemas.task import TaskResponse, TaskStatus
from backend.core.db.models import TaskStatusEnum
from backend.core.db.models import ImageFile
from backend.modules.wzy.api.deps import get_current_user_id
from backend.modules.wzy.config import settings
from backend.core.services.gemini_ocr_service import get_gemini_ocr_service, SubjectType
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()

UPLOAD_DIR = "./data/uploads"

# WZY模块学科映射：数学和物理
SUBJECT_NAME_MAP = {
    "数学": "math",
    "物理": "physics",
    "其他": "other",  # 为了兼容性保留
}

class SuggestedQuestionAnswerResponse(BaseModel):
    index: int
    suggested_question: SuggestedQuestion
    generated: bool = False

def ensure_markdown_format(text: str) -> str:
    """
    确保文本以合适的Markdown格式返回，特别是数学公式
    """
    if not text:
        return text
    
    text = str(text)
    
    # 如果已经是Markdown格式，直接返回
    if "```" in text or "#" in text or "**" in text:
        return text
    
    # 检查是否包含数学公式但没有合适的标记
    import re
    
    # 检查LaTeX公式模式
    latex_patterns = [
        r'\\\(.*?\\\)',  # \(...\)
        r'\\\[.*?\\\]',  # \[...\]
        r'\$(?!\$).*?(?<!\$)\$(?!\$)',  # $...$ 但不匹配 $$...$$
        r'\$\$.*?\$\$',  # $$...$$
    ]
    
    has_latex = False
    for pattern in latex_patterns:
        if re.search(pattern, text, re.DOTALL):
            has_latex = True
            break
    
    # 如果包含数学公式，但文本中没有其他Markdown标记，可以添加一些基本的Markdown
    if has_latex and not any(mark in text for mark in ["```", "#", "**", "*", ">"]):
        # 对于包含数学公式的长文本，可以包装在代码块中
        if len(text) > 100:
            lines = text.split('\n')
            if len(lines) > 3:
                return f"```math\n{text}\n```"
    
    return text

def _public_base() -> str:
    return (settings.PUBLIC_API_BASE_URL or "http://localhost:6003").rstrip("/")


def build_image_file_content_url(image_id: int) -> str:
    """
    用 image_files.id 生成图片访问 URL（与 question.id 不同维度，避免混用）。
    """
    base = _public_base()
    return f"{base}/api/{settings.MODULE_NAME}/v1/image-files/{image_id}/content"


def build_fallback_question_image_url(question_id: int, image_index: int) -> str:
    """
    向后兼容：如果无法定位 image_files.id，则退回 default 模块按 question_id+index 取图。
    """
    base = _public_base()
    return f"{base}/api/v1/questions/images/{question_id}?image_index={image_index}"


async def build_question_image_urls(
    db: AsyncSession,
    *,
    user_id: int,
    question: Any,
) -> List[str]:
    """
    生成该题目对应的图片 URL 列表。
    优先走 image_files.id（source_image_id 或 file_path->image_files 映射）。
    """
    paths: List[str] = list(getattr(question, "image_urls", None) or [])
    if not paths:
        return []

    source_image_id = getattr(question, "source_image_id", None)
    if source_image_id:
        url = build_image_file_content_url(int(source_image_id))
        return [url for _ in range(len(paths))]

    out: List[str] = []
    for idx, p in enumerate(paths):
        img = await crud_image_file.get_image_by_path(db, str(p))
        if img and img.user_id == int(user_id):
            out.append(build_image_file_content_url(int(img.id)))
        else:
            out.append(build_fallback_question_image_url(int(question.id), int(idx)))
    return out

def validate_subject(subject: str) -> None:
    """验证学科是否属于WZY模块（数学和物理）"""
    if subject not in settings.SUBJECTS:
        raise HTTPException(
            status_code=400,
            detail=f"Subject '{subject}' is not supported by WZY module. "
                   f"Supported subjects: {settings.SUBJECTS}"
        )

async def call_router_llm_json_with_retry(
    prompt: str,
    model: Optional[str] = None,
    log_ctx: str = "",
    trace_id: str = "",
    trace_stage: str = "",
    max_retries: int = 3,
    retry_delay: float = 1.0,
    timeout: float = 30.0
) -> Dict[str, Any]:
    """
    带有重试机制的大模型调用函数
    """
    last_error = None
    
    for attempt in range(max_retries):
        try:
            # 导入原始函数
            from backend.modules.wzy.agents.intake.question_intake_ocr_agent import call_router_llm_json
            
            # 设置超时
            try:
                result = await asyncio.wait_for(
                    call_router_llm_json(
                        prompt=prompt,
                        model=model,
                        log_ctx=log_ctx,
                        trace_id=trace_id,
                        trace_stage=trace_stage
                    ),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                raise TimeoutError(f"模型调用超时 ({timeout}秒)")
            
            # 验证结果是否为字典
            if isinstance(result, dict):
                logger.info(
                    f"[call_router_llm_json_with_retry] success attempt={attempt+1}/{max_retries} "
                    f"trace_id={trace_id} trace_stage={trace_stage}"
                )
                return result
            else:
                raise ValueError(f"模型返回的不是字典类型: {type(result)}")
                
        except (json.JSONDecodeError, ValueError, KeyError, AttributeError, TimeoutError) as e:
            last_error = e
            logger.warning(
                f"[call_router_llm_json_with_retry] attempt={attempt+1}/{max_retries} failed: {e} "
                f"trace_id={trace_id} trace_stage={trace_stage}"
            )
            
            if attempt < max_retries - 1:
                # 等待一段时间后重试（指数退避）
                wait_time = retry_delay * (2 ** attempt)  # 1, 2, 4 秒
                logger.info(f"等待 {wait_time} 秒后重试...")
                await asyncio.sleep(wait_time)
                continue
            else:
                logger.error(
                    f"[call_router_llm_json_with_retry] all {max_retries} attempts failed: {last_error}"
                )
                raise
    
    # 理论上不会执行到这里
    raise RuntimeError(f"重试{max_retries}次后仍然失败: {last_error}")

@router.post("/", response_model=TaskResponse, status_code=202)
async def create_question(
    question_data: QuestionCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    提交新错题

    触发Agent工作流进行异步处理:
    1. 解析输入提取结构化信息
    2. 保存到数据库
    3. 生成向量并存入向量库
    4. AI分析错因
    5. 生成举一反三题目

    返回task_id，可通过 /tasks/{task_id} 查询处理状态
    """
    # Generate task ID
    task_id = str(uuid.uuid4())

    # Create task record
    await crud_task.create_task(db, task_id, user_id=user_id)
    await db.commit()

    # Start background processing
    async def process_async():
        from backend.modules.wzy.agents.intake.question_intake_agent import QuestionIntakeAgent

        try:
            agent = QuestionIntakeAgent()
            result = await agent.process(
                raw_input=question_data.content,
                user_id=user_id,
                task_id=task_id,
                image_urls=question_data.image_urls,
                student_answer=question_data.student_answer,
            )

            if result.get("success"):
                logger.info(f"Task {task_id} completed, question_id={result.get('question_id')}")
            else:
                logger.warning(f"Task {task_id} completed with errors: {result.get('errors')}")

        except Exception as e:
            logger.error(f"Task {task_id} failed: {e}")
            async with async_session_maker() as session:
                await crud_task.fail_task(session, task_id, str(e))
                await session.commit()

    background_tasks.add_task(process_async)

    logger.info(f"Created task {task_id} for user {user_id}")

    return TaskResponse(
        task_id=task_id,
        status=TaskStatus.PENDING,
        message="Task created. Processing started.",
    )

async def process_image_intake_with_optimized_prompt(
    user_id: int,
    task_id: str,
    file_path: str,
    subject: str,
    grade: str,
    difficulty: str,
    image_file_id: Optional[int] = None
):
    """
    处理图片录入的优化版本，使用简化的reasoner_agent
    """
    from backend.modules.wzy.agents.intake.question_intake_ocr_agent import QuestionIntakeOCRAgent
    from backend.core.db.session import async_session_maker
    
    max_retries = 2  # 减少重试次数
    retry_delay = 1.0
    
    for attempt in range(max_retries):
        try:
            agent = QuestionIntakeOCRAgent()
            logger.info(
                f"[wzy/questions/ocr] task_id={task_id} user_id={user_id} attempt={attempt+1}/{max_retries} "
                f"agent.process(type=image) subject={subject} diff={difficulty}"
            )
            
            # 设置环境变量，强制使用简化模式
            os.environ["WZY_REASONER_MAX_TOKENS"] = "1024"
            os.environ["WZY_DEEP_ENRICH_MAX_ITEMS"] = "1"
            os.environ["WZY_SIMPLIFIED_MODE"] = "true"  # 新增标志
            
            result = await agent.process(
                input_type="image",
                user_id=user_id,
                task_id=task_id,
                subject=subject,
                grade=grade,
                difficulty=difficulty,
                image_path=file_path,
                source_image_id=image_file_id,
            )
            
            if result.get("success"):
                logger.info(f"Image intake task {task_id} succeeded on attempt {attempt+1}")
                return result
            else:
                logger.warning(f"Image intake task {task_id} failed on attempt {attempt+1}: {result.get('errors')}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay * (attempt + 1))
                    continue
        
        except Exception as e:
            logger.error(f"Image intake task {task_id} failed on attempt {attempt+1}: {e}", exc_info=True)
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay * (attempt + 1))
                continue
            else:
                async with async_session_maker() as session:
                    await crud_task.fail_task(session, task_id, str(e) or "处理失败")
                    await session.commit()
                return {"success": False, "errors": [str(e)]}
    
    # 如果所有重试都失败
    async with async_session_maker() as session:
        await crud_task.fail_task(session, task_id, "处理失败，已重试2次")
        await session.commit()
    return {"success": False, "errors": ["处理失败，已重试2次"]}
    
@router.post("/ocr", response_model=TaskResponse, status_code=202)
async def create_question_intake_ocr(
    file: Optional[UploadFile] = File(None),
    text_data: Optional[str] = Form(None),
    input_type: str = Form(..., description="输入类型: 'image' 或 'text'"),
    subject: str = Form("math"),  # WZY默认数学
    grade: str = Form("", description="学段/年级（可选，例如：初中/高中/高一/初三）"),
    difficulty: str = Form("medium"),
    background_tasks: BackgroundTasks = None,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    录入错题功能 - 支持图片和文字两种格式

    这是专门的"录入错题"功能接口，与AI批改功能区分。
    支持两种输入模式：
    1. 图片模式 (input_type='image'): 上传图片，OCR识别后入库
    2. 文字模式 (input_type='text'): 提交JSON格式文字，大模型处理总结后入库

    流程:
    图片模式:
    1. 上传图片并保存
    2. OCR识别题目内容
    3. 提取题目、学生答案、正确答案
    4. 创建错题记录

    文字模式:
    1. 接收JSON格式的文字数据
    2. 大模型处理总结
    3. 记录原始输入和总结后的输入
    4. 创建错题记录
    """
    # 验证输入类型
    if input_type not in ["image", "text"]:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的输入类型: {input_type}，支持: 'image' 或 'text'"
        )

    # 验证学科
    validate_subject(subject)

    # 获取用户对象
    user = await crud_user.get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # 生成task_id
    task_id = str(uuid.uuid4())
    t0 = time.perf_counter()

    try:
        # 创建任务记录
        # Backend-side concurrency limit: no more than 3 active image intakes per user
        if input_type == "image":
            active = await crud_task.count_active_intake_image_tasks_for_user(db, user_id)
            if active >= 3:
                raise HTTPException(status_code=429, detail="同时录入中的错题图片不能超过3张，请等待当前任务处理完成后再上传")

        await crud_task.create_task(db, task_id, user_id=user_id)
        await crud_task.update_task_status(
            db,
            task_id,
            TaskStatusEnum.PENDING,
            current_step="任务已创建，等待处理",
            result_patch={
                "request": {
                    "input_type": input_type,
                    "subject": subject,
                    "grade": grade,
                    "difficulty": difficulty,
                    "has_file": bool(file),
                    "text_len": len(text_data or "") if isinstance(text_data, str) else 0,
                }
            },
            result_stage="queued",
        )
        await db.commit()

        logger.info(
            f"[wzy/questions/ocr] intake request accepted task_id={task_id} user_id={user_id} "
            f"type={input_type} subject={subject} grade={grade or None} diff={difficulty} "
            f"file={getattr(file, 'filename', None)} content_type={getattr(file, 'content_type', None)} text_len={len(text_data or '') if text_data else 0}"
        )

        # 根据输入类型处理
        if input_type == "image":
            # 图片模式处理
            if not file:
                raise HTTPException(status_code=400, detail="图片模式需要上传文件")

            # 验证文件类型
            allowed_types = ["image/jpeg", "image/png", "image/webp", "image/heic"]
            if file.content_type not in allowed_types:
                raise HTTPException(
                    status_code=400,
                    detail=f"不支持的文件类型: {file.content_type}。支持: {', '.join(allowed_types)}"
                )

            # 读取文件内容
            content = await file.read()
            from backend.core.utils.file_utils import calculate_file_hash, get_user_upload_dir
            from backend.core.crud import crud_image_file

            # NOTE: 产品要求"录入错题图片不去重"：即使上传同一张图片，也要生成新的 image_files.id，
            # 以便后续按图片维度查询/删除更可控。
            # 由于 image_files.file_hash 在部分部署中可能有唯一约束，这里对 hash 做 task_id 级别的盐化，
            # 确保每次上传都会生成新的记录，但仍保留原始 hash 便于日志排查。
            file_hash_raw = calculate_file_hash(content)
            file_hash = calculate_file_hash(content + (str(task_id).encode("utf-8")))
            logger.info(
                f"[wzy/questions/ocr] task_id={task_id} user_id={user_id} image read bytes={len(content)} "
                f"hash_raw={file_hash_raw[:16]}... hash_upload={file_hash[:16]}..."
            )

            # 每次上传都保存为新文件（避免物理文件共享导致后续删除互相影响）
            file_ext = file.filename.split(".")[-1] if file.filename else "jpg"
            filename = f"{str(task_id).replace('-', '')[:16]}_{file_hash_raw[:16]}.{file_ext}"
            subject_en = SUBJECT_NAME_MAP.get(subject, subject.lower())

            file_path = os.path.join(
                get_user_upload_dir(UPLOAD_DIR, user, "questions", subject_en),
                filename
            )

            with open(file_path, "wb") as f:
                f.write(content)

            created_image = await crud_image_file.create_image_file(
                db=db,
                file_hash=file_hash,
                user_id=user.id,
                file_type="questions",
                subject=subject_en,
                file_path=file_path,
                file_size=len(content),
                mime_type=file.content_type,
            )
            image_file_id: Optional[int] = int(created_image.id) if created_image and getattr(created_image, "id", None) is not None else None
            logger.info(
                f"[wzy/questions/ocr] task_id={task_id} user_id={user_id} saved new image "
                f"image_id={image_file_id} hash_raw={file_hash_raw[:16]}... path={file_path}"
            )

            # Persist image_id early so task stream can expose it before OCR completes
            try:
                await crud_task.update_task_status(
                    db,
                    task_id,
                    TaskStatusEnum.PENDING,
                    current_step="图片已上传，等待识别",
                    result_patch={
                        "image_id": image_file_id,
                        # Keep old naming for compatibility
                        "source_image_id": image_file_id,
                        "file_path": file_path,
                    },
                    result_stage="uploaded",
                )
            except Exception:
                # best-effort; do not fail the upload request
                pass

            await db.commit()

            # 异步处理 - 使用优化版本
            async def process_image():
                try:
                    result = await process_image_intake_with_optimized_prompt(
                        user_id=user_id,
                        task_id=task_id,
                        file_path=file_path,
                        subject=subject,
                        grade=grade,
                        difficulty=difficulty,
                        image_file_id=image_file_id
                    )
                    duration_ms = int((time.perf_counter() - t0) * 1000)
                    logger.info(
                        f"[wzy/questions/ocr] task_id={task_id} user_id={user_id} agent.process done duration_ms={duration_ms} "
                        f"success={bool(result.get('success'))} created_count={result.get('created_count') or result.get('created_count', None)}"
                    )

                    if not result.get("success"):
                        async with async_session_maker() as session:
                            errs = result.get("errors", [])
                            msg = "; ".join([str(e) for e in errs]) if isinstance(errs, list) else str(errs)
                            await crud_task.fail_task(session, task_id, msg or "处理失败")
                            await session.commit()

                except Exception as e:
                    logger.error(f"Image intake task {task_id} failed: {e}", exc_info=True)
                    async with async_session_maker() as session:
                        await crud_task.fail_task(session, task_id, str(e) or "处理失败")
                        await session.commit()

            background_tasks.add_task(process_image)

        else:
            # 文字模式处理
            if not text_data:
                raise HTTPException(status_code=400, detail="文字模式需要提供text_data")

            # 解析JSON数据
            try:
                text_json = json.loads(text_data)
            except json.JSONDecodeError:
                raise HTTPException(status_code=400, detail="text_data必须是有效的JSON格式")

            # 异步处理
            async def process_text():
                from backend.modules.wzy.agents.intake.question_intake_ocr_agent import QuestionIntakeOCRAgent
                from backend.core.db.session import async_session_maker

                try:
                    agent = QuestionIntakeOCRAgent()
                    logger.info(
                        f"[wzy/questions/ocr] task_id={task_id} user_id={user_id} start agent.process(type=text) subject={subject} diff={difficulty} "
                        f"text_keys={list(text_json.keys()) if isinstance(text_json, dict) else None}"
                    )
                    result = await agent.process(
                        input_type="text",
                        user_id=user_id,
                        task_id=task_id,
                        subject=subject,
                        grade=grade,
                        difficulty=difficulty,
                        text_data=text_json,
                    )
                    duration_ms = int((time.perf_counter() - t0) * 1000)
                    logger.info(
                        f"[wzy/questions/ocr] task_id={task_id} user_id={user_id} agent.process done duration_ms={duration_ms} success={bool(result.get('success'))}"
                    )

                    if not result.get("success"):
                        async with async_session_maker() as session:
                            errs = result.get("errors", [])
                            msg = "; ".join([str(e) for e in errs]) if isinstance(errs, list) else str(errs)
                            await crud_task.fail_task(session, task_id, msg or "处理失败")
                            await session.commit()

                except Exception as e:
                    logger.error(f"Text intake task {task_id} failed: {e}", exc_info=True)
                    async with async_session_maker() as session:
                        await crud_task.fail_task(session, task_id, str(e) or "处理失败")
                        await session.commit()

            background_tasks.add_task(process_text)

        logger.info(f"[wzy/questions/ocr] task created task_id={task_id} user_id={user_id} type={input_type}")

        return TaskResponse(
            task_id=task_id,
            status=TaskStatus.PENDING,
            message=f"{'图片' if input_type == 'image' else '文字'}已提交，正在处理中...",
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to process intake OCR: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")

@router.post("/ocr-old", response_model=TaskResponse, status_code=202)
async def create_question_with_image_old(
    file: UploadFile = File(...),
    subject: str = Form("other"),
    difficulty: str = Form("medium"),
    title: Optional[str] = Form(None),
    background_tasks: BackgroundTasks = None,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    上传图片识别错题（旧接口，保留兼容性）

    支持上传错题图片，自动OCR识别题目内容和答案，
    然后进行结构化存储和AI分析。

    流程:
    1. 上传图片并保存到用户专属目录
    2. OCR识别题目内容
    3. 提取题目、学生答案、正确答案
    4. 创建错题记录
    5. 触发AI分析流程
    """
    # 验证文件类型
    allowed_types = ["image/jpeg", "image/png", "image/webp", "image/heic"]
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {file.content_type}。支持: {', '.join(allowed_types)}"
        )

    # 获取用户对象
    user = await crud_user.get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # 解析学科
    subject_en = SUBJECT_NAME_MAP.get(subject, subject.lower())

    # 读取文件内容并计算哈希值
    content = await file.read()
    from backend.core.utils.file_utils import calculate_file_hash, get_filename_from_path, get_user_upload_dir
    from backend.core.crud import crud_image_file

    file_hash = calculate_file_hash(content)

    # 检查图片是否已存在（同一用户维度去重）
    existing_image = await crud_image_file.get_image_by_hash(db, file_hash)
    is_duplicate = False

    # 检查是否为同一用户的重复图片
    if existing_image and existing_image.user_id == user.id:
        is_duplicate = True
        logger.info(f"Duplicate image detected for user {user.id}: hash={file_hash[:16]}...")
        # 前端可以通过响应中的信息来显示提醒

    # 生成task_id用于后续处理
    task_id = str(uuid.uuid4())

    if existing_image:
        # 图片已存在，复用现有文件
        file_path = existing_image.file_path
        filename = get_filename_from_path(file_path)
        logger.info(f"Image already exists, reusing: hash={file_hash[:16]}..., path={file_path}")

        # 增加引用计数
        await crud_image_file.increment_reference_count(db, file_hash)
    else:
        # 图片不存在，保存新文件（使用hash值作为文件名）
        file_ext = file.filename.split(".")[-1] if file.filename else "jpg"
        # 使用hash值的前32位作为文件名，避免文件名过长
        filename = f"{file_hash[:32]}.{file_ext}"

        # 保存到用户专属目录: data/uploads/{username_email}/questions/{subject}/
        file_path = os.path.join(
            get_user_upload_dir(UPLOAD_DIR, user, "questions", subject_en),
            filename
        )

        # 保存文件
        with open(file_path, "wb") as f:
            f.write(content)

        # 创建图片文件记录
        await crud_image_file.create_image_file(
            db=db,
            file_hash=file_hash,
            user_id=user.id,
            file_type="questions",
            subject=subject_en,
            file_path=file_path,
            file_size=len(content),
            mime_type=file.content_type,
        )
        logger.info(f"New image saved: hash={file_hash[:16]}..., path={file_path}")

    try:

        # 创建任务记录
        await crud_task.create_task(db, task_id, user_id=user_id)
        await crud_task.create_task(db, task_id, user_id=user_id)
        await db.commit()

        # 异步处理OCR和分析
        async def process_with_ocr():
            from backend.modules.wzy.agents.intake.question_intake_agent import QuestionIntakeAgent
            from backend.core.db.session import async_session_maker

            try:
                # 1. OCR识别
                from backend.modules.wzy.config import settings as wzy_settings
                ocr_service = get_gemini_ocr_service(wzy_settings)
                await ocr_service.initialize()

                # 解析学科类型 - 支持中文和英文
                subject_en = SUBJECT_NAME_MAP.get(subject, subject.lower())
                try:
                    subject_type = SubjectType(subject_en)
                except ValueError:
                    subject_type = SubjectType.OTHER

                # 使用OCR识别单个题目（不是试卷批改，而是错题录入）
                logger.info(f"Starting OCR for question image: {file_path}")

                # 使用简化的prompt进行单题识别
                from backend.core.services.gemini_ocr_service import GeminiOCRService
                ocr_result = await ocr_service._analyze_image(
                    image_path=file_path,
                    prompt=f"""你是一个专业的学习助手。请识别图片中的错题，提取以下信息（如果图片中没有某项信息，请留空）：

1. **题目内容**: 完整的题目描述
2. **学生答案**: 学生写的答案（如果有）
3. **正确答案**: 正确的答案（如果有标注）
4. **题目类型**: 选择题/填空题/解答题等
5. **知识点**: 涉及的知识点（如果能识别）

请以JSON格式返回，格式如下：
{{
  "question_content": "题目内容",
  "student_answer": "学生答案",
  "correct_answer": "正确答案",
  "question_type": "题目类型",
  "knowledge_points": ["知识点1", "知识点2"]
}}

如果图片模糊或无法识别，请说明原因。"""
                )

                # 解析OCR结果
                import json
                import re

                # 尝试从结果中提取JSON
                json_match = re.search(r'\{[\s\S]*\}', ocr_result)
                if json_match:
                    ocr_data = json.loads(json_match.group())
                else:
                    # 如果没有JSON格式，使用原始文本作为题目内容
                    ocr_data = {
                        "question_content": ocr_result,
                        "student_answer": "",
                        "correct_answer": "",
                        "question_type": "",
                        "knowledge_points": []
                    }

                logger.info(f"OCR completed for task {task_id}: {ocr_data}")

                # 2. 使用QuestionIntakeAgent处理
                agent = QuestionIntakeAgent()
                result = await agent.process(
                    raw_input=ocr_data.get("question_content", ""),
                    user_id=user_id,
                    task_id=task_id,
                    image_urls=[file_path],
                    student_answer=ocr_data.get("student_answer", ""),
                    correct_answer=ocr_data.get("correct_answer", ""),
                    subject=subject,
                    difficulty=difficulty,
                    title=title or "OCR识别错题",
                )

                if result.get("success"):
                    logger.info(f"OCR task {task_id} completed, question_id={result.get('question_id')}")
                else:
                    logger.warning(f"OCR task {task_id} completed with errors: {result.get('errors')}")

            except Exception as e:
                logger.error(f"OCR task {task_id} failed: {e}", exc_info=True)
                async with async_session_maker() as session:
                    await crud_task.fail_task(session, task_id, str(e))
                    await session.commit()

        background_tasks.add_task(process_with_ocr)

        logger.info(f"Created OCR task {task_id} for user {user_id}")

        return TaskResponse(
            task_id=task_id,
            status=TaskStatus.PENDING,
            message="图片已上传，OCR识别处理中...",
        )

    except Exception as e:
        logger.error(f"Failed to process image upload: {e}")
        # 清理文件
        if os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=500, detail=f"处理失败: {str(e)}")

@router.get("/", response_model=QuestionListResponse)
async def list_questions(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    subject: Optional[str] = Query(None, description="学科筛选"),
    difficulty: Optional[str] = Query(None, description="难度筛选"),
    search: Optional[str] = Query(None, description="关键词搜索"),
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    获取错题列表
    支持分页、筛选和搜索
    """
    skip = (page - 1) * page_size
    questions, total = await crud_question.get_questions(
        db,
        user_id=user_id,
        skip=skip,
        limit=page_size,
        subject=subject,
        difficulty=difficulty,
        search=search,
    )

    # Bulk resolve file_path -> image_files.id for this page (avoid N+1)
    path_to_image_id: dict[str, int] = {}
    try:
        from sqlalchemy import select

        all_paths: set[str] = set()
        for q in questions:
            if getattr(q, "source_image_id", None):
                continue
            for p in (getattr(q, "image_urls", None) or []):
                if p:
                    all_paths.add(str(p))
        if all_paths:
            stmt = select(ImageFile).where(ImageFile.user_id == int(user_id), ImageFile.file_path.in_(list(all_paths)))
            imgs = (await db.execute(stmt)).scalars().all()
            path_to_image_id = {str(img.file_path): int(img.id) for img in imgs if img and img.file_path}
    except Exception:
        path_to_image_id = {}

    items: List[QuestionResponse] = []
    for q in questions:
        item = QuestionResponse.model_validate(q)
        paths = list(getattr(q, "image_urls", None) or [])
        if not paths:
            item.image_urls = []
        else:
            sid = getattr(q, "source_image_id", None)
            if sid:
                url = build_image_file_content_url(int(sid))
                item.image_urls = [url for _ in range(len(paths))]
            else:
                urls: List[str] = []
                for idx, p in enumerate(paths):
                    img_id = path_to_image_id.get(str(p))
                    if img_id:
                        urls.append(build_image_file_content_url(int(img_id)))
                    else:
                        urls.append(build_fallback_question_image_url(int(q.id), int(idx)))
                item.image_urls = urls
                # If this question doesn't have source_image_id persisted yet, expose it in response for frontend linking.
                first_img_id = path_to_image_id.get(str(paths[0])) if paths else None
                if first_img_id and getattr(item, "source_image_id", None) is None:
                    item.source_image_id = int(first_img_id)
        items.append(item)

    return QuestionListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=items,
    )

@router.get("/{question_id}", response_model=QuestionDetail)
async def get_question(
    question_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    获取错题详情
    包含AI分析结果和举一反三题目
    """
    question = await crud_question.get_question(db, question_id, user_id)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    resp = QuestionDetail.model_validate(question)
    resp.image_urls = await build_question_image_urls(db, user_id=user_id, question=question)
    
    # 确保Markdown格式字段正确处理
    # 如果字段中包含LaTeX数学公式，确保它们被正确标记
    if resp.explanation:
        resp.explanation = ensure_markdown_format(resp.explanation)
    if resp.error_analysis:
        resp.error_analysis = ensure_markdown_format(resp.error_analysis)
    if resp.student_answer:
        resp.student_answer = ensure_markdown_format(resp.student_answer)
    if resp.correct_answer:
        resp.correct_answer = ensure_markdown_format(resp.correct_answer)
    
    # 处理举一反三题目中的答案格式
    for sq in resp.suggested_questions:
        if sq.answer:
            sq.answer = ensure_markdown_format(sq.answer)
        if sq.explanation:
            sq.explanation = ensure_markdown_format(sq.explanation)
    
    # Derive answer_sources (student raw / teacher marked / model inferred / grading basis) from summarized_input JSON
    try:
        si = getattr(question, "summarized_input", None)
        if isinstance(si, str):
            s = si.strip()
            if s.startswith("{") and s.endswith("}"):
                obj = json.loads(s)
                if isinstance(obj, dict):
                    ans = obj.get("answer_sources")
                    grading = obj.get("grading")
                    if isinstance(ans, dict) or isinstance(grading, dict):
                        resp.answer_sources = {
                            "answer_sources": ans if isinstance(ans, dict) else {},
                            "grading": grading if isinstance(grading, dict) else {},
                        }
    except Exception:
        pass
    if getattr(resp, "source_image_id", None) is None:
        try:
            paths = list(getattr(question, "image_urls", None) or [])
            if paths:
                img = await crud_image_file.get_image_by_path(db, str(paths[0]))
                if img and img.user_id == int(user_id):
                    resp.source_image_id = int(img.id)
        except Exception:
            pass
    return resp


def ensure_markdown_format(text: str) -> str:
    """
    确保文本以合适的Markdown格式返回，特别是数学公式
    """
    if not text:
        return text
    
    # 如果文本中已经有LaTeX公式标记，确保格式正确
    text = str(text)
    
    # 检查是否包含LaTeX公式但没有正确的标记
    latex_patterns = [
        r'\\\(.*?\\\)',  # \(...\)
        r'\\\[.*?\\\]',  # \[...\]
        r'\$(?!\$).*?(?!<\$)\$',  # $...$ 但不匹配 $$...$$
    ]
    
    has_latex = False
    for pattern in latex_patterns:
        import re
        if re.search(pattern, text):
            has_latex = True
            break
    
    # 如果包含数学公式但没有合适的标记，添加Markdown代码块提示
    if has_latex and not text.startswith("```"):
        # 添加Markdown代码块提示，让前端知道这是数学公式
        return text
    
    return text


@router.post("/{question_id}/suggested-questions/{index}/answer", response_model=SuggestedQuestionAnswerResponse)
async def get_suggested_question_answer(
    question_id: int,
    index: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    WZY模块: lazily generate/fill the answer for a '举一反三'练习题。
    Frontend uses this when sq.answer is empty, so users can see the solution after clicking '查看答案'.
    """
    question = await crud_question.get_question(db, question_id, user_id)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    # Normalize suggested_questions via QuestionDetail validator (handles list[str]/legacy dict formats)
    resp = QuestionDetail.model_validate(question)
    sqs = list(resp.suggested_questions or [])
    if index < 0 or index >= len(sqs):
        raise HTTPException(status_code=404, detail="Suggested question not found")

    sq = sqs[index]
    if isinstance(sq.answer, str) and sq.answer.strip():
        # 确保现有答案格式正确
        sq.answer = ensure_markdown_format(sq.answer)
        if sq.explanation:
            sq.explanation = ensure_markdown_format(sq.explanation)
        return SuggestedQuestionAnswerResponse(index=index, suggested_question=sq, generated=False)

    # Generate answer via router LLM (with WZY tracing/logging)
    model = os.getenv("WZY_PRACTICE_ANSWER_MODEL") or os.getenv("WZY_TEXT_MODEL") or None
    trace_id = f"sq_answer_q{question_id}_i{index}_{uuid.uuid4().hex[:8]}"
    
    # 优化prompt，要求返回Markdown格式的答案
    prompt = f"""
请作为数学老师，为以下练习题提供参考答案和解题思路：

题目：{sq.content}

要求：
1. 使用Markdown格式返回，数学公式使用$...$或$$...$$包裹
2. 答案要清晰、完整，包含必要的计算步骤
3. 如果可能，提供多种解法或思路

请按照以下JSON格式返回：
{{
  "answer": "答案内容（使用Markdown格式）",
  "explanation": "详细的解题思路和步骤（使用Markdown格式）"
}}
""".strip()

    try:
        # 使用带重试的版本调用大模型
        obj = await call_router_llm_json_with_retry(
            prompt,
            model=model,
            log_ctx=f"task=- user={user_id} subject={getattr(resp, 'subject', '')} q={question_id} sq={index}",
            trace_id=trace_id,
            trace_stage="suggested_answer",
            max_retries=3,
            retry_delay=1.0,
            timeout=30.0
        )
    except Exception as e:
        logger.error(
            f"[suggested_answer] user={user_id} q={question_id} sq={index} failed after retries: {e}",
            exc_info=True,
        )
        raise HTTPException(status_code=503, detail=f"模型服务暂时不可用：{str(e)}")

    # 验证返回的数据结构
    if not isinstance(obj, dict):
        raise HTTPException(status_code=502, detail="模型输出解析失败：返回的不是字典格式")
    
    answer = obj.get("answer")
    explanation = obj.get("explanation")
    
    if not isinstance(answer, str) or not answer.strip():
        # 如果answer字段为空，尝试从其他可能的字段获取
        for key in ["答案", "solution", "result"]:
            if key in obj and isinstance(obj[key], str) and obj[key].strip():
                answer = obj[key].strip()
                break
        
        if not answer or not answer.strip():
            raise HTTPException(status_code=502, detail="模型未返回有效答案")
    
    # 确保答案是Markdown格式
    answer = ensure_markdown_format(answer.strip())
    
    if explanation is not None and not isinstance(explanation, str):
        explanation = None
    elif explanation is not None:
        explanation = ensure_markdown_format(explanation.strip())

    updated = SuggestedQuestion(
        content=sq.content,
        answer=answer,
        difficulty=sq.difficulty,
        knowledge_points=list(sq.knowledge_points or []),
        explanation=(explanation if isinstance(explanation, str) and explanation else sq.explanation),
    )
    sqs[index] = updated

    # Persist back to DB (store list[dict])
    try:
        question.suggested_questions = [x.model_dump() for x in sqs]
        await db.commit()
    except Exception as e:
        logger.warning(
            f"[suggested_answer] user={user_id} q={question_id} sq={index} commit failed: {e}",
            exc_info=True,
        )
        # still return generated answer even if persistence fails

    return SuggestedQuestionAnswerResponse(index=index, suggested_question=updated, generated=True)

@router.patch("/{question_id}", response_model=QuestionResponse)
async def update_question(
    question_id: int,
    question_data: QuestionUpdate,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    更新错题信息
    """
    question = await crud_question.update_question(
        db, question_id, question_data, user_id
    )
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    return QuestionResponse.model_validate(question)

@router.delete("/{question_id}", status_code=204)
async def delete_question(
    question_id: int,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    删除错题
    """
    # capture source_image_id for potential cleanup
    q = await crud_question.get_question(db, question_id, user_id)
    if not q:
        raise HTTPException(status_code=404, detail="Question not found")
    source_image_id = getattr(q, "source_image_id", None)

    success = await crud_question.delete_question(db, question_id, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="Question not found")

    # Cleanup orphan image_files row (and physical file) if this was the last question for that image.
    try:
        from backend.core.crud import crud_image_file
        paths = await crud_image_file.mark_delete_orphan_question_images(
            db,
            user_id=int(user_id),
            image_ids=[int(source_image_id)] if source_image_id else [],
        )
        # Ensure DB commit before deleting physical files.
        await db.commit()
        if paths:
            crud_image_file.delete_files_best_effort(paths)
    except Exception as e:
        logger.warning(f"[wzy] cleanup orphan question image failed: {e}")

@router.post("/{question_id}/reanalyze", response_model=TaskResponse, status_code=202)
async def reanalyze_question(
    question_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    重新分析错题
    对已有错题重新进行AI分析
    """
    # Verify question exists and belongs to user
    question = await crud_question.get_question(db, question_id, user_id)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    # Create new task
    task_id = str(uuid.uuid4())
    await crud_task.create_task(db, task_id, user_id=user_id, question_id=question_id)
    await db.commit()

    # Start background reanalysis using new agent
    async def reanalyze_async():
        from backend.modules.wzy.agents.intake.question_intake_agent import analyze_error, update_result
        from backend.core.agents.state import QuestionIntakeState
        from backend.core.db.session import async_session_maker

        try:
            # 构建状态
            state: QuestionIntakeState = {
                "task_id": task_id,
                "question_id": question_id,
                "user_id": user_id,
                "raw_input": question.content,
                "structured_data": {
                    "question_body": question.content,
                    "student_answer": question.student_answer,
                    "correct_answer": question.correct_answer,
                },
                "subject": question.subject.value if question.subject else "math",
                "grade": question.grade or "",
                "chapter": question.chapter or "",
                "knowledge_points": question.knowledge_points or [],
                "errors": [],
            }

            # 执行分析
            result = await analyze_error(state)
            state = {**state, **result}

            # 更新结果
            await update_result(state)

            async with async_session_maker() as session:
                await crud_task.complete_task(session, task_id, question_id)
                await session.commit()

        except Exception as e:
            logger.error(f"Reanalysis task {task_id} failed: {e}")
            async with async_session_maker() as session:
                await crud_task.fail_task(session, task_id, str(e))
                await session.commit()

    background_tasks.add_task(reanalyze_async)

    return TaskResponse(
        task_id=task_id,
        status=TaskStatus.PENDING,
        message="Reanalysis started.",
    )

@router.post("/similar", response_model=List[QuestionResponse])
async def find_similar_questions(
    query: SimilarQuestionQuery,
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    查找相似题目
    基于向量相似度检索相关错题
    """
    from backend.core.services.vector_store_service import get_vector_store_service

    vector_store = get_vector_store_service()
    await vector_store.initialize()

    # Get query text
    if query.question_id:
        question = await crud_question.get_question(db, query.question_id, user_id)
        if not question:
            raise HTTPException(status_code=404, detail="Question not found")
        query_text = question.content
    elif query.content:
        query_text = query.content
    else:
        raise HTTPException(status_code=400, detail="Provide question_id or content")

    # Search similar
    results = await vector_store.search_by_text(
        query_text=query_text,
        n_results=query.limit,
        where={"user_id": user_id} if user_id else None,
    )

    # Get full question data
    questions = []
    for result in results:
        q_id = int(result["id"])
        if query.question_id and q_id == query.question_id:
            continue  # Skip self
        question = await crud_question.get_question(db, q_id, user_id)
        if question:
            questions.append(QuestionResponse.model_validate(question))

    return questions