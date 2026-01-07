"""
OCR识别Agent (RPJ模块 - 学生实现版本 / Stub)

说明：
- RPJ 属于学生模块，这里仅保留**主要入口类/方法定义**，删除具体实现逻辑。
- 参考实现请对照 tony 模块：
  - `backend/modules/tony/agents/ai_correction/ocr_agent.py`

你需要实现什么（建议按 Tony 的实现拆成若干节点/步骤）：
1) 输入校验 + 学科校验
   - 输入：image_path/user_id/task_id/subject/grade/hint 等
   - 使用 BaseAgent 的 `validate_subject` 做 subject 约束

2) OCR/版面解析（试卷/作业图片 -> 结构化题目列表）
   - 建议输出结构（示例）：
     - questions: [{question_body, student_answer_raw, teacher_marked_answer, model_inferred_answer, ...}, ...]
     - total_score / max_score / accuracy_rate
     - weak_points / improvement_suggestions / overall_analysis
     - corrected_image_base64（可选：如有批改图）

3) 批改结果/正确性判断（如有教师批改痕迹优先）
   - 参考 Tony 的“老师打勾/打叉优先级”策略

4) 结果持久化（如需要）
   - 写库/落图/任务状态更新等应由上层 tasks / endpoints 协作完成

注意：
- 本文件只保留入口，具体实现请学生自行补齐。
"""

import logging
from typing import Dict, Any, Optional

from backend.core.agents.base_agent import BaseAgent
from backend.modules.rpj.config import settings

logger = logging.getLogger(__name__)


class OCRAgent(BaseAgent):
    """
    OCR识别/试卷分析 Agent（RPJ）

    TODO(student):
    - 参考：`backend/modules/tony/agents/ai_correction/ocr_agent.py`
    - 目标：对上传试卷图片进行 OCR + 结构化解析 + 批改分析，并返回结构化结果
    """

    def __init__(self, subject: Optional[str] = None):
        # 保持兼容：RPJ 的 endpoints 会以 `OCRAgent(subject)` 初始化；Celery tasks 也可能直接 `OCRAgent()`
        super().__init__(subjects=settings.SUBJECTS)
        self.default_subject = subject
        logger.info(f"[{settings.MODULE_NAME.upper()}] 初始化 OCRAgent (stub), default_subject={subject!r}")

    async def process(self, **kwargs) -> Dict[str, Any]:
        """
        任务入口（Celery 等上层会调用）。

        TODO(student):
        - 约定常见参数：
          - image_path: str
          - user_id: int
          - task_id: str
          - subject: str
          - grade: str（可选）
          - hint: str（可选）
        - 建议内部调用 `analyze_exam_image(...)` 复用逻辑
        """
        logger.warning(f"[{settings.MODULE_NAME.upper()}] OCRAgent.process() 需要学生实现")
        return {
            "success": False,
            "message": "学生TODO: 实现RPJ模块 OCRAgent.process()",
        }

    async def analyze_exam_image(
        self,
        *,
        image_path: str,
        subject: str,
        grade: str = "",
        hint: str = "",
        **kwargs,
    ) -> Dict[str, Any]:
        """
        供 API endpoint 直接调用的试卷分析入口（RPJ 的 `api/endpoints/ai_correction/ocr.py` 会调用）。

        TODO(student):
        - 按 Tony 的返回结构产出字段，至少包含：
          - success: bool
          - questions: list
          - total_score/max_score/accuracy_rate（如适用）
          - overall_analysis/weak_points/improvement_suggestions（如适用）
          - corrected_image_base64（可选）
        """
        logger.warning(f"[{settings.MODULE_NAME.upper()}] OCRAgent.analyze_exam_image() 需要学生实现")
        return {
            "success": False,
            "message": "学生TODO: 实现RPJ模块 OCRAgent.analyze_exam_image()",
        }


