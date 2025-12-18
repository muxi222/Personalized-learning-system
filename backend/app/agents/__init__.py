"""
Agents Module - LangGraph based intelligent agents
智能体模块 - 基于LangGraph的多Agent系统

参考架构:
- Google AI Platform: https://cloud.google.com/ai-platform
- Facebook/Meta AI Research: https://ai.facebook.com
- OpenAI: https://platform.openai.com

包含以下Agent:
- QuestionIntakeAgent: 错题录入Agent - 处理用户输入的错题，进行结构化解析
- SimilarQuestionAgent: 举一反三Agent - 基于错题检索相似题目
- OCRAgent: 试卷OCR Agent - 使用Gemini进行试卷识别与批改
"""

from .question_intake_agent import (
    QuestionIntakeAgent,
    create_intake_graph,
)
from .similar_question_agent import (
    SimilarQuestionAgent,
    create_similar_question_graph,
)
from .ocr_agent import (
    OCRAgent,
    create_ocr_agent_graph,
    get_ocr_graph,
)
from .state import (
    AgentState,
    StudentProfile,
    QuestionIntakeState,
    SimilarQuestionState,
)

__all__ = [
    # Intake Agent
    "QuestionIntakeAgent",
    "create_intake_graph",
    "QuestionIntakeState",
    # Similar Question Agent
    "SimilarQuestionAgent",
    "create_similar_question_graph",
    "SimilarQuestionState",
    # OCR Agent
    "OCRAgent",
    "create_ocr_agent_graph",
    "get_ocr_graph",
    # Common
    "AgentState",
    "StudentProfile",
]

