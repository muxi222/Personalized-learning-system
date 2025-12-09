"""
LangGraph State & Graph Definition
智能体工作流图定义
"""

import logging
from typing import TypedDict, List, Optional, Dict, Any, Annotated
from operator import add

from langgraph.graph import StateGraph, END

logger = logging.getLogger(__name__)


class AgentState(TypedDict, total=False):
    """
    Agent状态定义
    包含工作流中各节点需要读写的数据
    """
    # ======== 输入数据 ========
    raw_input: str  # 原始输入文本
    image_urls: List[str]  # 图片URL列表
    user_id: int  # 用户ID
    task_id: str  # 任务ID

    # ======== 中间数据 ========
    structured_data: Dict[str, Any]  # 结构化提取的数据
    question_id: int  # 数据库中的题目ID
    embedding: List[float]  # 题目的向量表示

    # ======== 分析结果 ========
    knowledge_points: List[str]  # 涉及的知识点
    error_analysis: str  # 错因分析
    suggested_questions: List[Dict[str, Any]]  # 举一反三题目

    # ======== 元数据 ========
    subject: str  # 学科
    difficulty: str  # 难度
    current_step: str  # 当前步骤
    progress: float  # 进度 (0-100)
    errors: Annotated[List[str], add]  # 错误信息列表 (追加模式)


def create_agent_graph():
    """
    创建Agent工作流图
    
    工作流:
    1. extract_info: 解析原始输入，提取结构化信息
    2. save_to_db: 保存到PostgreSQL数据库
    3. generate_embedding: 生成题目向量
    4. save_to_vectorstore: 保存向量到ChromaDB
    5. analyze_error: AI分析错因
    6. generate_suggestions: 生成举一反三题目
    7. update_final_result: 更新最终结果到数据库
    """
    from . import nodes

    # Create workflow graph
    workflow = StateGraph(AgentState)

    # Add nodes
    workflow.add_node("extract_info", nodes.extract_info)
    workflow.add_node("save_to_db", nodes.save_to_db)
    workflow.add_node("generate_embedding", nodes.generate_embedding)
    workflow.add_node("save_to_vectorstore", nodes.save_to_vectorstore)
    workflow.add_node("analyze_error", nodes.analyze_error)
    workflow.add_node("generate_suggestions", nodes.generate_suggestions)
    workflow.add_node("update_final_result", nodes.update_final_result)

    # Define edges (linear flow)
    workflow.set_entry_point("extract_info")

    workflow.add_edge("extract_info", "save_to_db")
    workflow.add_edge("save_to_db", "generate_embedding")
    workflow.add_edge("generate_embedding", "save_to_vectorstore")
    workflow.add_edge("save_to_vectorstore", "analyze_error")
    workflow.add_edge("analyze_error", "generate_suggestions")
    workflow.add_edge("generate_suggestions", "update_final_result")
    workflow.add_edge("update_final_result", END)

    # Compile graph
    app = workflow.compile()

    logger.info("Agent workflow graph created successfully")
    return app


def create_analysis_only_graph():
    """
    创建仅分析的工作流图 (用于已存在的题目重新分析)
    
    工作流:
    1. analyze_error: AI分析错因
    2. generate_suggestions: 生成举一反三题目
    3. update_final_result: 更新结果
    """
    from . import nodes

    workflow = StateGraph(AgentState)

    workflow.add_node("analyze_error", nodes.analyze_error)
    workflow.add_node("generate_suggestions", nodes.generate_suggestions)
    workflow.add_node("update_final_result", nodes.update_final_result)

    workflow.set_entry_point("analyze_error")
    workflow.add_edge("analyze_error", "generate_suggestions")
    workflow.add_edge("generate_suggestions", "update_final_result")
    workflow.add_edge("update_final_result", END)

    return workflow.compile()


# Pre-compiled graphs (lazy initialization)
_main_graph = None
_analysis_graph = None


def get_main_graph():
    """Get main agent graph (lazy initialization)"""
    global _main_graph
    if _main_graph is None:
        _main_graph = create_agent_graph()
    return _main_graph


def get_analysis_graph():
    """Get analysis-only graph (lazy initialization)"""
    global _analysis_graph
    if _analysis_graph is None:
        _analysis_graph = create_analysis_only_graph()
    return _analysis_graph

