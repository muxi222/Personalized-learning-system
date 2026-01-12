import logging
import uuid
import json
import re
from typing import Dict, Any, List
from langgraph.graph import StateGraph, END

from backend.core.agents.base_agent import BaseAgent
from backend.core.agents.state import AgentState
from backend.modules.xmx.config import settings

logger = logging.getLogger(__name__)

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

class OCRAgentState(AgentState):
    image_path: str
    subject: str
    user_id: int
    task_id: str
    ocr_result: Dict[str, Any] = {}
    questions: List[Dict[str, Any]] = []
    analysis_report: Dict[str, Any] = {}
    errors: List[str] = []

async def ocr_process_node(state: OCRAgentState) -> Dict[str, Any]:
    """核心节点：极其鲁棒的 OCR 数据解析"""
    try:
        from backend.core.services.gemini_ocr_service import GeminiOCRService, SubjectType
        ocr_service = GeminiOCRService()
        
        subject_str = state.get("subject", "economics")
        try:
            subject_type = SubjectType(subject_str)
        except:
            subject_type = SubjectType.OTHER
        
        # 1. 调用 Gemini 获取结果
        result_obj = await ocr_service.analyze_exam_image(
            image_path=state.get("image_path"),
            subject=subject_type
        )

        # 2. 多重适配解析逻辑 (针对 ExamAnalysisResult 对象优化)
        res_dict = {}
        
        # 路径 A: 尝试 Pydantic 序列化 (v2: model_dump, v1: dict)
        if hasattr(result_obj, "model_dump"):
            res_dict = result_obj.model_dump()
        elif hasattr(result_obj, "dict"):
            res_dict = result_obj.dict()
        
        # 路径 B: 已经是字典
        elif isinstance(result_obj, dict):
            res_dict = result_obj
            
        # 路径 C: 原始字符串处理
        elif isinstance(result_obj, str):
            try:
                cleaned_text = clean_json_response(result_obj)
                res_dict = json.loads(cleaned_text)
            except:
                return {"errors": ["AI返回字符串解析失败"], "questions": []}
        
        # 路径 D: 暴力反射 (针对日志中 ExamAnalysisResult 类属性提取)
        else:
            logger.info(f"Falling back to attribute reflection for type: {type(result_obj)}")
            res_dict = {
                "questions": getattr(result_obj, "questions", []),
                "total_score": getattr(result_obj, "total_score", 0),
                "max_score": getattr(result_obj, "max_score", 100),
                "accuracy_rate": getattr(result_obj, "accuracy_rate", 0),
                "overall_analysis": getattr(result_obj, "overall_analysis", ""),
                "subject": str(getattr(result_obj, "subject", ""))
            }

        # 3. 统一数据结构清洗
        raw_questions = res_dict.get("questions") or []
        # 处理 Pydantic 对象列表转为 纯 Dict 列表
        questions = []
        for q in raw_questions:
            if hasattr(q, "model_dump"):
                questions.append(q.model_dump())
            elif hasattr(q, "dict"):
                questions.append(q.dict())
            elif isinstance(q, dict):
                questions.append(q)
            else:
                # 尝试通过 __dict__ 获取
                questions.append(vars(q) if hasattr(q, "__dict__") else {})

        return {
            "questions": questions,
            "ocr_result": {
                "total_score": float(res_dict.get("total_score") or 0),
                "max_score": float(res_dict.get("max_score") or 100),
                "accuracy_rate": float(res_dict.get("accuracy_rate") or 0),
                "overall_analysis": res_dict.get("overall_analysis", "批改完成")
            }
        }
        
    except Exception as e:
        logger.error(f"OCR Node Error: {str(e)}", exc_info=True)
        return {"errors": [f"解析异常: {str(e)}"], "questions": []}

async def analysis_node(state: OCRAgentState) -> Dict[str, Any]:
    """分析节点：从 OCR 结果中提取建议"""
    ocr_res = state.get("ocr_result", {})
    return {
        "analysis_report": {
            "suggestions": [ocr_res.get("overall_analysis", "分析完成")],
            "weak_points": state.get("analysis_report", {}).get("weak_points", [])
        }
    }

class OCRAgent(BaseAgent):
    def __init__(self):
        super().__init__(subjects=settings.SUBJECTS)
        self.graph = self._build_workflow()

    def _build_workflow(self):
        wf = StateGraph(OCRAgentState)
        wf.add_node("ocr", ocr_process_node)
        wf.add_node("analysis", analysis_node)
        wf.set_entry_point("ocr")
        wf.add_edge("ocr", "analysis")
        wf.add_edge("analysis", END)
        return wf.compile()

async def process(self, **kwargs) -> Dict[str, Any]:
    task_id = kwargs.get("task_id", str(uuid.uuid4()))
    # 初始化状态时确保所有预期字段都存在
    initial_state = {
        **kwargs, 
        "questions": [], 
        "errors": [], 
        "ocr_result": {}, 
        "analysis_report": {}
    }
    
    try:
        current_state = initial_state
        async for chunk in self.graph.astream(initial_state):
            for output in chunk.values():
                current_state.update(output)
        
        # 核心：构造与前端/API模型 1:1 对应的返回结构
        ocr_res = current_state.get("ocr_result", {})
        analysis = current_state.get("analysis_report", {})
        
        return {
            "success": not bool(current_state.get("errors")),
            "task_id": task_id,
            "data": {
                # 必须确保这些 key 与你的 Pydantic Schema (OCRAnalysisResponse) 完全一致
                "subject": current_state.get("subject", "economics"),
                "questions": current_state.get("questions", []),  # 即使失败也要给空列表
                "total_score": float(ocr_res.get("total_score", 0)),
                "max_score": float(ocr_res.get("max_score", 100)),
                "accuracy_rate": float(ocr_res.get("accuracy_rate", 0)),
                "overall_analysis": ocr_res.get("overall_analysis", ""),
                "weak_points": analysis.get("weak_points", []),
                "improvement_suggestions": analysis.get("suggestions", [])
            },
            "errors": current_state.get("errors")
        }
    except Exception as e:
        logger.error(f"Agent Final Process Error: {e}")
        return {
            "success": False, 
            "data": {"questions": [], "total_score": 0}, # 保证基础结构
            "errors": [str(e)]
        }