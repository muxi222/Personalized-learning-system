"""
举一反三Agent - Similar Question Agent
根据设计文档4.2节实现 RAG流程

功能流程:
1. 向量检索 - 从向量数据库检索相似题目
2. 信息整合 - 获取题目详情
3. 生成引导 - 使用LLM生成引导文本
"""

import logging
from typing import Dict, Any, List, Optional

from langgraph.graph import StateGraph, END

from backend.core.agents.state import SimilarQuestionState
from backend.core.agents.prompts import SIMILAR_QUESTION_PROMPT
from backend.core.agents.base_agent import BaseAgent
from backend.modules.wzy.config import settings  # 修改：tony -> wzy

logger = logging.getLogger(__name__)


class SimilarQuestionAgent(BaseAgent):
    """
    举一反三Agent
    基于RAG技术推荐相关题目
    """

    def __init__(self):
        super().__init__(subjects=settings.SUBJECTS)
        self.graph = create_similar_question_graph()
    
    async def find_similar(
        self,
        question_id: int,
        user_id: int,
        top_k: int = 5,
        student_profile: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """
        查找相似题目并生成引导
        
        Args:
            question_id: 原题ID
            user_id: 用户ID
            top_k: 返回数量
            student_profile: 学生画像 (用于个性化)
        
        Returns:
            包含推荐题目和引导文本的结果
        """
        initial_state: SimilarQuestionState = {
            "question_id": question_id,
            "user_id": user_id,
            "task_id": f"similar_{question_id}",
            "retrieved_question_ids": [],
            "retrieved_questions": [],
            "similarity_scores": [],
            "errors": [],
            "student_profile": student_profile or {},
        }
        
        # 设置检索数量 (存储在state中供节点使用)
        initial_state["_top_k"] = top_k
        
        final_state = None
        async for state in self.graph.astream(initial_state):
            for node_name, node_output in state.items():
                if isinstance(node_output, dict):
                    final_state = {**initial_state, **(final_state or {}), **node_output}
        
        return {
            "question_id": question_id,
            "similar_questions": final_state.get("recommended_questions", []) if final_state else [],
            "guidance_text": final_state.get("guidance_text", "") if final_state else "",
            "errors": final_state.get("errors", []) if final_state else [],
        }


# ============ Graph Nodes ============

async def load_original_question(state: SimilarQuestionState) -> Dict[str, Any]:
    """
    加载原题信息节点
    """
    logger.info(f"[load_original] Loading question {state.get('question_id')}")
    
    from backend.core.db.session import async_session_maker
    from backend.core.crud.crud_question import get_question
    
    question_id = state.get("question_id")
    user_id = state.get("user_id")
    
    if not question_id:
        return {
            "errors": ["缺少原题ID"],
            "current_step": "load_original",
            "progress": 10.0,
        }
    
    try:
        async with async_session_maker() as session:
            question = await get_question(session, question_id, user_id)
            
            if not question:
                return {
                    "errors": ["找不到原题"],
                    "current_step": "load_original",
                    "progress": 10.0,
                }
            
            original_question = {
                "id": question.id,
                "content": question.content,
                "subject": question.subject.value if question.subject else "other",
                "difficulty": question.difficulty.value if question.difficulty else "medium",
                "student_answer": question.student_answer,
                "correct_answer": question.correct_answer,
                "knowledge_points": question.knowledge_points or [],
                "error_analysis": question.error_analysis,
            }
            
            return {
                "original_question": original_question,
                "original_error_analysis": question.error_analysis or "",
                "subject": original_question["subject"],
                "knowledge_points": original_question["knowledge_points"],
                "current_step": "load_original",
                "progress": 20.0,
            }
    
    except Exception as e:
        logger.error(f"[load_original] Error: {e}")
        return {
            "errors": [f"加载原题失败: {str(e)}"],
            "current_step": "load_original",
            "progress": 10.0,
        }


async def vector_retrieval(state: SimilarQuestionState) -> Dict[str, Any]:
    """
    向量检索节点 - RAG的Retrieval阶段
    根据设计文档4.2节: 使用当前错题的向量进行相似度搜索
    """
    logger.info(f"[vector_retrieval] Searching similar questions")
    
    from backend.core.services.embedding_service import get_embedding_service
    from backend.core.services.vector_store_service import get_vector_store_service
    
    original_question = state.get("original_question", {})
    question_id = state.get("question_id")
    user_id = state.get("user_id")
    top_k = state.get("_top_k", 5)
    
    if not original_question:
        return {
            "errors": ["缺少原题信息"],
            "current_step": "vector_retrieval",
            "progress": 40.0,
        }
    
    try:
        # 初始化服务
        embedding_service = get_embedding_service()
        vector_store = get_vector_store_service()
        await vector_store.initialize()
        
        # 生成查询向量
        query_text = original_question.get("content", "")
        knowledge_points = original_question.get("knowledge_points", [])
        if knowledge_points:
            query_text = f"{query_text}\n知识点: {', '.join(knowledge_points)}"
        
        query_embedding = await embedding_service.embed_text(query_text)
        
        if not query_embedding:
            return {
                "errors": ["生成查询向量失败"],
                "current_step": "vector_retrieval",
                "progress": 40.0,
            }
        
        # 向量检索 (多检索一些，排除自身后取top_k)
        results = await vector_store.search_similar(
            query_embedding=query_embedding,
            n_results=top_k + 5,
            where={"user_id": user_id} if user_id else None,
        )
        
        # 过滤掉原题自身
        filtered_results = [
            r for r in results
            if int(r["id"]) != question_id
        ][:top_k]
        
        retrieved_ids = [int(r["id"]) for r in filtered_results]
        similarity_scores = [r.get("score", 0) for r in filtered_results]
        
        logger.info(f"[vector_retrieval] Found {len(retrieved_ids)} similar questions")
        
        return {
            "retrieved_question_ids": retrieved_ids,
            "similarity_scores": similarity_scores,
            "current_step": "vector_retrieval",
            "progress": 50.0,
        }
    
    except Exception as e:
        logger.error(f"[vector_retrieval] Error: {e}")
        return {
            "errors": [f"向量检索失败: {str(e)}"],
            "current_step": "vector_retrieval",
            "progress": 40.0,
        }


async def fetch_question_details(state: SimilarQuestionState) -> Dict[str, Any]:
    """
    获取题目详情节点
    从结构化数据库查询检索到的题目完整信息
    """
    logger.info(f"[fetch_details] Fetching question details")
    
    from backend.core.db.session import async_session_maker
    from backend.core.crud.crud_question import get_question
    
    retrieved_ids = state.get("retrieved_question_ids", [])
    user_id = state.get("user_id")
    
    if not retrieved_ids:
        return {
            "retrieved_questions": [],
            "current_step": "fetch_details",
            "progress": 60.0,
        }
    
    try:
        questions = []
        async with async_session_maker() as session:
            for q_id in retrieved_ids:
                question = await get_question(session, q_id, user_id)
                if question:
                    questions.append({
                        "id": question.id,
                        "content": question.content,
                        "subject": question.subject.value if question.subject else "other",
                        "difficulty": question.difficulty.value if question.difficulty else "medium",
                        "correct_answer": question.correct_answer,
                        "knowledge_points": question.knowledge_points or [],
                        "chapter": question.chapter,
                    })
        
        logger.info(f"[fetch_details] Fetched {len(questions)} questions")
        
        return {
            "retrieved_questions": questions,
            "current_step": "fetch_details",
            "progress": 70.0,
        }
    
    except Exception as e:
        logger.error(f"[fetch_details] Error: {e}")
        return {
            "errors": [f"获取题目详情失败: {str(e)}"],
            "current_step": "fetch_details",
            "progress": 60.0,
        }


async def generate_guidance(state: SimilarQuestionState) -> Dict[str, Any]:
    """
    生成引导文本节点 - RAG的Generation阶段
    根据设计文档4.2节的Prompt设计
    """
    logger.info(f"[generate_guidance] Generating guidance text")
    
    from backend.core.services.llm_service import get_llm_service
    
    llm = get_llm_service()
    
    original_question = state.get("original_question", {})
    retrieved_questions = state.get("retrieved_questions", [])
    student_profile = state.get("student_profile", {})
    
    if not retrieved_questions:
        return {
            "guidance_text": "暂时没有找到相似的题目，继续加油！",
            "recommended_questions": [],
            "current_step": "generate_guidance",
            "progress": 90.0,
        }
    
    # 格式化检索到的题目
    questions_details = ""
    for i, q in enumerate(retrieved_questions, 1):
        questions_details += f"""
题目{i}:
- 内容: {q.get('content', '')}
- 知识点: {', '.join(q.get('knowledge_points', []))}
- 难度: {q.get('difficulty', '中等')}
- 参考答案: {q.get('correct_answer', '未提供')}
"""
    
    # 格式化学生画像
    profile_text = ""
    if student_profile:
        profile_text = f"""
- 年级: {student_profile.get('grade', '未知')}
- 薄弱知识点: {', '.join(student_profile.get('weak_knowledge_points', []))}
"""
    
    # 使用设计文档中的Prompt
    prompt = SIMILAR_QUESTION_PROMPT.format(
        original_question_body=original_question.get("content", ""),
        student_answer=original_question.get("student_answer", "未提供"),
        correct_answer=original_question.get("correct_answer", "未提供"),
        error_analysis_from_db=state.get("original_error_analysis", "暂无分析"),
        retrieved_questions_details=questions_details,
        student_profile=profile_text or "暂无学生画像",
    )
    
    guidance_text = await llm.generate(
        prompt=prompt,
        system_prompt="你是学习小书童，一位温暖有耐心的教学名师。",
        temperature=0.7,
        max_tokens=2000,
    )
    
    if not guidance_text:
        guidance_text = "这里有一些相关的练习题供你巩固！加油！💪"
    
    return {
        "guidance_text": guidance_text,
        "recommended_questions": retrieved_questions,
        "current_step": "generate_guidance",
        "progress": 100.0,
    }


# ============ Graph Definition ============

def create_similar_question_graph():
    """
    创建举一反三Agent的工作流图
    
    流程 (根据设计文档4.2节):
    1. load_original: 加载原题信息
    2. vector_retrieval: 向量检索相似题目 (RAG - Retrieval)
    3. fetch_details: 获取题目详情
    4. generate_guidance: 生成引导文本 (RAG - Generation)
    """
    workflow = StateGraph(SimilarQuestionState)
    
    # 添加节点
    workflow.add_node("load_original", load_original_question)
    workflow.add_node("vector_retrieval", vector_retrieval)
    workflow.add_node("fetch_details", fetch_question_details)
    workflow.add_node("generate_guidance", generate_guidance)
    
    # 定义边
    workflow.set_entry_point("load_original")
    workflow.add_edge("load_original", "vector_retrieval")
    workflow.add_edge("vector_retrieval", "fetch_details")
    workflow.add_edge("fetch_details", "generate_guidance")
    workflow.add_edge("generate_guidance", END)
    
    return workflow.compile()