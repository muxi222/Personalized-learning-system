"""
OCR API 端点 - 试卷分析与批改 (Refactored)

功能:
1. 上传试卷图片进行 OCR 分析
2. 自动批改并打分
3. 生成批改后的图像
4. 安全的图像资源访问
"""

import os
import uuid
import logging
import shutil
from typing import Optional, Tuple
from pathlib import Path
import base64

# 引入异步文件操作库（学生模块环境可能未安装：保持可导入）
try:
    import aiofiles  # type: ignore
except Exception:  # pragma: no cover
    aiofiles = None

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends, Query, Path as PathParam, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from jose import jwt, JWTError

# 内部模块导入 (保持原样)
from backend.modules.tony.api.deps import get_current_user, get_optional_user_id, get_db
from backend.modules.tony.config import settings
from backend.core.services.gemini_ocr_service import (
    get_gemini_ocr_service,
    SubjectType,
    ExamAnalysisResult,
)
from backend.core.db.models import User, ImageFileTypeEnum, ExamCorrection, QuestionSourceEnum, Question
from backend.core.utils.file_utils import (
    get_user_directory_name,
    calculate_file_hash,
)
from backend.core.crud import crud_image_file, crud_exam_correction, crud_user

logger = logging.getLogger(__name__)
router = APIRouter()

def validate_subject(subject: str) -> None:
    """验证学科是否属于WZM模块"""
    if subject not in settings.SUBJECTS:
        raise HTTPException(
            status_code=400,
            detail=f"Subject '{subject}' is not supported by WZM module. "
                   f"Supported subjects: {settings.SUBJECTS}"
        )

# --- 配置常量 ---
# 使用 pathlib 定义根目录，自动处理系统差异
PROJECT_ROOT = Path(__file__).resolve().parents[5]  # 根据文件位置调整层级
UPLOAD_ROOT = Path("./data/uploads") # 相对运行目录
# 允许的图片类型
ALLOWED_MIME_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic"}

# 学科映射
SUBJECT_NAME_MAP = {
    "数学": "math", "英语": "english", "物理": "physics", "化学": "chemistry",
    "语文": "chinese", "生物": "biology", "政治": "politics",
    "经济学": "economics", "历史": "history", "地理": "geography", "其他": "other",
}

# --- 辅助函数 ---

async def save_file_async(content: bytes, file_path: Path):
    """异步保存文件，自动创建父目录"""
    try:
        if not file_path.parent.exists():
            file_path.parent.mkdir(parents=True, exist_ok=True)
        # aiofiles 不存在时降级为同步写入（学生TODO：补齐依赖或改为线程池）
        if aiofiles is None:
            with open(file_path, "wb") as f:
                f.write(content)
        else:
            async with aiofiles.open(file_path, "wb") as f:
                await f.write(content)
    except Exception as e:
        logger.error(f"Async file save failed: {e}")
        raise HTTPException(status_code=500, detail="文件保存失败")

def get_clean_relative_path(full_path: Path) -> str:
    """
    将绝对路径或复杂路径转换为相对于 uploads 目录的清洁路径
    用于存入数据库，格式如: user_x/corrections/math/abc.jpg
    """
    try:
        # 尝试相对于 UPLOAD_ROOT 取路径
        return str(full_path.relative_to(UPLOAD_ROOT))
    except ValueError:
        # 如果路径不在 UPLOAD_ROOT 下（容错），尝试清洗
        path_str = str(full_path).replace("\\", "/")
        if "data/uploads/" in path_str:
            return path_str.split("data/uploads/")[-1]
        return path_str

def generate_api_url(path: str) -> str:
    """生成相对 API URL，解耦域名和端口"""
    return f"/api/v1/ocr{path}"

# --- 依赖项 (Dependencies) ---

async def verify_image_access(
    token: Optional[str] = Query(None),
    current_user_id: Optional[int] = Depends(get_optional_user_id),
) -> int:
    """
    统一图片访问鉴权。
    优先检查 Header 中的 Token (通过 Depends 获取)，
    其次检查 Query Param 中的 Token (用于 img 标签)。
    返回 user_id，如果未认证且非开发环境则抛出异常。
    """
    # 1. Header 认证成功
    if current_user_id is not None:
        return current_user_id

    # 2. Query Param 认证 (手动解析)
    if token:
        try:
            payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
            user_id_str: str = payload.get("sub")
            if user_id_str:
                return int(user_id_str)
        except JWTError:
            logger.warning("Invalid token in query param")

    # 3. 开发环境豁免 (返回 -1 标识)
    if settings.is_development:
        return -1

    raise HTTPException(
        status_code=401,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )

# --- Pydantic Models ---

class OCRAnalysisResponse(BaseModel):
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
    is_duplicate: bool = False
    duplicate_message: Optional[str] = None

# --- API Endpoints ---

@router.post("/analyze", response_model=OCRAnalysisResponse)
async def analyze_exam_image(
    file: UploadFile = File(...),
    subject: str = Form("other"),
    grade: str = Form(""),
    hint: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    分析试卷图片：上传 -> 异步保存 -> OCR -> 批改 -> 存库
    """
    # 1. 验证文件
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型。支持: {ALLOWED_MIME_TYPES}")

    subject_en = SUBJECT_NAME_MAP.get(subject, subject.lower())
    content = await file.read()
    file_hash = calculate_file_hash(content)
    task_id = str(uuid.uuid4())

    # 2. 检查去重
    existing_image = await crud_image_file.get_image_by_hash(db, file_hash)
    is_duplicate = False
    duplicate_msg = None

    # 构建用户目录路径: ./data/uploads/{user}/corrections/{subject}/
    user_dir_name = get_user_directory_name(current_user.username, current_user.email)
    base_save_dir = UPLOAD_ROOT / user_dir_name / "corrections" / subject_en

    # 3. 处理原始图片 (Original Image)
    if existing_image and existing_image.user_id == current_user.id:
        is_duplicate = True
        duplicate_msg = "检测到重复图片，使用已有记录分析"
        original_image_file = existing_image
        file_path_obj = UPLOAD_ROOT / existing_image.file_path # 拼回完整路径
        await crud_image_file.increment_reference_count(db, file_hash)
    else:
        # 新文件保存
        file_ext = file.filename.split(".")[-1] if file.filename else "jpg"
        filename = f"{file_hash[:32]}.{file_ext}"
        file_path_obj = base_save_dir / filename

        await save_file_async(content, file_path_obj)

        # 存入相对路径
        relative_path = get_clean_relative_path(file_path_obj)

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

    # 记录临时文件用于回滚
    files_to_rollback = [] if is_duplicate else [file_path_obj]

    try:
        # 4. 调用 OCR 服务
        ocr_service = get_gemini_ocr_service()
        await ocr_service.initialize()

        # Gemini 调用
        analysis_result = await ocr_service.analyze_exam_image(
            image_path=str(file_path_obj), # 传递字符串路径
            subject=SubjectType(subject_en) if subject_en in SubjectType.__members__ else SubjectType.OTHER,
            grade=grade,
            user_hint=hint,
        )

        # TODO(student): 学科判定 + 分类归一化（统一模板 v1；不要在此处直接实现，留给学生）
        # 【输入】user_selected_subject=subject_en，text=OCR提取出的题目文本/结构化题目
        # 【输出】对每题生成：
        #   - detected_subject + confidence(0~1)
        #   - chapter: 从 CHAPTER_TAXONOMY[detected_subject] 选 1 个（否则“综合”）
        #   - knowledge_points: 从 KNOWLEDGE_POINT_TAXONOMY[detected_subject] 选 1~3 个（否则“综合”）
        #   - tags: 2~6 个短词（用于检索，避免太碎）
        # 【规则】
        #   - 若 detected_subject != user_selected_subject 且 confidence >= 0.75：提示“学科不匹配”并拒绝返回批改结果
        #   - taxonomy 必须收敛：chapter 建议 6~10 个，knowledge_points 建议 10~25 个；同义项合并，避免发散
        # 【推荐 taxonomy 示例（WZM: chemistry）】
        #   CHAPTER_TAXONOMY = {
        #     "chemistry": ["物质结构", "化学反应原理", "无机化学", "有机化学", "实验与探究", "计算与守恒", "综合"],
        #   }
        #   KNOWLEDGE_POINT_TAXONOMY = {
        #     "chemistry": ["氧化还原", "化学平衡", "电化学", "酸碱盐", "物质结构与性质", "官能团与有机反应", "实验操作与安全", "定量计算", "综合"],
        #   }
        # 【实现建议】
        #   - OCR 后调用 settings.LLM_API_ENDPOINT 的 /chat/completions（二次判定+归一化）
        #   - 优先更强模型（gemini-3-pro-preview / gpt-5.2），可通过环境变量 WZM_HIGH_ACCURACY_MODEL 覆盖
        # 【参考实现】backend/modules/tony/agents/question_intake_ocr_agent.py（仅 tony 模块完整实现）

        # 5. 生成批改图片 (Corrected Image)
        correction_overlay = await ocr_service.create_correction_overlay(
            image_path=str(file_path_obj),
            analysis_result=analysis_result,
        )

        corrected_image_file = None
        if correction_overlay.success and correction_overlay.corrected_image_base64:
            corrected_bytes = base64.b64decode(correction_overlay.corrected_image_base64)
            corrected_hash = calculate_file_hash(corrected_bytes)

            # 检查批改图是否存在
            existing_corr = await crud_image_file.get_image_by_hash(db, corrected_hash)

            if existing_corr:
                corrected_image_file = existing_corr
                await crud_image_file.increment_reference_count(db, corrected_hash)
            else:
                corr_filename = f"{corrected_hash[:32]}.png"
                corr_path_obj = base_save_dir / corr_filename

                await save_file_async(corrected_bytes, corr_path_obj)
                files_to_rollback.append(corr_path_obj) # 加入回滚列表

                corr_relative_path = get_clean_relative_path(corr_path_obj)

                corrected_image_file = await crud_image_file.create_image_file(
                    db=db,
                    file_hash=corrected_hash,
                    user_id=current_user.id,
                    file_type="corrections",
                    subject=subject_en,
                    file_path=corr_relative_path,
                    file_size=len(corrected_bytes),
                    mime_type="image/png",
                    image_type=ImageFileTypeEnum.CORRECTED,
                    original_image_id=original_image_file.id,
                )

        # 6. 保存批注记录 (Correction Record)
        exam_correction = ExamCorrection(
            user_id=current_user.id,
            subject=analysis_result.subject,
            grade=grade or analysis_result.grade,
            exam_title=hint or f"{subject_en}试卷批改",
            original_image_id=original_image_file.id,
            corrected_image_id=corrected_image_file.id if corrected_image_file else None,
            total_score=analysis_result.total_score,
            max_score=analysis_result.max_score,
            accuracy_rate=analysis_result.accuracy_rate,
            question_count=len(analysis_result.questions),
            correct_count=sum(1 for q in analysis_result.questions if q.is_correct),
            wrong_count=sum(1 for q in analysis_result.questions if not q.is_correct),
            overall_analysis=analysis_result.overall_analysis,
            weak_points=analysis_result.weak_points,
            improvement_suggestions=analysis_result.improvement_suggestions,
            questions_detail=[q.dict() for q in analysis_result.questions],
        )
        db.add(exam_correction)
        await db.flush() # 获取 ID

        # 7. 处理错题 (Wrong Questions)
        questions_dir = UPLOAD_ROOT / user_dir_name / "questions" / subject_en

        for q in analysis_result.questions:
            if not q.is_correct:
                q_filename = f"{task_id}_q{q.question_number}.{file_ext}"
                q_path_obj = questions_dir / q_filename

                # 异步复制错题图 (如果是在同一个卷上，其实可以复用 aiofiles 读取写入，这里用 shutil 简化)
                # 注意：shutil 是同步的，为了不阻塞，这里做个简单处理
                # 生产环境建议使用 aiofiles 读取原图 bytes 再写入
                if not q_path_obj.parent.exists():
                    q_path_obj.parent.mkdir(parents=True, exist_ok=True)

                # 复制原图到新位置（aiofiles 不存在时降级为同步复制）
                if aiofiles is None:
                    shutil.copyfile(file_path_obj, q_path_obj)
                else:
                    async with aiofiles.open(file_path_obj, "rb") as src, aiofiles.open(q_path_obj, "wb") as dst:
                        await dst.write(await src.read())

                files_to_rollback.append(q_path_obj)

                # 生成 URL
                q_img_url = generate_api_url(f"/images/questions/{current_user.id}/{subject_en}/{q_filename}")

                db_question = Question(
                    user_id=current_user.id,
                    exam_correction_id=exam_correction.id,
                    title=f"第{q.question_number}题 - {q.question_type}",
                    content=q.question_text,
                    subject=analysis_result.subject,
                    difficulty=q.difficulty,
                    student_answer=q.student_answer,
                    correct_answer=q.correct_answer,
                    image_urls=[q_img_url],
                    knowledge_points=q.knowledge_points,
                    error_analysis=q.error_analysis,
                    source=QuestionSourceEnum.AI_CORRECTION,
                    source_description=f"AI批注试卷第{q.question_number}题",
                    tags=q.knowledge_points,
                )
                db.add(db_question)

        await db.commit()

        # 返回结果
        corr_url = None
        if corrected_image_file:
            # 返回统一的 API 路径
            corr_url = generate_api_url(f"/images/corrections/{exam_correction.id}/corrected")

        return OCRAnalysisResponse(
            success=True,
            task_id=task_id,
            subject=analysis_result.subject.value,
            grade=analysis_result.grade,
            total_score=analysis_result.total_score,
            max_score=analysis_result.max_score,
            accuracy_rate=analysis_result.accuracy_rate,
            questions=[q.dict() for q in analysis_result.questions],
            overall_analysis=analysis_result.overall_analysis,
            weak_points=analysis_result.weak_points,
            improvement_suggestions=analysis_result.improvement_suggestions,
            corrected_image_url=corr_url,
            is_duplicate=is_duplicate,
            duplicate_message=duplicate_msg,
        )

    except Exception as e:
        await db.rollback()
        logger.error(f"Analysis failed: {e}")
        # 回滚文件：删除刚才创建的所有文件
        for path in files_to_rollback:
            if path.exists():
                try:
                    os.remove(path)
                except OSError:
                    pass
        raise HTTPException(status_code=500, detail=f"分析失败: {str(e)}")

@router.get("/images/corrections/{correction_id}/{image_type}")
async def get_correction_image(
    correction_id: int,
    image_type: str = PathParam(..., regex="^(original|corrected)$"),
    access_user_id: int = Depends(verify_image_access),
    db: AsyncSession = Depends(get_db),
):
    """
    获取批注相关图片（安全优化版）
    """
    # 1. 查询记录
    correction = await crud_exam_correction.get_exam_correction(db, correction_id, None)
    if not correction:
        raise HTTPException(status_code=404, detail="记录不存在")

    # 2. 权限校验 (开发模式 access_user_id 为 -1 时跳过)
    if access_user_id != -1 and correction.user_id != access_user_id:
        raise HTTPException(status_code=403, detail="无权访问此资源")

    # 3. 获取对应的图片文件记录
    image_file = correction.original_image if image_type == "original" else correction.corrected_image
    if not image_file:
        raise HTTPException(status_code=404, detail="图片未生成")

    # 4. 路径解析 (核心修复)
    # 数据库存的可能是 "user/corrections/math/xxx.jpg"
    stored_path_str = image_file.file_path

    # 清洗路径：移除可能的 ../ 或 ./ 前缀，只保留相对部分
    # 注意：这里假设数据库里存的是相对路径。如果是绝对路径需要特殊处理。
    clean_path = Path(stored_path_str.lstrip("./").lstrip("/"))
    if str(clean_path).startswith("data/uploads/"):
        # 如果存了 data/uploads 前缀，去掉它，因为 UPLOAD_ROOT 已经包含了
        clean_path = Path(str(clean_path).replace("data/uploads/", "", 1))

    full_disk_path = UPLOAD_ROOT / clean_path

    if not full_disk_path.exists():
        logger.error(f"File missing on disk: {full_disk_path} (DB ID: {image_file.id})")
        raise HTTPException(status_code=404, detail="文件丢失")

    # 5. 确定 MIME 类型
    ext = full_disk_path.suffix.lower().lstrip('.')
    media_type = f"image/{ext}" if ext != 'jpg' else 'image/jpeg'

    return FileResponse(full_disk_path, media_type=media_type)

@router.get("/images/{file_type}/{user_id}/{subject}/{filename}")
async def get_user_image(
    file_type: str = PathParam(..., regex="^(corrections|questions)$"),
    user_id: int = PathParam(...),
    subject: str = PathParam(...),
    filename: str = PathParam(...),
    access_user_id: int = Depends(verify_image_access),
    db: AsyncSession = Depends(get_db),
):
    """
    通用用户图片获取接口 (兼容错题图片)
    """
    # 权限校验
    if access_user_id != -1 and user_id != access_user_id:
         raise HTTPException(status_code=403, detail="无权访问")

    # 获取用户信息以构建目录名
    user = await crud_user.get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 构建路径
    user_dir = get_user_directory_name(user.username, user.email)

    # 安全检查：防止 filename 包含 ".." 进行路径遍历
    safe_filename = Path(filename).name

    file_path = UPLOAD_ROOT / user_dir / file_type / subject / safe_filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="图片不存在")

    return FileResponse(file_path)

@router.post("/batch-analyze")
async def batch_analyze_images(
    files: list[UploadFile] = File(...),
):
    """批量接口占位符"""
    return {"message": "Batch analysis not implemented yet", "count": len(files)}

# ============================================================
# TODO: 学生需要实现以下API endpoints
# ============================================================
#
# 请参考完整实现: backend/modules/tony/api/endpoints/ocr.py
#
# 实现步骤:
# 1. 复制TONY模块对应文件的函数签名和路由装饰器
# 2. 保留学科验证逻辑 (validate_subject)
# 3. 实现业务逻辑（数据库查询、Agent调用等）
# 4. 返回正确的响应数据
#
# 提示:
# - 所有数据库操作使用 backend/core/crud/ 中的函数
# - 所有Agent操作使用 backend/modules/wzm/agents/ 中的类
# - 所有Schema使用 backend/core/schemas/ 中的定义
# ============================================================

# TODO: 在这里添加endpoint实现
# 示例:
# @router.get("/example")
# async def example_endpoint():
#     """示例端点"""
#     return {"message": "学生TODO: 实现此endpoint"}
