"""
OCR批改API (XMX模块 - 学生实现完整版)

参考实现:
backend/modules/tony/api/endpoints/ocr.py

XMX模块支持的学科: economics
"""

import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.modules.xmx.api.deps import get_current_user_id
from backend.modules.xmx.config import settings
from backend.modules.xmx.agents.ai_correction.ocr_agent import OCRAgent

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/ocr",
    tags=["OCR"],
)

# ============================================================
# Request Schema（🔥 关键修改点）
# ============================================================

class OCRAnalyzeRequest(BaseModel):
    image_path: str
    task_id: str
    subject: str = "economics"

# ============================================================
# 工具函数
# ============================================================

def validate_subject(subject: str) -> None:
    """验证学科是否属于XMX模块"""
    if subject not in settings.SUBJECTS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Subject '{subject}' is not supported by XMX module. "
                f"Supported subjects: {settings.SUBJECTS}"
            ),
        )

# ============================================================
# OCR 批改接口
# ============================================================

@router.post("/analyze")
async def analyze_exam_image(
    req: OCRAnalyzeRequest,
    user_id: int = Depends(get_current_user_id),
):
    """
    OCR 批改试卷（学生完整版）
    """

    logger.info(
        f"[XMX OCR API] task_id={req.task_id}, user_id={user_id}, subject={req.subject}"
    )

    # 1️⃣ 学科校验
    validate_subject(req.subject)

    # TODO(student): 学科判定 + 分类归一化（统一模板 v1；不要在此处直接实现，留给学生）
    # 【输入】user_selected_subject=req.subject，text=OCR提取出的题目文本/结构化题目
    # 【输出】对每题生成：
    #   - detected_subject + confidence(0~1)
    #   - chapter: 从 CHAPTER_TAXONOMY[detected_subject] 选 1 个（否则“综合”）
    #   - knowledge_points: 从 KNOWLEDGE_POINT_TAXONOMY[detected_subject] 选 1~3 个（否则“综合”）
    #   - tags: 2~6 个短词（用于检索，避免太碎）
    # 【规则】
    #   - 若 detected_subject != user_selected_subject 且 confidence >= 0.75：提示“学科不匹配”并拒绝返回结果
    #   - taxonomy 必须收敛：chapter 建议 6~10 个，knowledge_points 建议 10~25 个；同义项合并，避免发散
    # 【推荐 taxonomy 示例（XMX: economics）】
    #   CHAPTER_TAXONOMY = {
    #     "economics": ["供需与弹性", "成本与收益", "市场结构", "宏观经济(国民收入)", "货币与金融", "市场与政策", "国际贸易", "综合"],
    #   }
    #   KNOWLEDGE_POINT_TAXONOMY = {
    #     "economics": ["供给与需求", "价格弹性", "边际分析", "机会成本", "市场失灵", "财政政策", "货币政策", "通货膨胀", "GDP与失业", "汇率与贸易", "综合"],
    #   }
    # 【实现建议】
    #   - OCR 后调用 settings.LLM_API_ENDPOINT 的 /chat/completions（二次判定+归一化）
    #   - 优先更强模型（gemini-3-pro-preview / gpt-5.2），可通过环境变量 XMX_HIGH_ACCURACY_MODEL 覆盖
    # 【参考实现】backend/modules/tony/agents/question_intake_ocr_agent.py（仅 tony 模块完整实现）

    # 2️⃣ 创建 OCR Agent
    agent = OCRAgent()

    # 3️⃣ 执行 OCR + 分析
    try:
        result = await agent.process(
            image_path=req.image_path,
            user_id=user_id,
            task_id=req.task_id,
            subject=req.subject,
        )
    except Exception as e:
        logger.exception("OCRAgent 执行异常")
        raise HTTPException(
            status_code=500,
            detail=f"OCR 处理失败: {str(e)}",
        )

    # 4️⃣ 业务失败处理
    if not result.get("success", False):
        raise HTTPException(
            status_code=400,
            detail={
                "task_id": req.task_id,
                "errors": result.get("errors", []),
            },
        )

    # 5️⃣ 返回结果（对齐 TONY API）
    return {
        "task_id": req.task_id,
        "subject": req.subject,
        "success": True,
        "total_score": result.get("total_score", 0),
        "total_possible": result.get("total_possible", 100),
        "questions": result.get("questions", []),
        "weak_points": result.get("weak_points", []),
        "suggestions": result.get("suggestions", []),
        "similar_questions": result.get("similar_questions", []),
    }
