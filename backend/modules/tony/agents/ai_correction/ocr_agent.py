"""
OCR Agent - 试卷识别与分析 Agent

使用 Gemini 2.5 Flash 进行试卷 OCR 和智能批改
支持多学科: 数学、物理、化学、英语、语文
"""

import logging
from typing import Dict, Any, Optional, List

from langgraph.graph import StateGraph, END

from backend.core.agents.state import AgentState
from backend.core.agents.base_agent import BaseAgent
from backend.modules.tony.config import settings

logger = logging.getLogger(__name__)

class OCRAgentState(AgentState):
    """
    OCR Agent 专用状态
    """
    # 图片处理
    image_path: str  # 原始图片路径
    corrected_image_path: str  # 批改后图片路径

    # OCR 结果
    ocr_text: str  # 识别的文本
    questions: List[Dict[str, Any]]  # 识别的题目列表

    # 批改结果
    grading_result: Dict[str, Any]  # 批改结果
    total_score: float  # 总分
    total_possible: float  # 满分

    # 分析结果
    weak_points: List[str]  # 薄弱知识点
    improvement_suggestions: List[str]  # 改进建议

# ============ Graph Nodes ============

async def ocr_extract(state: OCRAgentState) -> Dict[str, Any]:
    """
    OCR 提取节点 - 使用 Gemini 识别图片内容
    """
    logger.info(f"[ocr_extract] Task {state.get('task_id')}: Extracting text from image")

    from backend.core.services.gemini_ocr_service import GeminiOCRService

    image_urls = state.get("image_urls", [])
    image_path = state.get("image_path", "")
    subject = state.get("subject", "math")

    if not image_urls and not image_path:
        return {
            "errors": ["没有提供图片"],
            "current_step": "ocr_extract",
            "progress": 10.0,
        }

    try:
        ocr_service = GeminiOCRService()

        # 使用第一张图片或指定路径
        target_image = image_path or image_urls[0]

        # 调用 Gemini OCR
        result = await ocr_service.analyze_exam_image(
            image_path=target_image,
            subject=subject,
        )

        if not result.get("success"):
            return {
                "errors": [result.get("error", "OCR 处理失败")],
                "current_step": "ocr_extract",
                "progress": 10.0,
            }

        questions = result.get("questions", [])
        total_score = result.get("total_score", 0)
        total_possible = result.get("total_possible", 100)

        logger.info(f"[ocr_extract] Extracted {len(questions)} questions, score: {total_score}/{total_possible}")

        return {
            "ocr_text": result.get("raw_text", ""),
            "questions": questions,
            "grading_result": result,
            "total_score": total_score,
            "total_possible": total_possible,
            "corrected_image_path": result.get("corrected_image_path", ""),
            "current_step": "ocr_extract",
            "progress": 40.0,
        }

    except Exception as e:
        logger.error(f"[ocr_extract] Error: {e}")
        return {
            "errors": [f"OCR 处理错误: {str(e)}"],
            "current_step": "ocr_extract",
            "progress": 10.0,
        }

async def analyze_errors(state: OCRAgentState) -> Dict[str, Any]:
    """
    错误分析节点 - 分析学生的错误模式
    """
    logger.info(f"[analyze_errors] Task {state.get('task_id')}: Analyzing errors")

    from backend.core.services.llm_service import get_llm_service

    questions = state.get("questions", [])
    subject = state.get("subject", "math")

    if not questions:
        return {
            "weak_points": [],
            "improvement_suggestions": ["没有可分析的题目"],
            "current_step": "analyze_errors",
            "progress": 60.0,
        }

    # 找出错误的题目
    wrong_questions = [q for q in questions if not q.get("is_correct", True)]

    if not wrong_questions:
        return {
            "weak_points": [],
            "improvement_suggestions": ["所有题目都正确，继续保持！"],
            "error_analysis": "全部正确",
            "current_step": "analyze_errors",
            "progress": 60.0,
        }

    try:
        llm = get_llm_service()

        # 构建错题分析提示
        questions_text = "\n".join([
            f"题目{i+1}: {q.get('question', '')}\n"
            f"学生答案: {q.get('student_answer', '未作答')}\n"
            f"正确答案: {q.get('correct_answer', '未知')}\n"
            f"知识点: {', '.join(q.get('knowledge_points', []))}"
            for i, q in enumerate(wrong_questions)
        ])

        analysis_prompt = f"""请分析以下{subject}学科的错题，找出学生的薄弱知识点和错误模式：

{questions_text}

请以JSON格式返回分析结果：
{{
    "weak_points": ["薄弱知识点1", "薄弱知识点2", ...],
    "error_patterns": ["错误模式1", "错误模式2", ...],
    "improvement_suggestions": ["建议1", "建议2", ...],
    "summary": "总体分析摘要"
}}"""

        result = await llm.generate_json(
            prompt=analysis_prompt,
            temperature=0.5,
        )

        if result:
            return {
                "weak_points": result.get("weak_points", []),
                "improvement_suggestions": result.get("improvement_suggestions", []),
                "error_analysis": result.get("summary", ""),
                "current_step": "analyze_errors",
                "progress": 60.0,
            }

    except Exception as e:
        logger.error(f"[analyze_errors] Error: {e}")

    return {
        "weak_points": [],
        "improvement_suggestions": [],
        "current_step": "analyze_errors",
        "progress": 60.0,
    }

async def save_results(state: OCRAgentState) -> Dict[str, Any]:
    """
    保存结果节点 - 将分析结果保存到数据库
    """
    logger.info(f"[save_results] Task {state.get('task_id')}: Saving results")

    from backend.core.db.session import async_session_maker
    from backend.core.crud.crud_question import create_question
    from backend.core.schemas.question import QuestionCreate, SubjectType, DifficultyLevel

    user_id = state.get("user_id")
    questions = state.get("questions", [])

    if not user_id or not questions:
        return {
            "current_step": "save_results",
            "progress": 80.0,
        }

    try:
        subject_map = {
            "math": SubjectType.MATH,
            "physics": SubjectType.PHYSICS,
            "chemistry": SubjectType.CHEMISTRY,
            "english": SubjectType.ENGLISH,
            "chinese": SubjectType.CHINESE,
        }

        saved_question_ids = []

        async with async_session_maker() as session:
            # 只保存错误的题目
            wrong_questions = [q for q in questions if not q.get("is_correct", True)]

            for q in wrong_questions:
                question_data = QuestionCreate(
                    content=q.get("question", ""),
                    subject=subject_map.get(state.get("subject", "math"), SubjectType.OTHER),
                    difficulty=DifficultyLevel.MEDIUM,
                    student_answer=q.get("student_answer"),
                    correct_answer=q.get("correct_answer"),
                    tags=q.get("knowledge_points", []),
                    image_urls=state.get("image_urls", []),
                )

                question = await create_question(session, question_data, user_id)
                saved_question_ids.append(question.id)

            await session.commit()

        logger.info(f"[save_results] Saved {len(saved_question_ids)} questions")

        return {
            "question_id": saved_question_ids[0] if saved_question_ids else None,
            "saved_question_ids": saved_question_ids,
            "current_step": "save_results",
            "progress": 80.0,
        }

    except Exception as e:
        logger.error(f"[save_results] Error: {e}")
        return {
            "errors": [f"保存失败: {str(e)}"],
            "current_step": "save_results",
            "progress": 80.0,
        }

async def generate_practice(state: OCRAgentState) -> Dict[str, Any]:
    """
    生成练习节点 - 基于错题生成相似练习题
    """
    logger.info(f"[generate_practice] Task {state.get('task_id')}: Generating practice")

    from backend.core.services.hybrid_search_service import HybridSearchService

    weak_points = state.get("weak_points", [])
    subject = state.get("subject", "math")
    user_id = state.get("user_id")

    if not weak_points:
        return {
            "suggested_questions": [],
            "current_step": "generate_practice",
            "progress": 100.0,
        }

    try:
        # 使用混合检索找相似题目
        search_service = HybridSearchService()

        # 基于薄弱知识点搜索
        search_query = " ".join(weak_points[:3])  # 最多使用3个知识点

        results = await search_service.hybrid_search(
            query=search_query,
            top_k=5,
            filter_metadata={"subject": subject},
        )

        suggested_questions = []
        for doc_id, score, metadata, content in results:
            if int(doc_id) not in state.get("saved_question_ids", []):
                suggested_questions.append({
                    "question_id": doc_id,
                    "content": content,
                    "similarity_score": score,
                    "knowledge_points": metadata.get("knowledge_points", "").split(","),
                })

        return {
            "suggested_questions": suggested_questions[:5],
            "current_step": "generate_practice",
            "progress": 100.0,
        }

    except Exception as e:
        logger.error(f"[generate_practice] Error: {e}")
        return {
            "suggested_questions": [],
            "current_step": "generate_practice",
            "progress": 100.0,
        }

# ============ Graph Definition ============

def create_ocr_agent_graph():
    """
    创建 OCR Agent 工作流图

    流程:
    1. ocr_extract: OCR 提取图片内容
    2. analyze_errors: 分析错误模式
    3. save_results: 保存结果到数据库
    4. generate_practice: 生成相似练习题
    """
    workflow = StateGraph(OCRAgentState)

    # 添加节点
    workflow.add_node("ocr_extract", ocr_extract)
    workflow.add_node("analyze_errors", analyze_errors)
    workflow.add_node("save_results", save_results)
    workflow.add_node("generate_practice", generate_practice)

    # 定义边
    workflow.set_entry_point("ocr_extract")
    workflow.add_edge("ocr_extract", "analyze_errors")
    workflow.add_edge("analyze_errors", "save_results")
    workflow.add_edge("save_results", "generate_practice")
    workflow.add_edge("generate_practice", END)

    return workflow.compile()

# 懒加载编译的图
_ocr_graph = None

def get_ocr_graph():
    """获取 OCR Agent 图（懒加载）"""
    global _ocr_graph
    if _ocr_graph is None:
        _ocr_graph = create_ocr_agent_graph()
    return _ocr_graph

class OCRAgent(BaseAgent):
    """
    OCR Agent 类
    提供高层接口用于试卷分析
    """

    def __init__(self):
        super().__init__(subjects=settings.SUBJECTS)
        self.graph = get_ocr_graph()

    async def process(
        self,
        image_path: str,
        user_id: int,
        task_id: str,
        subject: str = "math",
    ) -> Dict[str, Any]:
        """
        处理试卷图片

        Args:
            image_path: 图片路径
            user_id: 用户ID
            task_id: 任务ID
            subject: 学科

        Returns:
            处理结果
        """
        # Validate subject
        if not self.validate_subject(subject):
            logger.error(f"Subject '{subject}' not supported by TONY module")
            return {
                "task_id": task_id,
                "success": False,
                "total_score": 0,
                "total_possible": 100,
                "questions": [],
                "weak_points": [],
                "suggestions": [],
                "similar_questions": [],
                "corrected_image": "",
                "errors": [f"Subject '{subject}' not supported by TONY module. Supported: {settings.SUBJECTS}"],
            }

        initial_state: OCRAgentState = {
            "image_path": image_path,
            "image_urls": [image_path],
            "user_id": user_id,
            "task_id": task_id,
            "subject": subject,
            "errors": [],
        }

        final_state = None
        async for state in self.graph.astream(initial_state):
            for node_name, node_output in state.items():
                if isinstance(node_output, dict):
                    final_state = {**initial_state, **(final_state or {}), **node_output}

        return {
            "task_id": task_id,
            "success": not bool(final_state.get("errors", [])) if final_state else False,
            "total_score": final_state.get("total_score", 0) if final_state else 0,
            "total_possible": final_state.get("total_possible", 100) if final_state else 100,
            "questions": final_state.get("questions", []) if final_state else [],
            "weak_points": final_state.get("weak_points", []) if final_state else [],
            "suggestions": final_state.get("improvement_suggestions", []) if final_state else [],
            "similar_questions": final_state.get("suggested_questions", []) if final_state else [],
            "corrected_image": final_state.get("corrected_image_path", "") if final_state else "",
            "errors": final_state.get("errors", []) if final_state else [],
        }
