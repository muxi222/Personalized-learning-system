"""
错题录入Agent (XMX模块 - 学生实现版本)

本文件为框架代码，需要学生完成核心Agent逻辑的实现。
完整实现请参考: backend/modules/tony/agents/question_intake_agent.py
"""

import logging
from typing import Dict, Any
from backend.core.agents.base_agent import BaseAgent
from backend.modules.xmx.config import settings

logger = logging.getLogger(__name__)

class QuestionIntakeAgent(BaseAgent):
    """
    错题录入Agent

    TODO: 学生需要实现以下功能
    1. 继承自 BaseAgent，使用 subject 验证
    2. 实现核心处理逻辑
    3. 使用 LangGraph 构建工作流
    4. 返回处理结果

    参考实现: backend/modules/tony/agents/question_intake_agent.py

    TODO(student): 学科判定 + 分类归一化（统一模板 v1；重点要求）
    【输入】user_selected_subject=kwargs["subject"]（或同等字段），text=OCR提取出的题目文本/结构化题目
    【输出】保存到数据库前，需要生成：
      - detected_subject + confidence(0~1)
      - chapter: 从 CHAPTER_TAXONOMY[detected_subject] 选 1 个（否则“综合”）
      - knowledge_points: 从 KNOWLEDGE_POINT_TAXONOMY[detected_subject] 选 1~3 个（否则“综合”）
      - tags: 2~6 个短词（用于检索，避免太碎）
    【规则】
      - 若 detected_subject != user_selected_subject 且 confidence >= 0.75：提示“学科不匹配”，拒绝入库并提示用户改学科/换内容
      - taxonomy 必须收敛：chapter 建议 6~10 个，knowledge_points 建议 10~25 个；同义项合并，避免发散
    【推荐 taxonomy 示例（XMX: economics）】
      CHAPTER_TAXONOMY = {
        "economics": ["供需与弹性", "成本与收益", "市场结构", "宏观经济(国民收入)", "货币与金融", "市场与政策", "国际贸易", "综合"],
      }
      KNOWLEDGE_POINT_TAXONOMY = {
        "economics": ["供给与需求", "价格弹性", "边际分析", "机会成本", "市场失灵", "财政政策", "货币政策", "通货膨胀", "GDP与失业", "汇率与贸易", "综合"],
      }
    【实现建议】
      - OCR 后调用 settings.LLM_API_ENDPOINT 的 /chat/completions（二次判定+归一化）
      - 优先更强模型（gemini-3-pro-preview / gpt-5.2），可通过环境变量 XMX_HIGH_ACCURACY_MODEL 覆盖
    【参考实现】backend/modules/tony/agents/question_intake_ocr_agent.py（仅 tony 模块完整实现）
    """

    def __init__(self):
        super().__init__(subjects=settings.SUBJECTS)
        logger.info(f"[{settings.MODULE_NAME.upper()}] 初始化 QuestionIntakeAgent")

    async def process(self, **kwargs) -> Dict[str, Any]:
        """
        处理主逻辑

        TODO: 学生需要实现此方法

        参数:
            **kwargs: 根据Agent类型不同而不同

        返回:
            Dict[str, Any]: 处理结果

        实现步骤:
        1. 验证输入参数
        2. 调用subject验证 (已在BaseAgent中实现)
        3. 构建LangGraph工作流
        4. 执行Agent逻辑
        5. 返回结果

        参考: backend/modules/tony/agents/question_intake_agent.py
        """
        # ============ TODO: 实现Agent逻辑 ============
        logger.warning(f"[{settings.MODULE_NAME.upper()}] QuestionIntakeAgent.process() 需要学生实现")

        return {
            "success": False,
            "message": "学生TODO: 实现QuestionIntakeAgent的process方法"
        }
