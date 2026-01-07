"""
WZM - 错题录入 Agent（学生实现版 / Stub）

本文件仅保留主入口类与方法签名，删除了具体实现逻辑。
请对照参考实现：`backend/modules/tony/agents/intake/question_intake_agent.py`
"""

import logging
from typing import Dict, Any, Optional, List

from backend.core.agents.base_agent import BaseAgent
from backend.modules.wzm.config import settings

logger = logging.getLogger(__name__)


class QuestionIntakeAgent(BaseAgent):
    """错题录入主入口 Agent。

    TODO(student):
    - 目标：接收用户输入（文本/图片OCR结果），解析为结构化错题数据，入库并返回 `question_id`。
    - 参考：`backend/modules/tony/agents/intake/question_intake_agent.py`
    """

    def __init__(self):
        super().__init__(subjects=settings.SUBJECTS)
        logger.info("[%s] QuestionIntakeAgent stub initialized", settings.MODULE_NAME.upper())

    async def process(
        self,
        raw_input: str,
        user_id: int,
        task_id: str,
        image_urls: Optional[list] = None,
        student_answer: Optional[str] = None,
        correct_answer: Optional[str] = None,
        subject: Optional[str] = None,
        difficulty: Optional[str] = None,
        title: Optional[str] = None,
    ) -> Dict[str, Any]:
        """错题录入主流程入口。

        TODO(student):
        - 参数含义、返回结构请对齐 Tony 对应实现
        - 建议使用 LangGraph/LLM/OCR/CRUD 组合完成：解析 -> 入库 -> 向量化 -> 生成建议
        """
        raise NotImplementedError(
            "Not Implemented: students should implement QuestionIntakeAgent.process() by referencing tony module"
        )

