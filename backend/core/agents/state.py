"""
Agent State Definitions
智能体状态定义
"""

from typing import TypedDict, List, Optional, Dict, Any, Annotated
from operator import add
from datetime import datetime

class StudentProfile(TypedDict, total=False):
    """
    学生画像 - 用于长期记忆和个性化
    根据设计文档7.3节: 长期记忆与个性化演进
    """
    user_id: int
    username: str
    grade: str  # 年级

    # 学习统计
    total_questions: int  # 错题总数
    weak_subjects: List[str]  # 薄弱学科
    weak_knowledge_points: List[str]  # 薄弱知识点

    # 学习风格
    preferred_explanation_style: str  # 喜欢的讲解风格
    learning_pace: str  # 学习节奏 (fast/medium/slow)

    # 历史摘要
    recent_errors_summary: str  # 最近错题总结
    progress_summary: str  # 学习进度总结

    last_updated: str  # 最后更新时间

class AgentState(TypedDict, total=False):
    """
    通用Agent状态定义
    包含工作流中各节点需要读写的数据
    """
    # ======== 输入数据 ========
    raw_input: str  # 原始输入文本
    image_urls: List[str]  # 图片URL列表
    image_text: str  # OCR提取的文本
    user_id: int  # 用户ID
    task_id: str  # 任务ID

    # ======== 学生画像 ========
    student_profile: StudentProfile  # 学生画像（用于个性化）

    # ======== 结构化数据 (按设计文档4.1节) ========
    structured_data: Dict[str, Any]  # 包含以下字段:
    # - subject: 学科 (数学, 物理, 英语等)
    # - grade: 年级 (高一, 初三等)
    # - chapter: 章节/知识点
    # - question_body: 题干
    # - options: 选项 (选择题)
    # - correct_answer: 正确答案
    # - student_answer: 学生答案
    # - difficulty: 难度 (初级, 中级, 高级)

    question_id: int  # 数据库中的题目ID
    embedding: List[float]  # 题目的向量表示

    # ======== 分析结果 ========
    knowledge_points: List[str]  # 涉及的知识点
    error_analysis: str  # 错因分析
    error_type: str  # 错误类型
    suggested_questions: List[Dict[str, Any]]  # 举一反三题目
    learning_guidance: str  # 学习指导建议

    # ======== 元数据 ========
    subject: str  # 学科
    grade: str  # 年级
    difficulty: str  # 难度
    chapter: str  # 章节
    current_step: str  # 当前步骤
    progress: float  # 进度 (0-100)
    errors: Annotated[List[str], add]  # 错误信息列表 (追加模式)

class QuestionIntakeState(AgentState):
    """
    错题录入Agent专用状态
    扩展自AgentState，包含录入特定的字段
    """
    # OCR处理
    ocr_result: str  # OCR识别结果
    ocr_confidence: float  # OCR置信度

    # 解析状态
    parse_attempts: int  # 解析尝试次数
    parse_success: bool  # 解析是否成功

class SimilarQuestionState(AgentState):
    """
    举一反三Agent专用状态
    """
    # 检索结果
    retrieved_question_ids: List[int]  # 检索到的相似题目ID
    retrieved_questions: List[Dict[str, Any]]  # 相似题目详情
    similarity_scores: List[float]  # 相似度分数

    # 原题信息
    original_question: Dict[str, Any]  # 原始错题信息
    original_error_analysis: str  # 原题错因分析

    # 生成结果
    guidance_text: str  # 生成的引导文本
    recommended_questions: List[Dict[str, Any]]  # 推荐的练习题
