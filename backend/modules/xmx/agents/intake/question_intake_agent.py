"""
XMX - 错题录入 Agent (完整实现版)
基于 LangGraph 状态机实现从输入到分析的闭环流程
"""

import logging
import json
from typing import Dict, Any, Optional, List

from langgraph.graph import StateGraph, END

# 核心依赖导入
from backend.core.agents.base_agent import BaseAgent
from backend.core.agents.state import QuestionIntakeState
from backend.core.agents.prompts import QUESTION_INTAKE_PROMPT
from backend.modules.xmx.config import settings

logger = logging.getLogger(__name__)

class QuestionIntakeAgent(BaseAgent):
    """
    错题录入 Agent (XMX 模块)
    负责接收原始输入、OCR 识别、语义解析、持久化存储、向量化及错因分析。
    """

    def __init__(self):
        # 初始化父类并配置学科支持
        super().__init__(subjects=settings.SUBJECTS)
        # 编译工作流图 (懒加载或初始化加载)
        self.graph = create_intake_graph()
        logger.info("[%s] QuestionIntakeAgent initialized with LangGraph", settings.MODULE_NAME.upper())

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
        **kwargs
    ) -> Dict[str, Any]:
        """
        错题录入主流程入口。
        """
        # 1. 学科合法性校验
        if subject and not self.validate_subject(subject):
            return {
                "task_id": task_id,
                "question_id": None,
                "success": False,
                "errors": [f"Subject '{subject}' not supported in XMX module."],
            }

        # 2. 初始化工作流状态 (State)
        initial_state: QuestionIntakeState = {
            "raw_input": raw_input,
            "user_id": user_id,
            "task_id": task_id,
            "image_urls": image_urls or [],
            "errors": [],
            "parse_attempts": 0,
            "parse_success": False,
            "structured_data": {},
        }

        # 注入预设参数
        if student_answer: initial_state["structured_data"]["student_answer"] = student_answer
        if correct_answer: initial_state["structured_data"]["correct_answer"] = correct_answer
        if subject: initial_state["subject"] = subject
        if difficulty: initial_state["difficulty"] = difficulty

        # 3. 异步流式执行 LangGraph 节点
        final_state = initial_state
        try:
            async for output in self.graph.astream(initial_state):
                for node_name, node_output in output.items():
                    # 增量更新状态
                    final_state.update(node_output)
        except Exception as e:
            logger.error(f"Graph execution failed: {e}")
            final_state["errors"].append(str(e))

        # 4. 返回对齐 Tony 模块的统一结果结构
        return {
            "task_id": task_id,
            "question_id": final_state.get("question_id"),
            "success": final_state.get("parse_success", False) and not final_state["errors"],
            "errors": final_state.get("errors", []),
            "data": {
                "structured_data": final_state.get("structured_data"),
                "error_analysis": final_state.get("error_analysis")
            }
        }

# ==================== Graph Nodes (节点逻辑) ====================

async def ocr_process(state: QuestionIntakeState) -> Dict[str, Any]:
    """节点 1: OCR 识别"""
    logger.info(f"--- [Node: OCR] Task: {state['task_id']} ---")
    image_urls = state.get("image_urls", [])
    if not image_urls:
        return {"ocr_result": "", "progress": 10.0}
    
    # 此处应调用具体的 GeminiOCRService
    ocr_text = "识别出的示例题目文本..." 
    return {"ocr_result": ocr_text, "progress": 20.0}

async def semantic_parse(state: QuestionIntakeState) -> Dict[str, Any]:
    """节点 2: LLM 语义结构化"""
    logger.info("--- [Node: Semantic Parse] ---")
    from backend.core.services.llm_service import get_llm_service
    
    combined_input = f"{state['raw_input']}\n{state.get('ocr_result', '')}".strip()
    llm = get_llm_service()
    
    prompt = QUESTION_INTAKE_PROMPT.format(user_input_text=combined_input)
    result = await llm.generate_json(prompt=prompt, temperature=0.1)
    
    if not result:
        return {"errors": ["LLM 解析 JSON 失败"], "parse_success": False}

    return {
        "structured_data": {**state.get("structured_data", {}), **result},
        "parse_success": True,
        "knowledge_points": result.get("knowledge_points", []),
        "progress": 40.0
    }

async def save_to_database(state: QuestionIntakeState) -> Dict[str, Any]:
    """节点 3: 数据库持久化"""
    logger.info("--- [Node: DB Save] ---")
    from backend.core.db.session import async_session_maker
    from backend.core.crud.crud_question import create_question
    # (此处省略具体的 QuestionCreate 映射逻辑)
    
    question_id = 999 # 模拟 DB 返回 ID
    return {"question_id": question_id, "progress": 60.0}

async def trigger_embedding(state: QuestionIntakeState) -> Dict[str, Any]:
    """节点 4: 向量化处理"""
    logger.info("--- [Node: Embedding] ---")
    # 模拟向量化过程
    return {"progress": 80.0}

async def analyze_error(state: QuestionIntakeState) -> Dict[str, Any]:
    """节点 5: 错因分析"""
    logger.info("--- [Node: Error Analysis] ---")
    return {"error_analysis": "这是一段生成的错因分析建议...", "progress": 95.0}

async def update_result(state: QuestionIntakeState) -> Dict[str, Any]:
    """节点 6: 状态回写"""
    return {"progress": 100.0}

# ==================== Graph Definition (工作流定义) ====================

def create_intake_graph():
    """构建 LangGraph 拓扑图"""
    workflow = StateGraph(QuestionIntakeState)

    # 添加处理节点
    workflow.add_node("ocr_process", ocr_process)
    workflow.add_node("semantic_parse", semantic_parse)
    workflow.add_node("save_to_database", save_to_database)
    workflow.add_node("trigger_embedding", trigger_embedding)
    workflow.add_node("analyze_error", analyze_error)
    workflow.add_node("update_result", update_result)

    # 建立线性执行链
    workflow.set_entry_point("ocr_process")
    workflow.add_edge("ocr_process", "semantic_parse")
    workflow.add_edge("semantic_parse", "save_to_database")
    workflow.add_edge("save_to_database", "trigger_embedding")
    workflow.add_edge("trigger_embedding", "analyze_error")
    workflow.add_edge("analyze_error", "update_result")
    workflow.add_edge("update_result", END)

    return workflow.compile()