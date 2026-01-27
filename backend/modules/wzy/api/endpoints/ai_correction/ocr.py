"""
OCR API 端点 - 试卷分析与批改（WZY模块）
支持数学和物理学科

功能:
1. 上传试卷图片进行 OCR 分析
2. 自动批改并打分
3. 生成批改后的图像
"""

import os
import uuid
import logging
import time
from typing import Optional, Dict, Any
from datetime import datetime
import json
import re

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends, Query, Path
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.modules.wzy.api.deps import get_current_user, get_current_user_id, get_optional_user_id, get_db, oauth2_scheme
from backend.modules.wzy.config import settings
from backend.core.services.gemini_ocr_service import (
    get_gemini_ocr_service,
    SubjectType,
    ExamAnalysisResult,
)
from backend.core.db.models import User, ExamCorrection, ImageFile
from backend.core.utils.file_utils import (
    get_user_upload_dir,
    get_user_file_url,
    get_user_directory_name,
    calculate_file_hash,
    get_filename_from_path,
)
from backend.core.crud import crud_image_file, crud_exam_correction

logger = logging.getLogger(__name__)
router = APIRouter()

UPLOAD_DIR = "./data/uploads"

def generate_correction_image_url(correction_id: int, image_type: str, subject: str) -> str:
    """
    生成批改图片URL（统一由 default 模块处理）
    """
    from backend.modules.wzy.config import settings

    # 优先使用 PUBLIC_API_BASE_URL 配置
    if settings.PUBLIC_API_BASE_URL:
        base_url = settings.PUBLIC_API_BASE_URL.rstrip('/')
        return f"{base_url}/api/v1/ocr/images/corrections/{correction_id}/{image_type}"

    # 如果没有设置 PUBLIC_API_BASE_URL，使用 default 模块的地址（6100端口）
    from backend.modules.default.config import get_settings as get_default_settings
    default_settings = get_default_settings()
    default_host = default_settings.HOST if default_settings.HOST not in ['0.0.0.0', ''] else 'localhost'
    default_port = default_settings.PORT  # 6100

    return f"http://{default_host}:{default_port}/api/v1/ocr/images/corrections/{correction_id}/{image_type}"

# 中文学科名称到英文的映射
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
    is_duplicate: bool = False
    duplicate_message: Optional[str] = None
    is_previous_correction: bool = False
    correction_id: Optional[int] = None


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


async def get_existing_correction_by_image_hash(db: AsyncSession, file_hash: str, user_id: int, subject: str) -> Optional[ExamCorrection]:
    """
    根据图片哈希值查找已有的批注记录
    
    优化：直接通过数据库查询，避免遍历所有记录
    """
    try:
        # 首先查找图片文件记录
        stmt = select(ImageFile).where(
            ImageFile.file_hash == file_hash,
            ImageFile.user_id == user_id
        )
        result = await db.execute(stmt)
        image_file = result.scalar_one_or_none()
        
        if not image_file:
            return None
        
        # 直接查询使用该图片作为原始图片的批注记录
        stmt = select(ExamCorrection).where(
            ExamCorrection.original_image_id == image_file.id,
            ExamCorrection.user_id == user_id
        ).order_by(ExamCorrection.created_at.desc()).limit(1)
        
        result = await db.execute(stmt)
        correction = result.scalar_one_or_none()
        
        if correction:
            # 检查学科是否匹配
            correction_subject = correction.subject.value if hasattr(correction.subject, 'value') else str(correction.subject)
            if correction_subject.lower() == subject.lower():
                return correction
        
        return None
        
    except Exception as e:
        logger.error(f"查找历史批注记录失败: {e}")
        return None


async def detect_subject_from_image_advanced(image_content: bytes, selected_subject: str) -> Dict[str, Any]:
    """
    使用高级方法检测图片内容是否为数学或物理学科
    
    返回包含检测结果的字典
    """
    result = {
        "detected_subject": None,
        "confidence": 0.0,
        "reasoning": "",
        "should_reject": False
    }
    
    try:
        # 尝试导入pytesseract进行OCR
        try:
            import pytesseract
        except ImportError:
            logger.warning("pytesseract未安装，跳过学科检测")
            result["reasoning"] = "pytesseract未安装，跳过学科检测"
            return result
            
        import tempfile
        from PIL import Image
        
        # 创建临时文件
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp_file:
            tmp_file.write(image_content)
            tmp_path = tmp_file.name
        
        try:
            # 使用Tesseract进行OCR
            img = Image.open(tmp_path)
            
            # 调整图片大小以优化OCR识别
            if img.size[0] > 2000 or img.size[1] > 2000:
                img = img.resize((img.size[0] // 2, img.size[1] // 2))
            
            # 进行OCR识别
            ocr_text = pytesseract.image_to_string(img, lang='chi_sim+eng')
            
            # 保存OCR文本用于分析
            ocr_text_lower = ocr_text.lower()
            logger.info(f"OCR提取到 {len(ocr_text)} 个字符")
            
            # 1. 检查是否有明确的学科标识
            subject_indicators = {
                "math": ["数学", "math", "mathematics"],
                "physics": ["物理", "physics", "物理试卷"]
            }
            
            # 2. 检查特征词汇（更精确的分类）
            # 数学特有特征
            math_specific = [
                # 几何相关
                "几何", "三角形", "圆形", "正方形", "长方形", "平行四边形", "梯形", "菱形",
                "长方体", "正方体", "圆柱", "圆锥", "球体",
                # 代数相关
                "代数", "方程", "不等式", "函数", "解析式", "定义域", "值域",
                "单调性", "奇偶性", "周期性", "对称性",
                # 数学概念
                "集合", "映射", "向量", "矩阵", "行列式", "概率", "统计",
                "排列", "组合", "数列", "极限", "导数", "积分", "微分",
                # 数学操作
                "证明", "求证", "化简", "因式分解", "配方", "求导", "积分",
                # 数学符号（在文本中可能以单词形式出现）
                "正弦", "余弦", "正切", "余切", "对数", "指数", "幂",
            ]
            
            # 物理特有特征
            physics_specific = [
                # 物理分支
                "力学", "电学", "磁学", "光学", "热学", "声学", "原子物理",
                # 物理概念
                "力", "质量", "重量", "重力", "弹力", "摩擦力", "压力",
                "浮力", "压强", "密度", "速度", "加速度", "动量", "动能",
                "势能", "机械能", "功", "功率", "电流", "电压", "电阻",
                "电容", "电感", "电路", "磁场", "电场", "电磁波", "光速",
                "温度", "热量", "内能", "比热容", "熔解", "凝固", "汽化",
                # 物理现象和实验
                "实验", "测量", "观察", "数据", "图表", "图像", "曲线",
                "牛顿定律", "欧姆定律", "焦耳定律", "能量守恒", "动量守恒",
                # 物理单位和符号
                "牛顿", "焦耳", "瓦特", "帕斯卡", "伏特", "安培", "欧姆",
                "赫兹", "摄氏度", "开尔文",
            ]
            
            # 3. 检查公式特征
            # 数学公式常见模式
            math_formula_patterns = [
                r'f\(x\)\s*=', r'g\(x\)\s*=', r'h\(x\)\s*=',
                r'∫_[^{]+\^{[^}]+}', r'∑_[^{]+\^{[^}]+}',
                r'lim_{[^}]+}', r'log_[^{]+\{[^}]+\}',
                r'sin\([^)]+\)', r'cos\([^)]+\)', r'tan\([^)]+\)',
                r'△[A-Z]{3}', r'∠[A-Z]{3}', r'⊙[A-Z]',
            ]
            
            # 物理公式常见模式
            physics_formula_patterns = [
                r'F\s*=\s*ma', r'v\s*=\s*s/t', r'a\s*=\s*Δv/Δt',
                r'W\s*=\s*Fs', r'P\s*=\s*W/t', r'E\s*=\s*mc²',
                r'U\s*=\s*IR', r'P\s*=\s*UI', r'F\s*=\s*BIL',
                r'f\s*=\s*1/T', r'λ\s*=\s*v/f', r'n\s*=\s*c/v',
                r'Q\s*=\s*cmΔt', r'PV\s*=\s*nRT',
            ]
            
            # 4. 统计特征
            math_score = 0
            physics_score = 0
            
            # 检查学科标识
            for indicator in subject_indicators.get("math", []):
                if indicator.lower() in ocr_text_lower:
                    math_score += 3
                    result["reasoning"] += f"找到数学标识: {indicator}; "
            
            for indicator in subject_indicators.get("physics", []):
                if indicator.lower() in ocr_text_lower:
                    physics_score += 3
                    result["reasoning"] += f"找到物理标识: {indicator}; "
            
            # 检查特有词汇
            for word in math_specific:
                if word.lower() in ocr_text_lower:
                    math_score += 1
            
            for word in physics_specific:
                if word.lower() in ocr_text_lower:
                    physics_score += 1
            
            # 检查公式模式
            for pattern in math_formula_patterns:
                if re.search(pattern, ocr_text):
                    math_score += 2
            
            for pattern in physics_formula_patterns:
                if re.search(pattern, ocr_text):
                    physics_score += 2
            
            # 5. 检查单位符号
            # 物理特有单位
            physics_units = ['m/s', 'm/s²', 'N', 'J', 'W', 'Pa', 'Hz', 'Ω', 'V', 'A', 'C', 'F', 'H', 'T', 'K']
            for unit in physics_units:
                if unit in ocr_text:
                    physics_score += 1
            
            # 6. 分析结果
            logger.info(f"学科检测得分: 数学={math_score}, 物理={physics_score}")
            
            if math_score > physics_score and math_score >= 3:
                result["detected_subject"] = "math"
                result["confidence"] = min(0.9, math_score / 20.0)
                result["reasoning"] += f"数学特征更明显(得分:{math_score} vs {physics_score})"
            elif physics_score > math_score and physics_score >= 3:
                result["detected_subject"] = "physics"
                result["confidence"] = min(0.9, physics_score / 20.0)
                result["reasoning"] += f"物理特征更明显(得分:{physics_score} vs {math_score})"
            elif math_score > 0 or physics_score > 0:
                result["detected_subject"] = None
                result["confidence"] = 0.3
                result["reasoning"] += "检测到学科特征但不明显"
            else:
                result["detected_subject"] = None
                result["confidence"] = 0.1
                result["reasoning"] = "未检测到明显的学科特征"
            
            # 7. 判断是否应该拒绝
            if result["detected_subject"] and result["detected_subject"] != selected_subject:
                if result["confidence"] >= 0.6:
                    result["should_reject"] = True
                elif result["confidence"] >= 0.4:
                    # 中等置信度，记录但不拒绝
                    result["should_reject"] = False
                    result["reasoning"] += f" (置信度中等，继续处理)"
                else:
                    result["should_reject"] = False
                    result["reasoning"] += f" (置信度低，继续处理)"
                
        except Exception as e:
            logger.warning(f"学科检测失败: {e}")
            result["reasoning"] = f"学科检测失败: {str(e)}"
        finally:
            # 清理临时文件
            try:
                os.unlink(tmp_path)
            except:
                pass
                
    except Exception as e:
        logger.warning(f"学科检测过程异常: {e}")
        result["reasoning"] = f"学科检测过程异常: {str(e)}"
    
    return result


@router.post("/analyze", response_model=OCRAnalysisResponse)
async def analyze_exam_image(
    file: UploadFile = File(...),
    subject: str = Form("math"),  # WZY默认学科为数学
    grade: str = Form(""),
    hint: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    分析试卷图片（WZY模块，支持数学和物理）
    
    上传试卷图片，使用 Gemini 2.5 Flash 进行:
    1. OCR 识别题目和答案
    2. 自动批改打分
    3. 错因分析
    4. 生成学习建议
    
    优化点：
    1. 检查历史记录，避免重复处理
    2. 学科验证：检查图片是否为数学/物理学科
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
        f"filename={file.filename} content_type={file.content_type}"
    )

    # WZY模块学科验证（仅支持数学和物理）
    if subject_en not in ["math", "physics"]:
        raise HTTPException(
            status_code=400,
            detail=f"WZY模块仅支持数学(math)和物理(physics)学科，当前选择: {subject}"
        )

    # 读取文件内容并计算哈希值
    content = await file.read()
    file_hash = calculate_file_hash(content)
    logger.info(
        f"[ocr/analyze] file loaded user_id={current_user.id} bytes={len(content)} hash={file_hash[:16]}..."
    )

    # ===== 优化1: 检查是否存在历史批注记录 =====
    existing_correction = await get_existing_correction_by_image_hash(db, file_hash, current_user.id, subject_en)
    
    if existing_correction:
        # 直接返回历史批注记录
        logger.info(
            f"[ocr/analyze] 检测到历史批注记录 user_id={current_user.id} correction_id={existing_correction.id} "
            f"subject={subject_en} total_score={existing_correction.total_score}"
        )
        
        # 生成批改图片URL
        corrected_image_url = None
        if existing_correction.corrected_image_id:
            corrected_image_url = generate_correction_image_url(
                existing_correction.id, "corrected", subject_en
            )
        
        # 构建响应
        return OCRAnalysisResponse(
            success=True,
            task_id=str(uuid.uuid4()),
            subject=existing_correction.subject.value if hasattr(existing_correction.subject, 'value') else str(existing_correction.subject),
            grade=existing_correction.grade or "",
            total_score=existing_correction.total_score,
            max_score=existing_correction.max_score,
            accuracy_rate=existing_correction.accuracy_rate,
            questions=existing_correction.questions_detail,
            overall_analysis=existing_correction.overall_analysis,
            weak_points=existing_correction.weak_points,
            improvement_suggestions=existing_correction.improvement_suggestions,
            corrected_image_url=corrected_image_url,
            is_duplicate=True,
            duplicate_message="您已提交过同一份图片，已调用上次判题记录",
            is_previous_correction=True,
            correction_id=existing_correction.id,
        )

    # ===== 优化2: 判题前识别是否是数学/物理学科 =====
    # 使用高级方法检测学科
    subject_detection_result = await detect_subject_from_image_advanced(content, subject_en)
    
    logger.info(
        f"[ocr/analyze] 学科检测结果 user_id={current_user.id} "
        f"selected={subject_en} detected={subject_detection_result['detected_subject']} "
        f"confidence={subject_detection_result['confidence']} "
        f"reasoning={subject_detection_result['reasoning'][:100]}..."
    )
    
    if subject_detection_result["should_reject"]:
        # 检测到的学科与用户选择的不一致，且置信度高
        detected = subject_detection_result["detected_subject"]
        confidence = subject_detection_result["confidence"]
        
        logger.warning(
            f"[ocr/analyze] 学科检测不一致需要拒绝 user_id={current_user.id} "
            f"selected={subject_en} detected={detected} confidence={confidence}"
        )
        
        # 提供友好的错误信息
        if detected == 'math':
            error_message = f"检测到图片内容为数学试卷（置信度{confidence:.1%}），但您选择了物理学科。请确认学科选择是否正确。"
        elif detected == 'physics':
            error_message = f"检测到图片内容为物理试卷（置信度{confidence:.1%}），但您选择了数学学科。请确认学科选择是否正确。"
        else:
            error_message = "检测到图片内容可能不是数学或物理试卷，请确认您上传的是正确的学科试卷。"
        
        # 返回错误，让用户确认
        raise HTTPException(
            status_code=400,
            detail=error_message
        )
    
    # 如果检测不到学科或置信度不够高，继续处理，由后续的完整OCR验证

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
            module="wzy",
            subject=subject_en,
            task_id=task_id,
            payload={
                "filename": file.filename,
                "content_type": file.content_type,
                "is_duplicate": bool(is_duplicate),
                "is_previous_correction": False,
                "subject_detection": subject_detection_result,
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
        
        # 设置超时时间
        import httpx
        from httpx import Timeout
        
        # 保存原来的timeout设置
        original_timeout = getattr(ocr_service, '_client_timeout', None)
        
        # 设置超时时间
        if hasattr(ocr_service, '_client'):
            ocr_service._client.timeout = Timeout(60.0, connect=10.0, read=60.0, write=10.0, pool=10.0)
        
        try:
            result = await ocr_service.analyze_exam_image(
                image_path=file_path,
                subject=subject_type,
                grade=grade,
                user_hint=hint,
            )
        finally:
            # 恢复原来的timeout设置
            if hasattr(ocr_service, '_client') and original_timeout:
                ocr_service._client.timeout = original_timeout
        
        analyze_ms = int((time.perf_counter() - t_analyze0) * 1000)
        
        logger.info(
            f"[ocr/analyze] task_id={task_id} user_id={current_user.id} analyze done duration_ms={analyze_ms} "
            f"questions={len(result.questions or [])} accuracy={result.accuracy_rate} total={result.total_score}/{result.max_score}"
        )

        # ===== 检查OCR分析结果是否有效 =====
        if not hasattr(result, 'questions'):
            logger.error(f"[ocr/analyze] task_id={task_id} user_id={current_user.id} OCR分析失败：result对象没有questions属性")
            raise HTTPException(
                status_code=500,
                detail="OCR服务返回无效结果，请稍后重试或联系管理员"
            )
            
        questions_list = result.questions
        
        if questions_list is None:
            logger.error(f"[ocr/analyze] task_id={task_id} user_id={current_user.id} OCR分析失败：result.questions为None")
            raise HTTPException(
                status_code=500,
                detail="OCR服务返回无效结果，请稍后重试或联系管理员"
            )
            
        if not isinstance(questions_list, list):
            logger.error(f"[ocr/analyze] task_id={task_id} user_id={current_user.id} OCR分析失败：result.questions不是列表类型，实际类型: {type(questions_list)}")
            raise HTTPException(
                status_code=500,
                detail="OCR服务返回数据格式错误，请稍后重试或联系管理员"
            )
            
        if len(questions_list) == 0:
            logger.error(f"[ocr/analyze] task_id={task_id} user_id={current_user.id} OCR分析失败：未识别到任何题目")
            
            # 检查是否有分析文本内容
            has_content = (
                (hasattr(result, 'overall_analysis') and result.overall_analysis and len(result.overall_analysis.strip()) > 0) or
                (hasattr(result, 'weak_points') and result.weak_points and len(result.weak_points) > 0) or
                (hasattr(result, 'improvement_suggestions') and result.improvement_suggestions and len(result.improvement_suggestions) > 0)
            )
            
            if not has_content:
                error_msg = "OCR分析失败：服务暂时不可用，请稍后重试或联系管理员"
            else:
                error_msg = "OCR分析失败：识别到分析内容但未识别到具体题目。可能是OCR服务超时或图片格式问题，请稍后重试。"
            
            raise HTTPException(
                status_code=500,
                detail=error_msg
            )

        # ===== 学科一致性校验（WZY模块：math/physics）=====
        # 这是第二道防线，如果前面的快速检测没有发现问题，这里进行更精确的检查
        try:
            import httpx
            from backend.modules.wzy.config import settings as wzy_settings

            # 使用文本推理模型进行学科一致性判定
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
                    for q in (result.questions or [])[:min(10, len(result.questions))]
                ],
            }

            # 使用LLM进行学科判定
            prompt = f"""你是教研员，负责学科判定。请判断以下内容最匹配的学科，只能从 ["math","physics","other"] 中选。
用户选择学科：{subject_en}

内容摘要：
{json.dumps(text_sample, ensure_ascii=False)}

请严格输出 JSON（不要输出其它文字）：
{{"detected_subject":"math|physics|other","confidence":0.0,"reasoning":"判断理由"}}"""

            t_mismatch0 = time.perf_counter()
            async with httpx.AsyncClient(base_url=endpoint, timeout=30.0) as client:
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
            reasoning = ""
            if m:
                try:
                    parsed = json.loads(m.group())
                    detected = str(parsed.get("detected_subject") or "").strip().lower()
                    try:
                        conf_f = float(parsed.get("confidence", 0.0))
                    except Exception:
                        conf_f = 0.0
                    reasoning = str(parsed.get("reasoning", ""))
                except Exception as e:
                    logger.warning(f"解析LLM响应失败: {e}")

            # 记录LLM检测结果
            logger.info(
                f"[ocr/analyze] task_id={task_id} user_id={current_user.id} LLM学科检测 "
                f"detected={detected or None} conf={conf_f:.2f} reasoning={reasoning[:100]}"
            )

            # 如果检测到学科不匹配且置信度高，则拒绝处理
            if detected in ("math", "physics", "other") and detected != subject_en and conf_f >= 0.75:
                warn = f"上传内容与选择学科不匹配：检测为 {detected}（置信度 {conf_f:.2f}，理由：{reasoning}），但选择了 {subject_en}。请确认学科选择或更换图片。"
                raise HTTPException(status_code=400, detail=warn)
            elif detected in ("math", "physics", "other") and detected != subject_en:
                # 置信度不够高，记录警告但不拒绝
                logger.warning(
                    f"[ocr/analyze] task_id={task_id} user_id={current_user.id} 学科可能不匹配 "
                    f"detected={detected} conf={conf_f:.2f}但置信度不够高，继续处理"
                )
                
            logger.info(
                f"[ocr/analyze] task_id={task_id} user_id={current_user.id} subject_check ok model={model} "
                f"detected={detected or None} conf={conf_f:.2f} duration_ms={mismatch_ms}"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"[ocr/analyze] task_id={task_id} user_id={current_user.id} subject_check skipped/failed: {e}")

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

        # 检查批改图像是否生成成功
        if not correction_result.success:
            logger.warning(f"[ocr/analyze] task_id={task_id} user_id={current_user.id} 批改图像生成失败，但继续处理其他步骤")

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
                # 保存批改后的图片文件
                corrected_filename = f"{corrected_file_hash[:32]}.png"
                corrected_path = os.path.join(
                    get_user_upload_dir(UPLOAD_DIR, current_user, "corrections", subject_en),
                    corrected_filename
                )
                with open(corrected_path, "wb") as f:
                    f.write(corrected_image_bytes)

                # 标准化路径格式
                corrected_relative_path = os.path.relpath(corrected_path, os.path.abspath("."))
                corrected_relative_path = corrected_relative_path.lstrip("./")
                if not corrected_relative_path.startswith("data/uploads"):
                    corrected_relative_path = f"data/uploads/{get_user_directory_name(current_user.username, current_user.email)}/corrections/{subject_en}/{corrected_filename}"

                # 创建批改后图片文件记录
                corrected_image_file = await crud_image_file.create_image_file(
                    db=db,
                    file_hash=corrected_file_hash,
                    user_id=current_user.id,
                    file_type="corrections",
                    subject=subject_en,
                    file_path=corrected_relative_path,
                    file_size=len(corrected_image_bytes),
                    mime_type="image/png",
                    image_type=ImageFileTypeEnum.CORRECTED,
                    original_image_id=original_image_file.id,
                )
                logger.info(f"Saved corrected image: hash={corrected_file_hash[:16]}..., path={corrected_relative_path}, id={corrected_image_file.id}")

        # 保存批注记录到数据库
        from backend.core.db.models import ExamCorrection, QuestionSourceEnum

        exam_correction = ExamCorrection(
            user_id=current_user.id,
            subject=subject_type,
            grade=grade or result.grade,
            exam_title=hint or f"{subject_en}试卷批改",
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
                }
                for q in result.questions
            ],
        )
        db.add(exam_correction)
        await db.flush()
        logger.info(
            f"[ocr/analyze] task_id={task_id} user_id={current_user.id} saved exam_correction id={exam_correction.id} "
            f"wrong_count={exam_correction.wrong_count} correct_count={exam_correction.correct_count}"
        )

        # 生成批改图片URL
        corrected_image_url = None
        if corrected_image_file:
            corrected_image_url = generate_correction_image_url(
                exam_correction.id, "corrected", subject_en
            )
            logger.info(f"Corrected image URL: {corrected_image_url}")

        # 为错误的题目自动创建错题记录
        from backend.core.crud import crud_question
        from backend.core.schemas.question import QuestionCreate

        wrong_question_ids = []
        for q in result.questions:
            if not q.is_correct:
                # 保存错题图片到用户专属目录
                question_filename = f"{task_id}_q{q.question_number}.{file_ext}"
                question_image_path = os.path.join(
                    get_user_upload_dir(UPLOAD_DIR, current_user, "questions", subject_en),
                    question_filename
                )

                import shutil
                try:
                    shutil.copy2(file_path, question_image_path)
                except Exception as e:
                    logger.warning(f"Failed to copy question image: {e}")
                    question_image_path = file_path

                # 生成URL路径
                question_image_url = get_user_file_url(current_user, "questions", subject_en, question_filename)

                # 创建错题记录
                question_data = QuestionCreate(
                    content=q.question_text,
                    title=f"第{q.question_number}题 - {q.question_type}",
                    subject=subject_en,
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
                    subject=subject_type,
                    difficulty=question_data.difficulty,
                    student_answer=question_data.student_answer,
                    correct_answer=question_data.correct_answer,
                    image_urls=question_data.image_urls,
                    knowledge_points=q.knowledge_points,
                    error_analysis=q.error_analysis,
                    source=QuestionSourceEnum.AI_CORRECTION,
                    source_description=f"AI批注试卷第{q.question_number}题",
                    tags=q.knowledge_points,
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

        # Telemetry: journey step done
        try:
            from backend.core.services.metrics_service import get_metrics_service
            await get_metrics_service().log_event(
                event_type="journey",
                event_name="ocr.analyze.done",
                ok=True,
                duration_ms=float(total_ms),
                user_id=current_user.id,
                module="wzy",
                subject=subject_en,
                task_id=task_id,
                exam_correction_id=exam_correction.id,
                payload={
                    "wrong_questions": len(wrong_question_ids),
                    "accuracy_rate": float(result.accuracy_rate or 0.0),
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
                }
                for q in result.questions
            ],
            overall_analysis=result.overall_analysis,
            weak_points=result.weak_points,
            improvement_suggestions=result.improvement_suggestions,
            corrected_image_url=corrected_image_url,
            is_duplicate=is_duplicate,
            duplicate_message=duplicate_message,
            is_previous_correction=False,
            correction_id=exam_correction.id,
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
                module="wzy",
                subject=subject_en,
                task_id=task_id,
                payload={"error": str(e)},
            )
        except Exception:
            pass
        
        if isinstance(e, HTTPException):
            raise
        
        error_detail = str(e)
        if "timeout" in error_detail.lower() or "timed out" in error_detail.lower() or "ReadTimeout" in error_detail:
            error_detail = "OCR服务响应超时，可能是网络问题或OCR服务暂时不可用，请稍后重试"
        elif "network" in error_detail.lower():
            error_detail = "网络连接异常，请检查网络后重试"
        
        raise HTTPException(status_code=500, detail=f"分析失败: {error_detail}")

    finally:
        # 清理临时文件
        pass


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
    from backend.modules.wzy.config import settings
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
    from backend.modules.wzy.config import settings
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