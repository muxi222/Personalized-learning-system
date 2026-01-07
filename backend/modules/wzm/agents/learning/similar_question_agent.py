"""
WZM - 相似题/举一反三 Agent（学生实现版 / Stub）

本文件仅保留主入口类与方法签名，删除了具体实现逻辑。
请对照参考实现：`backend/modules/tony/agents/learning/similar_question_agent.py`
"""

import logging
from typing import Dict, Any, Optional

from backend.core.agents.base_agent import BaseAgent
from backend.modules.wzm.config import settings

logger = logging.getLogger(__name__)


class SimilarQuestionAgent(BaseAgent):
    """相似题推荐/举一反三主入口 Agent。

    TODO(student):
    - 目标：基于题目文本或题目ID做相似检索（向量库/RAG），返回相似题列表与引导文本。
    - 参考：`backend/modules/tony/agents/learning/similar_question_agent.py`
    """

    def __init__(self):
        super().__init__(subjects=settings.SUBJECTS)
        logger.info("[%s] SimilarQuestionAgent stub initialized", settings.MODULE_NAME.upper())

    async def process(
        self,
        question_id: int,
        user_id: int,
        task_id: str = "",
        top_k: int = 5,
        subject: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """相似题推荐主流程入口。"""
        raise NotImplementedError(
            "Not Implemented: students should implement SimilarQuestionAgent.process() by referencing tony module"
        )

