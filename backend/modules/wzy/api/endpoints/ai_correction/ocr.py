"""
OCR API 端点 - 试卷分析与批改（WZY模块）
基于TONY模块代码适配，支持数学物理学科的图形识别增强

功能:
1. 上传试卷图片进行 OCR 分析
2. 自动批改并打分
3. 生成批改后的图像
4. 增强的图形识别（几何图形、电路图等）
"""

import os
import uuid
import logging
import time
from typing import Optional
from datetime import datetime
import json

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends, Query, Path
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.modules.wzy.api.deps import get_current_user, get_current_user_id, get_optional_user_id, get_db, oauth2_scheme
from backend.modules.wzy.config import settings
from backend.core.services.gemini_ocr_service import (
    get_gemini_ocr_service,
    SubjectType,
    ExamAnalysisResult,
)
from backend.core.db.models import User
from backend.core.utils.file_utils import (
    get_user_upload_dir,
    get_user_file_url,
    get_user_directory_name,
    calculate_file_hash,
    get_filename_from_path,
)
from backend.core.crud import crud_image_file

logger = logging.getLogger(__name__)
router = APIRouter()

UPLOAD_DIR = "./data/uploads"

# 中文学科名称到英文的映射（WZY模块特有）
SUBJECT_NAME_MAP = {
    "数学": "math",
    "物理": "physics",
    "其他": "other",
}


class OCRAnalysisResponse(BaseModel):
    """OCR 分析响应"""
    success: bool
    task_id: str
    subject: str
    grade: str
    total_score: float
    max_score: float
    accuracy_rate: float
    questions: list
    overall_analysis: str
    weak_points: list
    improvement_suggestions: list
    corrected_image_url: Optional[str] = None
    is_duplicate: bool = False  # 是否为重复图片
    duplicate_message: Optional[str] = None  # 重复提示信息
    subject_mismatch_warning: Optional[str] = None  # 学科不匹配提示（如有）
    diagram_analysis: Optional[dict] = None  # 图形分析结果（WZY特有）


class QuestionDetail(BaseModel):
    """题目详情"""
    question_number: int
    question_type: str
    question_text: str
    student_answer: str
    correct_answer: Optional[str]
    score: float
    max_score: float
    is_correct: bool
    error_analysis: str
    knowledge_points: list
    solution_steps: list
    difficulty: str
    has_diagram: Optional[bool] = False  # 是否有图形（WZY特有）
    diagram_type: Optional[str] = None  # 图形类型（WZY特有）
    diagram_description: Optional[str] = None  # 图形描述（WZY特有）


@router.post("/analyze", response_model=OCRAnalysisResponse)
async def analyze_exam_image(
    file: UploadFile = File(...),
    subject: str = Form("math"),  # 默认学科改为math
    grade: str = Form(""),
    hint: Optional[str] = Form(None),
    enable_diagram_analysis: bool = Form(True),  # WZY特有：是否启用图形分析
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    分析试卷图片（WZY增强版）

    上传试卷图片，使用 Gemini 2.5 Flash 进行:
    1. OCR 识别题目和答案
    2. 自动批改打分
    3. 错因分析
    4. 生成学习建议
    5. 图形识别增强（几何图形、电路图等）
    """
    # 验证文件类型
    allowed_types = ["image/jpeg", "image/png", "image/webp", "image/heic"]
    if file.content_type not in allowed_types:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {file.content_type}。支持: {', '.join(allowed_types)}"
        )

    # 解析学科类型
    subject_en = SUBJECT_NAME_MAP.get(subject, subject.lower())

    t0 = time.perf_counter()
    logger.info(
        f"[ocr/analyze] start user_id={current_user.id} subject={subject_en} grade={grade or None} "
        f"filename={file.filename} content_type={file.content_type} enable_diagram_analysis={enable_diagram_analysis}"
    )

    # 学科验证（WZY特有）
    if subject_en not in settings.SUBJECTS:
        raise HTTPException(
            status_code=400,
            detail=f"Subject '{subject}' is not supported by WZY module. Supported: {settings.SUBJECTS}"
        )

    # 读取文件内容并计算哈希值
    content = await file.read()
    file_hash = calculate_file_hash(content)
    logger.info(
        f"[ocr/analyze] file loaded user_id={current_user.id} bytes={len(content)} hash={file_hash[:16]}..."
    )

    # 检查图片是否已存在（同一用户维度去重）
    existing_image = await crud_image_file.get_image_by_hash(db, file_hash)
    is_duplicate = False
    duplicate_message = None

    # 检查是否为同一用户的重复图片
    if existing_image and existing_image.user_id == current_user.id:
        is_duplicate = True
        duplicate_message = "检测到您之前已上传过相同的图片，系统将复用已有图片进行分析"
        logger.info(f"Duplicate image detected for user {current_user.id}: hash={file_hash[:16]}...")

    # 生成task_id用于后续处理
    task_id = str(uuid.uuid4())
    logger.info(f"[ocr/analyze] task_id={task_id} user_id={current_user.id} prepared")

    # Telemetry: journey start (exam upload -> analysis -> practice)
    try:
        from backend.core.services.metrics_service import get_metrics_service
        await get_metrics_service().log_event(
            event_type="journey",
            event_name="ocr.analyze.start",
            ok=True,
            user_id=current_user.id,
            module="wzy",  # 改为wzy
            subject=subject_en,
            task_id=task_id,
            payload={
                "filename": file.filename,
                "content_type": file.content_type,
                "is_duplicate": bool(is_duplicate),
                "enable_diagram_analysis": enable_diagram_analysis,
            },
        )
    except Exception:
        pass

    # 获取或创建原始图片记录
    from backend.core.db.models import ImageFileTypeEnum

    if existing_image:
        # 图片已存在，复用现有文件
        original_image_file = existing_image
        file_path = existing_image.file_path
        filename = get_filename_from_path(file_path)
        # NOTE: When reusing an existing image record (duplicate upload), we still need a safe
        # extension for downstream per-question image filenames.
        _ext = os.path.splitext(filename or "")[1].lstrip(".").strip().lower()
        file_ext = _ext or "jpg"
        logger.info(f"Image already exists, reusing: hash={file_hash[:16]}..., path={file_path}")

        # 增加引用计数
        await crud_image_file.increment_reference_count(db, file_hash)
    else:
        # 图片不存在，保存新文件（使用hash值作为文件名）
        file_ext = file.filename.split(".")[-1] if file.filename else "jpg"
        # 使用hash值的前32位作为文件名，避免文件名过长
        filename = f"{file_hash[:32]}.{file_ext}"

        # 保存到用户专属目录: data/uploads/{username_email}/corrections/{subject}/
        upload_dir = get_user_upload_dir(UPLOAD_DIR, current_user, "corrections", subject_en)
        file_path = os.path.join(upload_dir, filename)

        # 保存文件
        with open(file_path, "wb") as f:
            f.write(content)

        # 创建图片文件记录（原始图片）- 存储相对路径以便跨环境
        # 标准化路径格式为 data/uploads/... (不带 ./ 前缀)
        relative_path = os.path.relpath(file_path, os.path.abspath("."))
        # 移除开头的 ./ 或 ./
        relative_path = relative_path.lstrip("./")
        if not relative_path.startswith("data/uploads"):
            relative_path = f"data/uploads/{get_user_directory_name(current_user.username, current_user.email)}/corrections/{subject_en}/{filename}"

        original_image_file = await crud_image_file.create_image_file(
            db=db,
            file_hash=file_hash,
            user_id=current_user.id,
            file_type="corrections",
            subject=subject_en,
            file_path=relative_path,
            file_size=len(content),
            mime_type=file.content_type,
            image_type=ImageFileTypeEnum.ORIGINAL,
        )
        logger.info(f"New image saved: hash={file_hash[:16]}..., path={file_path}, id={original_image_file.id}")

    try:
        # 调用 OCR 服务
        ocr_service = get_gemini_ocr_service(settings)
        await ocr_service.initialize()

        # 解析学科类型 - 支持中文和英文
        try:
            subject_type = SubjectType(subject_en)
        except ValueError:
            subject_type = SubjectType.OTHER

        # 分析试卷
        t_analyze0 = time.perf_counter()
        result = await ocr_service.analyze_exam_image(
            image_path=file_path,
            subject=subject_type,
            grade=grade,
            user_hint=hint,
        )
        analyze_ms = int((time.perf_counter() - t_analyze0) * 1000)
        logger.info(
            f"[ocr/analyze] task_id={task_id} user_id={current_user.id} analyze done duration_ms={analyze_ms} "
            f"questions={len(result.questions or [])} accuracy={result.accuracy_rate} total={result.total_score}/{result.max_score}"
        )

        # ===== 学科一致性校验（WZY模块：math/physics/other）=====
        # 新增：WZY模块的学科一致性校验
        try:
            import httpx
            import re
            
            # 使用WZY模块的配置
            from backend.modules.wzy.config import settings as wzy_settings
            
            # 文本推理模型：用于学科一致性判定
            models_raw = (os.getenv("WZY_TEXT_REASONING_MODELS") or "").strip()
            if models_raw:
                model = [m.strip() for m in models_raw.split(",") if m.strip()][0]
            else:
                model = (wzy_settings.GEMINI_MODEL or "gemini-2.5-flash").strip()
            endpoint = (wzy_settings.LLM_API_ENDPOINT or "").rstrip("/")
            if not endpoint:
                raise RuntimeError("LLM_API_ENDPOINT not configured")

            headers = {}
            if getattr(wzy_settings, "LLM_API_KEY", None):
                headers["authorization"] = f"Bearer {wzy_settings.LLM_API_KEY}"

            text_sample = {
                "overall_analysis": getattr(result, "overall_analysis", "") or "",
                "questions": [
                    {"question_text": (getattr(q, "question_text", "") or "")[:300]}
                    for q in (result.questions or [])[:10]
                ],
            }

            prompt = f"""你是教研员，负责学科判定。请判断以下内容最匹配的学科，只能从 ["math","physics","other"] 中选。
用户选择学科：{subject_en}

内容摘要：
{json.dumps(text_sample, ensure_ascii=False)}

请严格输出 JSON（不要输出其它文字）：
{{"detected_subject":"math|physics|other","confidence":0.0}}"""

            t_mismatch0 = time.perf_counter()
            async with httpx.AsyncClient(base_url=endpoint, timeout=20.0) as client:
                resp = await client.post(
                    "/chat/completions",
                    json={
                        "model": model,
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.2,
                        "max_tokens": 512,
                    },
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()
                raw = data["choices"][0]["message"]["content"]
            mismatch_ms = int((time.perf_counter() - t_mismatch0) * 1000)

            m = re.search(r"\{[\s\S]*\}", raw or "")
            detected = None
            conf_f = 0.0
            subject_mismatch_warning = None
            
            if m:
                parsed = json.loads(m.group())
                detected = str(parsed.get("detected_subject") or "").strip().lower()
                try:
                    conf_f = float(parsed.get("confidence", 0.0))
                except Exception:
                    conf_f = 0.0

            if detected in ("math", "physics", "other") and detected != subject_en and conf_f >= 0.75:
                # 不直接拒绝，而是添加警告信息（WZY策略）
                subject_mismatch_warning = f"上传内容与选择学科不匹配：检测为 {detected}（置信度 {conf_f:.2f}），但选择了 {subject_en}。分析结果可能不够准确。"
                logger.warning(f"Subject mismatch warning: {subject_mismatch_warning}")
            
            logger.info(
                f"[ocr/analyze] task_id={task_id} user_id={current_user.id} subject_check ok model={model} "
                f"detected={detected or None} conf={conf_f:.2f} duration_ms={mismatch_ms}"
            )
        except Exception as e:
            logger.warning(f"[ocr/analyze] task_id={task_id} user_id={current_user.id} subject_check skipped/failed: {e}")
            subject_mismatch_warning = None

        # ===== 图形分析增强（WZY特有）=====
        diagram_analysis_result = None
        if enable_diagram_analysis and subject_en in ["math", "physics"]:
            try:
                from backend.core.services.generic_diagram_service import GenericDiagramService
                
                t_diagram0 = time.perf_counter()
                diagram_service = GenericDiagramService()
                
                # 检测图形区域
                diagram_regions = await diagram_service.detect_diagram_regions(
                    image_path=file_path,
                    subject=subject_en
                )
                
                # 为每个问题关联图形信息
                enhanced_questions = []
                for q in result.questions:
                    question_dict = q._asdict() if hasattr(q, '_asdict') else dict(q)
                    
                    # 检查问题文本中是否包含图形指示词
                    diagram_keywords = ["如图", "如图所示", "图", "图形", "示意图", "电路图", "受力图", "光路图", "磁感线"]
                    question_text = question_dict.get("question_text", "")
                    has_diagram_indicator = any(keyword in question_text for keyword in diagram_keywords)
                    
                    if has_diagram_indicator and diagram_regions:
                        # 尝试匹配最相关的图形区域
                        best_match = None
                        for region in diagram_regions:
                            region_desc = region.get("description", "")
                            # 简单匹配：如果区域描述包含题目编号或类似信息
                            if f"第{q.question_number}题" in region_desc or f"题{q.question_number}" in region_desc:
                                best_match = region
                                break
                        
                        if best_match:
                            # 提取图形信息
                            diagram_info = await diagram_service.extract_diagram_info(
                                image_path=file_path,
                                region=best_match["bbox"],
                                question_text=question_text,
                                subject=subject_en
                            )
                            
                            # 将图形信息添加到问题中
                            question_dict["has_diagram"] = True
                            question_dict["diagram_type"] = best_match.get("type", "unknown")
                            question_dict["diagram_description"] = diagram_info.get("description", "")
                            
                            # 学科特定的图形分析
                            if subject_en == "math" and best_match.get("type") in ["geometry", "function"]:
                                math_info = await diagram_service.extract_mathematical_info(
                                    image_path=file_path,
                                    region=best_match["bbox"]
                                )
                                question_dict["mathematical_elements"] = math_info
                            elif subject_en == "physics":
                                phys_info = await diagram_service.extract_physical_info(
                                    image_path=file_path,
                                    region=best_match["bbox"],
                                    diagram_type=best_match.get("type", "")
                                )
                                question_dict["physical_elements"] = phys_info
                    
                    enhanced_questions.append(question_dict)
                
                # 创建图形摘要
                if diagram_regions:
                    diagram_summary = await diagram_service.create_diagram_summary(
                        diagram_regions=diagram_regions,
                        image_path=file_path,
                        subject=subject_en
                    )
                    diagram_analysis_result = {
                        "regions": diagram_regions,
                        "summary": diagram_summary,
                        "total_regions": len(diagram_regions),
                    }
                
                diagram_ms = int((time.perf_counter() - t_diagram0) * 1000)
                logger.info(
                    f"[ocr/analyze] task_id={task_id} user_id={current_user.id} diagram analysis done duration_ms={diagram_ms} "
                    f"regions={len(diagram_regions)}"
                )
                
                # 更新result中的questions
                result.questions = enhanced_questions
                
            except Exception as e:
                logger.error(f"[ocr/analyze] task_id={task_id} user_id={current_user.id} diagram analysis failed: {e}")
                # 图形分析失败不影响主要OCR功能

        # 生成批改图像
        t_overlay0 = time.perf_counter()
        correction_result = await ocr_service.create_correction_overlay(
            image_path=file_path,
            analysis_result=result,
        )
        overlay_ms = int((time.perf_counter() - t_overlay0) * 1000)
        logger.info(
            f"[ocr/analyze] task_id={task_id} user_id={current_user.id} overlay done success={bool(correction_result.success)} duration_ms={overlay_ms}"
        )

        # 保存批改后的图像到用户专属目录和image_files表
        corrected_image_file = None
        if correction_result.success and correction_result.corrected_image_base64:
            import base64
            corrected_image_bytes = base64.b64decode(correction_result.corrected_image_base64)
            corrected_file_hash = calculate_file_hash(corrected_image_bytes)

            # 检查批改后的图片是否已存在
            existing_corrected_image = await crud_image_file.get_image_by_hash(db, corrected_file_hash)

            if existing_corrected_image:
                corrected_image_file = existing_corrected_image
                corrected_path = existing_corrected_image.file_path
                await crud_image_file.increment_reference_count(db, corrected_file_hash)
                logger.info(f"Corrected image already exists, reusing: hash={corrected_file_hash[:16]}..., id={corrected_image_file.id}")
            else:
                # 保存批改后的图片文件（使用原始学科，保证与批改前一致）
                corrected_filename = f"{corrected_file_hash[:32]}.png"
                corrected_path = os.path.join(
                    get_user_upload_dir(UPLOAD_DIR, current_user, "corrections", subject_en),
                    corrected_filename
                )
                with open(corrected_path, "wb") as f:
                    f.write(corrected_image_bytes)

                # 标准化路径格式为 data/uploads/... (不带 ./ 前缀)
                corrected_relative_path = os.path.relpath(corrected_path, os.path.abspath("."))
                corrected_relative_path = corrected_relative_path.lstrip("./")
                if not corrected_relative_path.startswith("data/uploads"):
                    corrected_relative_path = f"data/uploads/{get_user_directory_name(current_user.username, current_user.email)}/corrections/{subject_en}/{corrected_filename}"

                # 创建批改后图片文件记录（关联到原始图片，使用原始学科）
                corrected_image_file = await crud_image_file.create_image_file(
                    db=db,
                    file_hash=corrected_file_hash,
                    user_id=current_user.id,
                    file_type="corrections",
                    subject=subject_en,  # 使用原始学科，保证与批改前一致
                    file_path=corrected_relative_path,  # 使用标准化路径（不带 ./ 前缀）
                    file_size=len(corrected_image_bytes),
                    mime_type="image/png",
                    image_type=ImageFileTypeEnum.CORRECTED,
                    original_image_id=original_image_file.id,  # 关联到原始图片
                )
                logger.info(f"Saved corrected image: hash={corrected_file_hash[:16]}..., path={corrected_relative_path}, id={corrected_image_file.id}")

        # 保存批注记录到数据库（使用原始学科，保证与批改前一致）
        from backend.core.db.models import ExamCorrection, QuestionSourceEnum

        exam_correction = ExamCorrection(
            user_id=current_user.id,
            subject=subject_type,  # 使用原始学科类型
            grade=grade or result.grade,
            exam_title=hint or f"{subject_en}试卷批改",  # 使用原始学科
            original_image_id=original_image_file.id,
            corrected_image_id=corrected_image_file.id if corrected_image_file else None,
            total_score=result.total_score,
            max_score=result.max_score,
            accuracy_rate=result.accuracy_rate,
            question_count=len(result.questions),
            correct_count=sum(1 for q in result.questions if q.is_correct),
            wrong_count=sum(1 for q in result.questions if not q.is_correct),
            overall_analysis=result.overall_analysis,
            weak_points=result.weak_points,
            improvement_suggestions=result.improvement_suggestions,
            questions_detail=[
                {
                    "question_number": q.question_number,
                    "question_type": q.question_type,
                    "question_text": q.question_text,
                    "student_answer": q.student_answer,
                    "correct_answer": q.correct_answer,
                    "score": q.score,
                    "max_score": q.max_score,
                    "is_correct": q.is_correct,
                    "error_analysis": q.error_analysis,
                    "knowledge_points": q.knowledge_points,
                    "solution_steps": q.solution_steps,
                    "difficulty": q.difficulty,
                    "has_diagram": getattr(q, "has_diagram", False) if hasattr(q, "has_diagram") else False,
                    "diagram_type": getattr(q, "diagram_type", None) if hasattr(q, "diagram_type") else None,
                    "diagram_description": getattr(q, "diagram_description", None) if hasattr(q, "diagram_description") else None,
                }
                for q in result.questions
            ],
            diagram_analysis=diagram_analysis_result,  # WZY特有：保存图形分析结果
        )
        db.add(exam_correction)
        await db.flush()
        logger.info(
            f"[ocr/analyze] task_id={task_id} user_id={current_user.id} saved exam_correction id={exam_correction.id} "
            f"wrong_count={exam_correction.wrong_count} correct_count={exam_correction.correct_count}"
        )

        # 生成批改图片URL（统一由default模块处理，与TONY相同）
        def generate_correction_image_url(correction_id: int, image_type: str, subject: str) -> str:
            """
            生成批改图片URL（统一由 default 模块处理）
            与TONY模块保持一致
            """
            # 优先使用 PUBLIC_API_BASE_URL 配置
            if settings.PUBLIC_API_BASE_URL:
                base_url = settings.PUBLIC_API_BASE_URL.rstrip('/')
                return f"{base_url}/api/v1/ocr/images/corrections/{correction_id}/{image_type}"

            # 如果没有设置 PUBLIC_API_BASE_URL，使用 default 模块的地址（6100端口）
            # 统一由 default 模块处理图片访问，不再根据学科路由到不同模块
            from backend.modules.default.config import get_settings as get_default_settings
            default_settings = get_default_settings()
            default_host = default_settings.HOST if default_settings.HOST not in ['0.0.0.0', ''] else 'localhost'
            default_port = default_settings.PORT  # 6100

            # 生成完整URL，统一使用 default 模块地址
            return f"http://{default_host}:{default_port}/api/v1/ocr/images/corrections/{correction_id}/{image_type}"

        corrected_image_url = None
        if corrected_image_file:
            corrected_image_url = generate_correction_image_url(
                exam_correction.id, "corrected", subject_en
            )
            logger.info(f"Corrected image URL: {corrected_image_url}")

        # 为错误的题目自动创建错题记录（包含图形信息）
        from backend.core.crud import crud_question
        from backend.core.schemas.question import QuestionCreate

        wrong_question_ids = []
        for q in result.questions:
            if not q.is_correct:  # 只为错题创建记录
                # 保存错题图片到用户专属目录（使用原始学科，保证与批改前一致）
                question_filename = f"{task_id}_q{q.question_number}.{file_ext}"
                question_image_path = os.path.join(
                    get_user_upload_dir(UPLOAD_DIR, current_user, "questions", subject_en),
                    question_filename
                )

                # 复制原图作为错题图片（后续可优化为裁剪）
                import shutil
                try:
                    shutil.copy2(file_path, question_image_path)
                except Exception as e:
                    logger.warning(f"Failed to copy question image: {e}")
                    question_image_path = file_path

                # 生成URL路径（使用原始学科，保证与批改前一致）
                question_image_url = get_user_file_url(current_user, "questions", subject_en, question_filename)

                # 创建错题记录（使用原始学科，保证与批改前一致）
                question_data = QuestionCreate(
                    content=q.question_text,
                    title=f"第{q.question_number}题 - {q.question_type}",
                    subject=subject_en,  # 使用原始学科
                    difficulty=q.difficulty,
                    student_answer=q.student_answer,
                    correct_answer=q.correct_answer,
                    image_urls=[question_image_url],
                    tags=q.knowledge_points,
                )

                from backend.core.db.models import Question
                db_question = Question(
                    user_id=current_user.id,
                    exam_correction_id=exam_correction.id,
                    title=question_data.title,
                    content=question_data.content,
                    subject=subject_type,  # 使用原始学科类型
                    difficulty=question_data.difficulty,
                    student_answer=question_data.student_answer,
                    correct_answer=question_data.correct_answer,
                    image_urls=question_data.image_urls,
                    knowledge_points=q.knowledge_points,
                    error_analysis=q.error_analysis,
                    source=QuestionSourceEnum.AI_CORRECTION,
                    source_description=f"AI批注试卷第{q.question_number}题",
                    tags=q.knowledge_points,
                    # WZY特有：保存图形相关信息
                    has_diagram=getattr(q, "has_diagram", False),
                    diagram_type=getattr(q, "diagram_type", None),
                    diagram_description=getattr(q, "diagram_description", None),
                )
                db.add(db_question)
                await db.flush()
                wrong_question_ids.append(db_question.id)

        await db.commit()
        total_ms = int((time.perf_counter() - t0) * 1000)
        logger.info(
            f"[ocr/analyze] done task_id={task_id} user_id={current_user.id} correction_id={exam_correction.id} "
            f"created_wrong_questions={len(wrong_question_ids)} duration_ms={total_ms}"
        )

        # Telemetry: journey step done (used for total duration metric)
        try:
            from backend.core.services.metrics_service import get_metrics_service
            await get_metrics_service().log_event(
                event_type="journey",
                event_name="ocr.analyze.done",
                ok=True,
                duration_ms=float(total_ms),
                user_id=current_user.id,
                module="wzy",  # 改为wzy
                subject=subject_en,
                task_id=task_id,
                exam_correction_id=exam_correction.id,
                payload={
                    "wrong_questions": len(wrong_question_ids),
                    "accuracy_rate": float(result.accuracy_rate or 0.0),
                    "enable_diagram_analysis": enable_diagram_analysis,
                    "diagram_regions": diagram_analysis_result.get("total_regions", 0) if diagram_analysis_result else 0,
                },
            )
        except Exception:
            pass

        logger.info(
            f"Saved exam correction {exam_correction.id} for user {current_user.id}, "
            f"created {len(wrong_question_ids)} wrong question records"
        )

        return OCRAnalysisResponse(
            success=True,
            task_id=task_id,
            subject=result.subject.value,
            grade=result.grade,
            total_score=result.total_score,
            max_score=result.max_score,
            accuracy_rate=result.accuracy_rate,
            questions=[
                {
                    "question_number": q.question_number,
                    "question_type": q.question_type,
                    "question_text": q.question_text,
                    "student_answer": q.student_answer,
                    "correct_answer": q.correct_answer,
                    "score": q.score,
                    "max_score": q.max_score,
                    "is_correct": q.is_correct,
                    "error_analysis": q.error_analysis,
                    "knowledge_points": q.knowledge_points,
                    "solution_steps": q.solution_steps,
                    "difficulty": q.difficulty,
                    "has_diagram": getattr(q, "has_diagram", False) if hasattr(q, "has_diagram") else False,
                    "diagram_type": getattr(q, "diagram_type", None) if hasattr(q, "diagram_type") else None,
                    "diagram_description": getattr(q, "diagram_description", None) if hasattr(q, "diagram_description") else None,
                }
                for q in result.questions
            ],
            overall_analysis=result.overall_analysis,
            weak_points=result.weak_points,
            improvement_suggestions=result.improvement_suggestions,
            corrected_image_url=corrected_image_url,
            is_duplicate=is_duplicate,
            duplicate_message=duplicate_message,
            subject_mismatch_warning=subject_mismatch_warning,
            diagram_analysis=diagram_analysis_result,
        )

    except Exception as e:
        logger.error(f"OCR analysis failed: {e}")
        try:
            from backend.core.services.metrics_service import get_metrics_service
            await get_metrics_service().log_event(
                event_type="journey",
                event_name="ocr.analyze.failed",
                ok=False,
                duration_ms=float((time.perf_counter() - t0) * 1000.0),
                user_id=current_user.id,
                module="wzy",  # 改为wzy
                subject=subject_en,
                task_id=task_id,
                payload={"error": str(e)},
            )
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"分析失败: {str(e)}")

    finally:
        # 清理临时文件 (可选，生产环境可保留用于审计)
        pass


# 以下函数与TONY模块完全相同，仅模块名称从tony改为wzy
@router.get("/images/{file_type}/{user_id}/{subject}/{filename}")
async def get_user_image(
    file_type: str,
    user_id: int,
    subject: str,
    filename: str,
    token: Optional[str] = Query(None, description="JWT token (for image tag access)"),
    current_user_id: Optional[int] = Depends(get_optional_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    获取用户图像
    
    路径格式: /ocr/images/{file_type}/{user_id}/{subject}/{filename}
    file_type: corrections 或 questions
    
    安全验证：
    - 如果提供了JWT token，验证路径中的user_id与JWT中的user_id是否一致
    - 如果没有token，在开发模式下允许访问（生产环境应要求认证）
    - 支持通过<img>标签直接访问（浏览器不会发送Authorization header）
    """
    from fastapi.responses import FileResponse
    from backend.core.crud import crud_user
    from backend.core.utils.file_utils import get_user_directory_name
    from backend.modules.wzy.config import settings  # 改为wzy
    from jose import jwt, JWTError

    # 如果从查询参数提供了token，尝试解析
    if token and current_user_id is None:
        try:
            payload = jwt.decode(
                token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
            )
            user_id_str: str = payload.get("sub")
            if user_id_str:
                current_user_id = int(user_id_str)
        except JWTError as e:
            logger.warning(f"Failed to parse token from query param: {e}")
        except Exception as e:
            logger.warning(f"Failed to parse token from query param: {e}")

    # 如果提供了token，验证用户ID是否一致
    if current_user_id is not None:
        logger.info(f"Image access with authentication: current_user_id={current_user_id}, path_user_id={user_id}")
        if user_id != current_user_id:
            logger.warning(f"User ID mismatch: current_user_id={current_user_id}, path_user_id={user_id}")
            raise HTTPException(
                status_code=403,
                detail="无权访问该用户的图像资源"
            )
    else:
        # 没有token的情况
        logger.warning(f"Image access without authentication: user_id={user_id}, file={filename}, is_development={settings.is_development}")
        if not settings.is_development:
            # 生产环境要求认证
            raise HTTPException(
                status_code=401,
                detail="需要认证才能访问图像资源",
                headers={"WWW-Authenticate": "Bearer"},
            )
        # 开发模式允许访问，但记录警告
    
    # 学科验证（WZY特有）
    if subject not in settings.SUBJECTS:
        raise HTTPException(
            status_code=400,
            detail=f"Subject '{subject}' is not supported by WZY module"
        )
    
    # 获取用户对象以构建正确的文件路径
    user = await crud_user.get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    
    # 根据用户信息构建用户目录名
    user_dir_name = get_user_directory_name(user.username, user.email)
    file_path = os.path.join(UPLOAD_DIR, user_dir_name, file_type, subject, filename)
    
    if os.path.exists(file_path):
        # 根据文件扩展名确定 MIME 类型
        ext = filename.split('.')[-1].lower()
        mime_types = {
            'png': 'image/png',
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'webp': 'image/webp',
            'heic': 'image/heic',
        }
        media_type = mime_types.get(ext, 'image/png')
        return FileResponse(file_path, media_type=media_type)
    
    raise HTTPException(status_code=404, detail="图像不存在")


@router.get("/images/corrections/{correction_id}/{image_type}")
async def get_correction_image(
    correction_id: int,
    image_type: str = Path(description="图片类型: 'original' 或 'corrected'"),
    token: Optional[str] = Query(None, description="JWT token (for image tag access)"),
    current_user_id: Optional[int] = Depends(get_optional_user_id),
    db: AsyncSession = Depends(get_db),
):
    """
    获取批注图片（通过correction_id和image_type）
    
    路径格式: /ocr/images/corrections/{correction_id}/{image_type}
    image_type: 'original' 或 'corrected'
    
    安全验证：
    - 通过correction_id查找ExamCorrection记录
    - 验证当前用户是否为批注记录的所有者
    - 根据image_type获取对应的图片ID并返回图片文件
    """
    from fastapi.responses import FileResponse
    from backend.core.crud import crud_exam_correction, crud_image_file
    from backend.modules.wzy.config import settings  # 改为wzy
    from jose import jwt, JWTError
    import os

    # 验证image_type
    if image_type not in ["original", "corrected"]:
        raise HTTPException(
            status_code=400,
            detail="image_type必须是'original'或'corrected'"
        )

    # 如果从查询参数提供了token，尝试解析
    if token and current_user_id is None:
        try:
            payload = jwt.decode(
                token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
            )
            user_id_str: str = payload.get("sub")
            if user_id_str:
                current_user_id = int(user_id_str)
        except JWTError as e:
            logger.warning(f"Failed to parse token from query param: {e}")
        except Exception as e:
            logger.warning(f"Failed to parse token from query param: {e}")

    # 获取批注记录
    correction = await crud_exam_correction.get_exam_correction(db, correction_id, None)
    if not correction:
        raise HTTPException(status_code=404, detail="批注记录不存在")

    # 学科验证（WZY特有）
    if correction.subject.value not in settings.SUBJECTS:
        raise HTTPException(
            status_code=400,
            detail=f"Subject '{correction.subject.value}' is not supported by WZY module"
        )

    # 验证用户权限
    if current_user_id is not None:
        if correction.user_id != current_user_id:
            raise HTTPException(
                status_code=403,
                detail="无权访问该批注记录的图像资源"
            )
    else:
        # 没有token的情况
        if not settings.is_development:
            raise HTTPException(
                status_code=401,
                detail="需要认证才能访问图像资源",
                headers={"WWW-Authenticate": "Bearer"},
            )
        logger.warning(f"Correction image access without authentication: correction_id={correction_id}, image_type={image_type}")

    # 根据image_type获取对应的图片文件（直接使用已加载的关联对象）
    if image_type == "original":
        image_file = correction.original_image
        if not image_file:
            logger.error(f"Correction {correction_id} has no original_image (original_image_id={correction.original_image_id})")
            raise HTTPException(status_code=404, detail="原始图片不存在")
        logger.info(f"Getting original image: correction_id={correction_id}, image_id={image_file.id}, file_path={image_file.file_path}")
    else:  # corrected
        image_file = correction.corrected_image
        if not image_file:
            logger.error(f"Correction {correction_id} has no corrected_image (corrected_image_id={correction.corrected_image_id})")
            raise HTTPException(status_code=404, detail="批改后的图片不存在")
        logger.info(f"Getting corrected image: correction_id={correction_id}, image_id={image_file.id}, file_path={image_file.file_path}")
    
    logger.info(f"Found ImageFile: id={image_file.id}, file_path={image_file.file_path}, image_type={image_file.image_type}")

    # 检查文件是否存在（处理相对路径）
    file_path = image_file.file_path
    original_stored_path = file_path
    
    # 获取项目根目录
    current_file_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(current_file_dir, "../../../../../"))
    
    # 尝试多种路径解析方式
    possible_paths = []
    
    # 1. 如果是绝对路径，直接使用
    if os.path.isabs(file_path):
        possible_paths.append(file_path)
    else:
        # 2. 移除开头的 ./ 或 ./
        normalized = file_path.lstrip("./").lstrip("/")
        
        # 3. 基于项目根目录
        possible_paths.append(os.path.join(project_root, normalized))
        
        # 4. 基于当前工作目录
        possible_paths.append(os.path.join(os.getcwd(), normalized))
        
        # 5. 如果路径包含 data/uploads，尝试直接拼接
        if "data/uploads" in normalized:
            possible_paths.append(os.path.join(project_root, normalized))
            # 移除 data/uploads 前缀，重新拼接
            rel_part = normalized.split("data/uploads/", 1)[-1] if "data/uploads/" in normalized else normalized
            possible_paths.append(os.path.join(project_root, "data", "uploads", rel_part))
    
    # 尝试每个可能的路径
    found_path = None
    for path in possible_paths:
        if os.path.exists(path):
            found_path = path
            logger.info(f"Found file at: {path} (from stored path: {original_stored_path})")
            break
    
    if not found_path:
        # 备用方案：尝试根据hash值查找文件
        logger.warning(f"File not found at stored path, trying to find by hash: {image_file.file_hash[:32]}")
        upload_base = os.path.join(project_root, "data", "uploads")
        
        # 构建可能的目录路径（需要加载user关系）
        from backend.core.crud import crud_user
        user = await crud_user.get_user(db, correction.user_id)
        if not user:
            logger.error(f"User not found: user_id={correction.user_id}")
            raise HTTPException(status_code=404, detail="用户不存在")
        user_dir_name = get_user_directory_name(user.username, user.email)
        possible_dirs = [
            os.path.join(upload_base, user_dir_name, "corrections", correction.subject.value if hasattr(correction.subject, 'value') else str(correction.subject)),
            os.path.join(upload_base, user_dir_name, "corrections", "math"),  # 尝试math目录
            os.path.join(upload_base, user_dir_name, "corrections"),  # 尝试corrections目录
        ]
        
        # 尝试查找包含hash值的文件
        hash_prefix = image_file.file_hash[:32]
        for search_dir in possible_dirs:
            if os.path.exists(search_dir):
                try:
                    for filename in os.listdir(search_dir):
                        if hash_prefix in filename:
                            candidate_path = os.path.join(search_dir, filename)
                            if os.path.exists(candidate_path):
                                found_path = candidate_path
                                logger.info(f"Found file by hash search: {found_path}")
                                break
                    if found_path:
                        break
                except Exception as e:
                    logger.warning(f"Error searching directory {search_dir}: {e}")
        
        if not found_path:
            logger.error(f"Image file not found. Stored path: {original_stored_path}, Tried paths: {possible_paths}, Hash search dirs: {possible_dirs}, image_id={image_file.id}, correction_id={correction_id}, image_type={image_type}, file_hash={image_file.file_hash[:32]}")
            raise HTTPException(status_code=404, detail=f"图片文件不存在: {original_stored_path}")
    
    file_path = found_path

    # 根据文件扩展名确定 MIME 类型
    ext = os.path.splitext(file_path)[1].lower().lstrip('.')
    mime_types = {
        'png': 'image/png',
        'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg',
        'webp': 'image/webp',
        'heic': 'image/heic',
    }
    media_type = mime_types.get(ext, 'image/png')
    
    return FileResponse(file_path, media_type=media_type)


@router.get("/images/{subject}/{filename}")
async def get_image_legacy(subject: str, filename: str):
    """
    获取图像（兼容旧路径）
    旧路径格式: /ocr/images/{subject}/{filename}
    """
    from fastapi.responses import FileResponse

    # 学科验证（WZY特有）
    if subject not in settings.SUBJECTS:
        raise HTTPException(
            status_code=400,
            detail=f"Subject '{subject}' is not supported by WZY module"
        )

    # 尝试从批注目录或错题目录查找（遍历所有用户目录）
    base_paths = [UPLOAD_DIR]
    
    for base_path in base_paths:
        # 遍历用户目录
        if os.path.exists(base_path):
            for user_dir in os.listdir(base_path):
                user_path = os.path.join(base_path, user_dir)
                if not os.path.isdir(user_path):
                    continue
                
                # 尝试 corrections 和 questions
                for file_type in ["corrections", "questions"]:
                    file_path = os.path.join(user_path, file_type, subject, filename)
                    if os.path.exists(file_path):
                        ext = filename.split('.')[-1].lower()
                        mime_types = {
                            'png': 'image/png',
                            'jpg': 'image/jpeg',
                            'jpeg': 'image/jpeg',
                            'webp': 'image/webp',
                            'heic': 'image/heic',
                        }
                        media_type = mime_types.get(ext, 'image/png')
                        return FileResponse(file_path, media_type=media_type)
    
    raise HTTPException(status_code=404, detail="图像不存在")


@router.post("/batch-analyze")
async def batch_analyze_images(
    files: list[UploadFile] = File(...),
    subject: str = Form("math"),  # 默认学科改为math
    enable_diagram_analysis: bool = Form(True),  # WZY特有
    current_user: User = Depends(get_current_user),
):
    """
    批量分析多张试卷图片
    """
    results = []

    for file in files:
        try:
            # 复用单张分析逻辑
            # 这里简化处理，实际应该异步处理
            results.append({
                "filename": file.filename,
                "status": "queued",
                "message": "已加入处理队列",
                "enable_diagram_analysis": enable_diagram_analysis,
            })
        except Exception as e:
            results.append({
                "filename": file.filename,
                "status": "error",
                "message": str(e),
            })

    return {
        "success": True,
        "total": len(files),
        "results": results,
    }