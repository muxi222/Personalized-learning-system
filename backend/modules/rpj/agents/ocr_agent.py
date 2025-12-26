"""
OCR识别Agent (RPJ模块 - 学生实现版本)

本文件为框架代码，需要学生完成核心Agent逻辑的实现。
完整实现请参考: backend/modules/tony/agents/ocr_agent.py
"""

import logging
from typing import Dict, Any
from backend.core.agents.base_agent import BaseAgent
from backend.modules.rpj.config import settings

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
