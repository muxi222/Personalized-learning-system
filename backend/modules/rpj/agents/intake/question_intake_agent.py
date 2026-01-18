"""
RPJ - 错题录入 Agent（学生实现版 / Stub）

本文件为RPJ模块（语文、英语、政治学科）的错题录入Agent框架。
请参考Tony模块实现：`backend/modules/tony/agents/intake/question_intake_agent.py`

主要功能：
1. 接收用户输入（文本/图片OCR结果）
2. 解析为结构化错题数据
3. 保存到数据库并生成向量
4. 生成举一反三题目
"""

import logging
import json
from typing import Dict, Any, Optional, List
from datetime import datetime

from langgraph.graph import StateGraph, END

from backend.core.agents.state import QuestionIntakeState
from backend.core.agents.prompts import QUESTION_INTAKE_PROMPT
from backend.core.agents.base_agent import BaseAgent
from backend.modules.rpj.config import settings

logger = logging.getLogger(__name__)

# RPJ模块学科映射（语文、英语、政治）
RPJ_SUBJECT_MAP = {
    "chinese": "语文",
    "english": "英语", 
    "politics": "政治",
    "other": "其他",
}

# RPJ模块难度映射
DIFFICULTY_MAP = {
    "easy": "简单",
    "medium": "中等",
    "hard": "困难",
    "简单": "easy",
    "中等": "medium",
    "困难": "hard",
}

class QuestionIntakeAgent(BaseAgent):
    """
    RPJ模块错题录入Agent
    
    负责接收、解析、存储错题（语文、英语、政治学科）
    基于LangGraph工作流实现
    """

    def __init__(self):
        super().__init__(subjects=["chinese", "english", "politics", "other"])
        self.graph = create_intake_graph()
        logger.info(f"[RPJ] QuestionIntakeAgent initialized with subjects: {self.subjects}")

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
        grade: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        处理错题录入主流程
        
        Args:
            raw_input: 原始输入文本
            user_id: 用户ID
            task_id: 任务ID
            image_urls: 图片URL列表 (可选)
            student_answer: 学生答案 (可选)
            correct_answer: 正确答案 (可选)
            subject: 学科 (可选，支持：chinese/english/politics/other)
            difficulty: 难度 (可选，支持：easy/medium/hard)
            title: 题目标题 (可选)
            grade: 年级 (可选)
            
        Returns:
            处理结果字典:
            {
                "task_id": str,
                "question_id": int | None,
                "success": bool,
                "errors": List[str],
                "structured_data": Dict,
                "created_at": str
            }
        """
        # TODO(student): 实现RPJ模块的错题录入主流程
        # 参考实现：Tony模块的QuestionIntakeAgent.process方法
        # 需要适配RPJ模块的学科特点
        
        # 步骤1: 验证输入参数
        # - 验证学科是否在RPJ模块支持范围内
        # - 验证难度格式
        # - 处理中英文转换
        
        # 步骤2: 构建初始状态
        # - 合并原始输入和OCR结果（如果有）
        # - 预设结构化数据
        # - 设置学科和难度
        
        # 步骤3: 运行工作流图
        # - 使用self.graph.astream处理
        # - 捕获各个节点的输出
        
        # 步骤4: 返回处理结果
        # - 包含question_id（如果成功）
        # - 包含错误信息（如果失败）
        
        raise NotImplementedError("QuestionIntakeAgent.process() not implemented for RPJ module")

# ============ Graph Nodes (工作流节点) ============

async def semantic_parse(state: QuestionIntakeState) -> Dict[str, Any]:
    """
    语义解析节点 - 使用LLM提取结构化信息（RPJ模块专用）
    
    TODO(student):
    1. 使用RPJ模块的LLM配置调用大模型
    2. 设计适合语文、英语、政治学科的prompt模板
    3. 提取以下信息：
       - 题目正文 (question_body)
       - 题目类型 (question_type: 选择题/填空题/阅读理解/作文等)
       - 学科 (subject: chinese/english/politics)
       - 年级 (grade)
       - 章节 (chapter: 从CHAPTER_TAXONOMY中选择)
       - 知识点 (knowledge_points: 从KNOWLEDGE_POINT_TAXONOMY中选择1-3个)
       - 难度 (difficulty: easy/medium/hard)
       - 标签 (tags: 2-6个短词)
    
    Args:
        state: 工作流状态
        
    Returns:
        包含解析结果的字典
    """
    # TODO(student): 实现RPJ模块的语义解析
    # 参考：Tony模块的semantic_parse函数
    # 注意：要适配语文、英语、政治学科的特点
    
    # 示例代码结构：
    # 1. 合并原始输入和OCR结果
    # combined_input = state.get("raw_input", "") + state.get("ocr_result", "")
    
    # 2. 构建学科特定的prompt
    # subject = state.get("subject", "chinese")
    # prompt = build_rpj_prompt(subject, combined_input)
    
    # 3. 调用LLM服务（使用RPJ模块配置）
    # from backend.core.services.llm_service import get_llm_service
    # llm = get_llm_service(module="rpj")
    # result = await llm.generate_json(prompt=prompt, temperature=0.3)
    
    # 4. 验证和标准化结果
    # - 学科必须映射为英文：chinese/english/politics
    # - 章节必须从CHAPTER_TAXONOMY中选择
    # - 知识点必须从KNOWLEDGE_POINT_TAXONOMY中选择
    # - 难度转换为标准格式
    
    # 5. 返回结构化数据
    
    raise NotImplementedError("semantic_parse() not implemented for RPJ module")

async def subject_validation_and_normalization(state: QuestionIntakeState) -> Dict[str, Any]:
    """
    学科验证与归一化节点（RPJ模块专用）
    
    TODO(student):
    1. 验证用户选择的学科与解析出的学科是否一致
    2. 如果不一致且置信度高(≥0.75)，记录学科不匹配警告
    3. 对章节和知识点进行归一化处理
    4. 生成标准化标签
    
    Args:
        state: 工作流状态
        
    Returns:
        包含验证和归一化结果的字典
    """
    # TODO(student): 实现学科验证与归一化
    # 这个节点是RPJ模块特有的，用于确保学科一致性
    
    # 步骤：
    # 1. 从state中获取用户选择的学科和解析出的学科
    # 2. 比较两者，如果不同且解析置信度高，添加警告
    # 3. 使用RPJ模块的分类体系对章节和知识点进行归一化
    # 4. 生成适合检索的标签
    
    raise NotImplementedError("subject_validation_and_normalization() not implemented for RPJ module")

async def save_to_database(state: QuestionIntakeState) -> Dict[str, Any]:
    """
    数据存储节点 - 保存到数据库（RPJ模块专用）
    
    TODO(student):
    1. 将结构化数据保存到数据库
    2. 处理学科映射（中英文转换）
    3. 保存章节和知识点信息
    4. 记录原始输入和解析后的输入
    
    Args:
        state: 工作流状态
        
    Returns:
        包含question_id的字典
    """
    # TODO(student): 实现RPJ模块的数据存储
    # 参考：Tony模块的save_to_database函数
    
    # 注意事项：
    # 1. 使用RPJ模块的数据库模型
    # 2. 学科类型需要映射为RPJ模块的SubjectType
    # 3. 难度需要映射为DifficultyLevel
    # 4. 保存章节和知识点到特定字段
    # 5. 记录学科判定信息（detected_subject, confidence等）
    
    raise NotImplementedError("save_to_database() not implemented for RPJ module")

async def trigger_embedding(state: QuestionIntakeState) -> Dict[str, Any]:
    """
    触发异步Embedding节点（RPJ模块专用）
    
    TODO(student):
    1. 生成题目文本的embedding向量
    2. 将向量保存到向量数据库
    3. 添加学科、章节、知识点等元数据
    
    Args:
        state: 工作流状态
        
    Returns:
        包含embedding状态的字典
    """
    # TODO(student): 实现RPJ模块的向量化处理
    # 参考：Tony模块的trigger_embedding函数
    
    # 注意事项：
    # 1. 使用RPJ模块的embedding配置
    # 2. 结合学科特点优化文本表示
    # 3. 元数据中包含学科、章节、知识点等信息
    
    raise NotImplementedError("trigger_embedding() not implemented for RPJ module")

async def analyze_error(state: QuestionIntakeState) -> Dict[str, Any]:
    """
    错因分析节点（RPJ模块专用）
    
    TODO(student):
    1. 根据学科特点分析错误原因
    2. 语文：分析语言表达、理解偏差、知识盲点等
    3. 英语：分析语法错误、词汇不足、理解偏差等
    4. 政治：分析概念混淆、理解偏差、应用不当等
    
    Args:
        state: 工作流状态
        
    Returns:
        包含错因分析结果的字典
    """
    # TODO(student): 实现RPJ模块的错因分析
    # 参考：Tony模块的analyze_error函数
    
    # 注意事项：
    # 1. 设计学科特定的错因分析prompt
    # 2. 语文：关注语言表达、修辞手法、篇章结构等
    # 3. 英语：关注语法、词汇、阅读理解等
    # 4. 政治：关注概念理解、理论应用、时事分析等
    
    raise NotImplementedError("analyze_error() not implemented for RPJ module")

async def generate_suggested_questions(state: QuestionIntakeState) -> Dict[str, Any]:
    """
    生成举一反三题目节点（RPJ模块专用）
    
    TODO(student):
    1. 根据原题生成相似题目
    2. 保持相同知识点但变换形式
    3. 生成1-3个举一反三题目
    4. 包含题目、答案、难度、知识点等信息
    
    Args:
        state: 工作流状态
        
    Returns:
        包含举一反三题目的字典
    """
    # TODO(student): 实现RPJ模块的举一反三题目生成
    # 这个节点是错题录入的重要环节
    
    # 步骤：
    # 1. 基于原题的知识点和难度
    # 2. 生成相似但不同的题目
    # 3. 确保题目质量（语法正确、逻辑清晰）
    # 4. 生成参考答案和解题思路
    
    raise NotImplementedError("generate_suggested_questions() not implemented for RPJ module")

async def update_result(state: QuestionIntakeState) -> Dict[str, Any]:
    """
    更新最终结果节点（RPJ模块专用）
    
    TODO(student):
    1. 更新数据库中的错题记录
    2. 添加错因分析和举一反三题目
    3. 更新任务状态为完成
    4. 记录处理时间
    
    Args:
        state: 工作流状态
        
    Returns:
        包含最终状态的字典
    """
    # TODO(student): 实现RPJ模块的结果更新
    # 参考：Tony模块的update_result函数
    
    # 注意事项：
    # 1. 更新错题记录的错因分析字段
    # 2. 保存举一反三题目到数据库
    # 3. 更新任务状态
    # 4. 记录完整的处理结果
    
    raise NotImplementedError("update_result() not implemented for RPJ module")

# ============ 辅助函数 ============

def build_rpj_prompt(subject: str, input_text: str) -> str:
    """
    构建RPJ模块的语义解析prompt
    
    TODO(student):
    根据学科构建特定的prompt模板
    
    Args:
        subject: 学科（chinese/english/politics）
        input_text: 输入文本
        
    Returns:
        prompt字符串
    """
    # TODO(student): 实现RPJ模块的prompt构建
    # 需要针对语文、英语、政治学科设计不同的prompt
    
    subject_cn = {
        "chinese": "语文",
        "english": "英语",
        "politics": "政治"
    }.get(subject, "其他")
    
    # 示例结构：
    prompt_template = f"""
    你是一位经验丰富的{subject_cn}老师，请分析以下题目并提取结构化信息：
    
    【题目原文】
    {input_text}
    
    请提取以下信息（如果某项信息不存在，请留空或填写"未知"）：
    1. 题目正文 (question_body)
    2. 题目类型 (question_type: 选择题/填空题/阅读理解/作文/简答题/论述题等)
    3. 学科 (subject: chinese/english/politics)
    4. 年级 (grade: 如"高一"、"初三"等)
    5. 章节 (chapter: 从以下选择：{CHAPTER_TAXONOMY.get(subject, ["综合"])})
    6. 知识点 (knowledge_points: 从以下选择1-3个：{KNOWLEDGE_POINT_TAXONOMY.get(subject, ["综合"])})
    7. 难度 (difficulty: easy/medium/hard)
    8. 标签 (tags: 生成2-6个短词标签，用于检索)
    
    请以JSON格式返回，不要添加其他内容。
    """
    
    return prompt_template

def normalize_chapter(chapter: str, subject: str) -> str:
    """
    章节归一化函数
    
    TODO(student):
    将解析出的章节映射到预定义的分类体系中
    
    Args:
        chapter: 原始章节
        subject: 学科
        
    Returns:
        归一化后的章节
    """
    # TODO(student): 实现章节归一化
    # 将相似的章节名称映射到标准名称
    
    raise NotImplementedError("normalize_chapter() not implemented for RPJ module")

def normalize_knowledge_points(knowledge_points: List[str], subject: str) -> List[str]:
    """
    知识点归一化函数
    
    TODO(student):
    将解析出的知识点映射到预定义的分类体系中
    
    Args:
        knowledge_points: 原始知识点列表
        subject: 学科
        
    Returns:
        归一化后的知识点列表
    """
    # TODO(student): 实现知识点归一化
    # 将相似的知识点名称映射到标准名称
    
    raise NotImplementedError("normalize_knowledge_points() not implemented for RPJ module")

# ============ Graph Definition (工作流定义) ============

def create_intake_graph():
    """
    创建RPJ模块错题录入Agent的工作流图
    
    TODO(student):
    设计适合RPJ模块的工作流，包含以下节点：
    1. semantic_parse: 语义解析
    2. subject_validation_and_normalization: 学科验证与归一化
    3. save_to_database: 保存到数据库
    4. trigger_embedding: 触发向量化
    5. analyze_error: 错因分析
    6. generate_suggested_questions: 生成举一反三题目
    7. update_result: 更新结果
    
    注意：可以根据需要调整节点顺序和连接关系
    """
    
    workflow = StateGraph(QuestionIntakeState)
    
    # TODO(student): 添加工作流节点
    # workflow.add_node("semantic_parse", semantic_parse)
    # workflow.add_node("subject_validation_and_normalization", subject_validation_and_normalization)
    # workflow.add_node("save_to_database", save_to_database)
    # workflow.add_node("trigger_embedding", trigger_embedding)
    # workflow.add_node("analyze_error", analyze_error)
    # workflow.add_node("generate_suggested_questions", generate_suggested_questions)
    # workflow.add_node("update_result", update_result)
    
    # TODO(student): 定义工作流边（连接关系）
    # workflow.set_entry_point("semantic_parse")
    # workflow.add_edge("semantic_parse", "subject_validation_and_normalization")
    # workflow.add_edge("subject_validation_and_normalization", "save_to_database")
    # ...
    # workflow.add_edge("update_result", END)
    
    # TODO(student): 编译工作流图
    # return workflow.compile()
    
    raise NotImplementedError("create_intake_graph() not implemented for RPJ module")

# ============ 全局变量（从模块配置导入） ============

# 从配置中获取分类体系
try:
    from backend.modules.rpj.api.endpoints.intake.questions import (
        CHAPTER_TAXONOMY, 
        KNOWLEDGE_POINT_TAXONOMY
    )
except ImportError:
    # 备用分类体系
    CHAPTER_TAXONOMY = {
        "chinese": ["文言文", "现代文", "古诗词", "作文", "语言运用", "综合"],
        "english": ["阅读理解", "完形填空", "语法", "写作", "词汇", "综合"],
        "politics": ["政治生活", "经济生活", "文化生活", "哲学", "时事政治", "综合"],
        "other": ["综合"],
    }
    
    KNOWLEDGE_POINT_TAXONOMY = {
        "chinese": ["文言实词", "修辞手法", "篇章结构", "写作技巧", "文学常识", "综合"],
        "english": ["时态语态", "从句结构", "阅读理解技巧", "写作模板", "词汇搭配", "综合"],
        "politics": ["政治制度", "经济原理", "文化传承", "哲学原理", "政策法规", "综合"],
        "other": ["综合"],
    }

logger.info(f"[RPJ] QuestionIntakeAgent stub loaded with taxonomies for subjects: {list(CHAPTER_TAXONOMY.keys())}")