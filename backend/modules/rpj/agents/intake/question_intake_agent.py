"""
RPJ - 错题录入 Agent（学生实现版 / Stub）

本文件仅保留主入口类与方法签名，删除了具体实现逻辑。
请对照参考实现：`backend/modules/tony/agents/intake/question_intake_agent.py`
"""

import logging
from typing import Dict, Any, Optional, List

from backend.core.agents.base_agent import BaseAgent
from backend.modules.rpj.config import settings

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
        image_paths: Optional[List[str]] = None,
        subject: str = "chinese",
        student_answer: Optional[str] = None,
        correct_answer: Optional[str] = None,
        difficulty: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """错题录入主流程入口。

        TODO(student):
        - 参数含义、返回结构请对齐 Tony 对应实现
        - 建议使用 LangGraph/LLM/OCR/CRUD 组合完成：解析 -> 入库 -> 向量化 -> 生成建议
        """
        raise NotImplementedError(
            "Not Implemented: students should implement QuestionIntakeAgent.process() by referencing tony module"
        )



# QUESTION_INTAKE_PROMPT = """
# 请从以下题目文本中提取结构化信息，并按JSON格式返回。

# 题目文本：
# {user_input_text}

# 请提取以下信息：
# 1. question_body: 题目正文
# 2. subject: 学科（语文、英语、政治）
# 3. grade: 年级（如：七年级、八年级、九年级）
# 4. difficulty: 难度（初级、中级、高级）
# 5. chapter: 章节或单元
# 6. knowledge_points: 知识点列表
# 7. student_answer: 学生答案（如果没有则留空）
# 8. correct_answer: 正确答案（如果没有则留空）
# 9. source: 来源（如：教材名称、试卷名称）

# JSON格式示例：
# {{
#     "question_body": "题目完整内容",
#     "subject": "语文",
#     "grade": "八年级",
#     "difficulty": "中级",
#     "chapter": "第一单元 文言文阅读",
#     "knowledge_points": ["文言文", "虚词用法", "句子翻译"],
#     "student_answer": "学生的错误答案",
#     "correct_answer": "正确答案",
#     "source": "人教版八年级语文上册"
# }}

# 请直接返回JSON，不要有其他内容。
# """

# # 学科专用Prompt
# CHINESE_QUESTION_PROMPT = """
# 你是一位语文老师，请分析以下语文题目：

# 题目文本：
# {user_input_text}

# 作为语文老师，请特别关注：
# 1. 题型（选择题、填空题、阅读理解、文言文、作文等）
# 2. 文学知识点（修辞手法、文学常识、文言文知识等）
# 3. 语言表达（病句修改、句子排序、词语运用等）

# 请以JSON格式返回分析结果。
# """

# ENGLISH_QUESTION_PROMPT = """
# You are an English teacher, please analyze the following English question:

# Question Text:
# {user_input_text}

# As an English teacher, please pay special attention to:
# 1. Question type (multiple choice, cloze test, reading comprehension, writing, etc.)
# 2. Grammar points (tenses, prepositions, sentence structures, etc.)
# 3. Vocabulary (key words, phrases, collocations)
# 4. Language skills (listening, reading, writing, translation)

# Please return the analysis results in JSON format.
# """
