"""
OCR识别Agent (XMX模块 - 学生实现版本)

本文件为框架代码，需要学生完成核心Agent逻辑的实现。
完整实现请参考: backend/modules/tony/agents/ai_correction/ocr_agent.py

建议实现思路（对照 tony 模块）：
1) 输入校验 + 学科校验
   - 常见输入：image_path / user_id / task_id / subject / grade / hint
   - 使用 BaseAgent.validate_subject(subject) 约束学科

2) OCR/版面解析 -> 结构化题目
   - 输出建议字段（示例）：
     - success: bool
     - questions: list[dict]（按题号顺序）
     - total_score / max_score / accuracy_rate
     - overall_analysis / weak_points / improvement_suggestions
     - corrected_image_base64（可选：批改图）

3) 批改/正确性判断（如图片存在老师批改痕迹）
   - 优先级建议：老师打勾/打叉 > 老师写的正确答案 > 模型推断 > 分值/得分

4) 任务状态更新/结果落库（由上层 tasks/endpoints 配合完成）
"""

import logging
from typing import Dict, Any
from backend.core.agents.base_agent import BaseAgent
from backend.modules.xmx.config import settings

logger = logging.getLogger(__name__)

class OCRAgent(BaseAgent):
    """
    OCR识别Agent

    TODO: 学生需要实现以下功能
    1. 继承自 BaseAgent，使用 subject 验证
    2. 实现核心处理逻辑
    3. 使用 LangGraph 构建工作流
    4. 返回处理结果

    参考实现: backend/modules/tony/agents/ocr_agent.py
    """

    def __init__(self):
        super().__init__(subjects=settings.SUBJECTS)
        logger.info(f"[{settings.MODULE_NAME.upper()}] 初始化 OCRAgent")

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

        参考: backend/modules/tony/agents/ocr_agent.py
        """
        # ============ TODO: 实现Agent逻辑 ============
        logger.warning(f"[{settings.MODULE_NAME.upper()}] OCRAgent.process() 需要学生实现")

        return {
            "success": False,
            "message": "学生TODO: 实现OCRAgent的process方法"
        }
