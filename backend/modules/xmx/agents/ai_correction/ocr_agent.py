"""
OCR Agent - 试卷识别与分析 Agent (XMX 模块对齐 Tony 版本)
"""

import logging
import uuid
import json
import re
from typing import Dict, Any, List, Optional

from langgraph.graph import StateGraph, END

from backend.core.agents.base_agent import BaseAgent
from backend.core.agents.state import AgentState
from backend.modules.xmx.config import settings

logger = logging.getLogger(__name__)

# ============ Utils ============

def clean_json_response(raw_str: str) -> str:
    """清洗 AI 返回的 Markdown JSON 标签"""
    if not raw_str or not isinstance(raw_str, str):
        return ""
    json_block = re.search(r'```json\s*(.*?)\s*```', raw_str, re.DOTALL)
    if json_block:
        return json_block.group(1).strip()
    brace_match = re.search(r'(\{.*\})', raw_str, re.DOTALL)
    if brace_match:
        return brace_match.group(1).strip()
    return raw_str.strip()

# ============ Agent State ============

class OCRAgentState(AgentState):
    """
    OCR Agent 专用状态 (与 Tony 对齐)
    """
    image_path: str
    image_urls: List[str] = []
    corrected_image_path: str = ""
    
    ocr_text: str = ""
    questions: List[Dict[str, Any]] = []
    
    grading_result: Dict[str, Any] = {}
    total_score: float = 0.0
    total_possible: float = 100.0
    
    weak_points: List[str] = []
    improvement_suggestions: List[str] = []
    suggested_questions: List[Dict[str, Any]] = []

# ============ Graph Nodes ============

async def ocr_extract_node(state: OCRAgentState) -> Dict[str, Any]:
    """
    OCR 提取节点 - 使用 Gemini 识别并初步批改
    """
    try:
        from backend.core.services.gemini_ocr_service import GeminiOCRService, SubjectType
        ocr_service = GeminiOCRService()
        
        subject_str = state.get("subject", "economics")
        try:
            subject_type = SubjectType(subject_str)
        except:
            subject_type = SubjectType.OTHER
        
        # 调用核心 OCR 服务
        result_obj = await ocr_service.analyze_exam_image(
            image_path=state.get("image_path"),
            subject=subject_type
        )

        # 数据清洗适配 (针对 ExamAnalysisResult 对象)
        questions = []
        raw_qs = getattr(result_obj, "questions", [])
        for q in raw_qs:
            if hasattr(q, "model_dump"):
                questions.append(q.model_dump())
            elif isinstance(q, dict):
                questions.append(q)

        return {
            "ocr_text": getattr(result_obj, "raw_text", ""),
            "questions": questions,
            "total_score": float(getattr(result_obj, "total_score", 0)),
            "total_possible": float(getattr(result_obj, "max_score", 100)),
            "corrected_image_path": getattr(result_obj, "corrected_image_path", ""),
            "current_step": "ocr_extract",
            "progress": 40.0
        }
    except Exception as e:
        logger.error(f"OCR Node Error: {e}")
        return {"errors": [f"OCR提取失败: {str(e)}"], "progress": 10.0}

async def analyze_errors_node(state: OCRAgentState) -> Dict[str, Any]:
    """
    错误分析节点 - 提取薄弱点和建议
    """
    questions = state.get("questions", [])
    if not questions:
        return {"weak_points": [], "improvement_suggestions": ["未能识别到题目"], "progress": 60.0}

    # 简单的逻辑：提取 OCR 结果中的 analysis 字段
    # 如果需要更深度的 LLM 分析，可以在此处调用 llm.generate_json
    weak_points = []
    for q in questions:
        if not q.get("is_correct", True):
            weak_points.extend(q.get("knowledge_points", []))
    
    # 去重
    weak_points = list(set(weak_points))
    
    return {
        "weak_points": weak_points,
        "improvement_suggestions": ["建议加强对相关公式的记忆"] if weak_points else ["表现完美！"],
        "current_step": "analyze_errors",
        "progress": 70.0
    }

async def save_results_node(state: OCRAgentState) -> Dict[str, Any]:
    """
    保存结果节点 (对应 Tony 的 save_results)
    """
    # 实际项目中，这里会调用 CRUD 将错题存入题库，目前返回进度
    return {"current_step": "save_results", "progress": 90.0}

async def generate_practice_node(state: OCRAgentState) -> Dict[str, Any]:
    """
    推荐练习节点 (对应 Tony 的 generate_practice)
    """
    # 此处可对接 HybridSearchService
    return {
        "suggested_questions": [], 
        "current_step": "generate_practice", 
        "progress": 100.0
    }

# ============ Agent Implementation ============

class OCRAgent(BaseAgent):
    def __init__(self):
        super().__init__(subjects=settings.SUBJECTS)
        self.graph = self._build_workflow()

    def _build_workflow(self):
        wf = StateGraph(OCRAgentState)
        
        # 添加节点 (路径对齐 Tony)
        wf.add_node("ocr_extract", ocr_extract_node)
        wf.add_node("analyze_errors", analyze_errors_node)
        wf.add_node("save_results", save_results_node)
        wf.add_node("generate_practice", generate_practice_node)
        
        # 定义边
        wf.set_entry_point("ocr_extract")
        wf.add_edge("ocr_extract", "analyze_errors")
        wf.add_edge("analyze_errors", "save_results")
        wf.add_edge("save_results", "generate_practice")
        wf.add_edge("generate_practice", END)
        
        return wf.compile()

    async def process(self, **kwargs) -> Dict[str, Any]:
        """
        核心处理函数 - 结构完全对齐 Tony 模块
        """
        task_id = kwargs.get("task_id", str(uuid.uuid4()))
        subject = kwargs.get("subject", "math")
        
        # 1. 学科验证
        if not self.validate_subject(subject):
            return {
                "task_id": task_id,
                "success": False,
                "errors": [f"Subject '{subject}' not supported by XMX module."]
            }

        initial_state = {
            **kwargs,
            "image_urls": [kwargs.get("image_path")] if kwargs.get("image_path") else [],
            "questions": [],
            "errors": [],
            "progress": 0.0
        }

        try:
            current_state = initial_state
            async for chunk in self.graph.astream(initial_state):
                for output in chunk.values():
                    current_state.update(output)

            # 2. 构造与 Tony/前端 API 1:1 对应的返回结构
            
            return {
                "task_id": task_id,
                "success": not bool(current_state.get("errors")),
                "total_score": current_state.get("total_score", 0.0),
                "total_possible": current_state.get("total_possible", 100.0),
                "questions": current_state.get("questions", []),
                "weak_points": current_state.get("weak_points", []),
                "suggestions": current_state.get("improvement_suggestions", []),
                "similar_questions": current_state.get("suggested_questions", []),
                "corrected_image": current_state.get("corrected_image_path", ""),
                "errors": current_state.get("errors", [])
            }

        except Exception as e:
            logger.error(f"Agent Final Process Error: {e}")
            return {
                "task_id": task_id,
                "success": False,
                "errors": [str(e)],
                "questions": []
            }