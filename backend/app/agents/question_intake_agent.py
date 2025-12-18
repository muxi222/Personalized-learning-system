"""
错题录入Agent - Question Intake Agent
根据设计文档4.1节实现

功能流程:
1. 接收用户输入 (文本/图片)
2. OCR处理 (如果是图片)
3. 语义解析 - 使用LLM提取结构化信息
4. 数据存储 - 保存到数据库
5. 触发异步Embedding
"""

import logging
import json
from typing import Dict, Any, Optional

from langgraph.graph import StateGraph, END

from .state import QuestionIntakeState
from .prompts import QUESTION_INTAKE_PROMPT

logger = logging.getLogger(__name__)


class QuestionIntakeAgent:
    """
    错题录入Agent
    负责接收、解析、存储错题
    """
    
    def __init__(self):
        self.graph = create_intake_graph()
    
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
    ) -> Dict[str, Any]:
        """
        处理错题录入
        
        Args:
            raw_input: 原始输入文本
            user_id: 用户ID
            task_id: 任务ID
            image_urls: 图片URL列表 (可选)
            student_answer: 学生答案 (可选)
            correct_answer: 正确答案 (可选)
            subject: 学科 (可选)
            difficulty: 难度 (可选)
            title: 题目标题 (可选)
        
        Returns:
            处理结果，包含question_id等
        """
        initial_state: QuestionIntakeState = {
            "raw_input": raw_input,
            "user_id": user_id,
            "task_id": task_id,
            "image_urls": image_urls or [],
            "errors": [],
            "parse_attempts": 0,
            "parse_success": False,
        }
        
        # 预设结构化数据
        structured_data = {}
        if student_answer:
            structured_data["student_answer"] = student_answer
        if correct_answer:
            structured_data["correct_answer"] = correct_answer
        if title:
            structured_data["title"] = title
            
        if structured_data:
            initial_state["structured_data"] = structured_data
        
        # 预设学科和难度
        if subject:
            initial_state["subject"] = subject
        if difficulty:
            initial_state["difficulty"] = difficulty
        
        # 运行图
        final_state = None
        async for state in self.graph.astream(initial_state):
            for node_name, node_output in state.items():
                if isinstance(node_output, dict):
                    final_state = {**initial_state, **(final_state or {}), **node_output}
        
        return {
            "task_id": task_id,
            "question_id": final_state.get("question_id") if final_state else None,
            "success": final_state.get("parse_success", False) if final_state else False,
            "errors": final_state.get("errors", []) if final_state else [],
        }


# ============ Graph Nodes ============

async def ocr_process(state: QuestionIntakeState) -> Dict[str, Any]:
    """
    OCR处理节点 - 处理图片输入
    """
    logger.info(f"[ocr_process] Task {state.get('task_id')}: Processing images")
    
    image_urls = state.get("image_urls", [])
    if not image_urls:
        return {
            "ocr_result": "",
            "current_step": "ocr_process",
            "progress": 5.0,
        }
    
    # TODO: 集成OCR服务 (Tesseract / 云服务)
    # 目前返回空，后续可扩展
    try:
        # 示例: 使用多模态模型直接理解图片
        # 或调用OCR API
        ocr_text = ""
        
        logger.info(f"[ocr_process] Processed {len(image_urls)} images")
        
        return {
            "ocr_result": ocr_text,
            "image_text": ocr_text,
            "current_step": "ocr_process",
            "progress": 10.0,
        }
    except Exception as e:
        logger.error(f"[ocr_process] OCR error: {e}")
        return {
            "errors": [f"OCR处理失败: {str(e)}"],
            "current_step": "ocr_process",
            "progress": 10.0,
        }


async def semantic_parse(state: QuestionIntakeState) -> Dict[str, Any]:
    """
    语义解析节点 - 使用LLM提取结构化信息
    根据设计文档4.1节的Prompt设计
    """
    logger.info(f"[semantic_parse] Task {state.get('task_id')}: Parsing input")
    
    from ..services.llm_service import get_llm_service
    
    llm = get_llm_service()
    
    # 合并原始输入和OCR结果
    raw_input = state.get("raw_input", "")
    ocr_text = state.get("ocr_result", "")
    combined_input = f"{raw_input}\n{ocr_text}".strip()
    
    if not combined_input:
        return {
            "errors": ["输入内容为空"],
            "parse_success": False,
            "current_step": "semantic_parse",
            "progress": 20.0,
        }
    
    # 使用设计文档中的Prompt
    prompt = QUESTION_INTAKE_PROMPT.format(user_input_text=combined_input)
    
    # 调用LLM进行结构化解析
    result = await llm.generate_json(
        prompt=prompt,
        temperature=0.3,  # 低温度确保一致性
    )
    
    if not result:
        logger.error("[semantic_parse] Failed to parse input")
        return {
            "structured_data": {"question_body": combined_input},
            "errors": ["无法解析题目结构，将使用原始文本"],
            "parse_success": False,
            "parse_attempts": state.get("parse_attempts", 0) + 1,
            "current_step": "semantic_parse",
            "progress": 20.0,
        }
    
    # 合并已有的structured_data (如student_answer)
    existing_data = state.get("structured_data", {})
    structured_data = {**result, **existing_data}
    
    logger.info(f"[semantic_parse] Parsed fields: {list(result.keys())}")
    
    return {
        "structured_data": structured_data,
        "subject": result.get("subject", "其他"),
        "grade": result.get("grade", ""),
        "difficulty": result.get("difficulty", "中级"),
        "chapter": result.get("chapter", ""),
        "knowledge_points": result.get("knowledge_points", []),
        "parse_success": True,
        "parse_attempts": state.get("parse_attempts", 0) + 1,
        "current_step": "semantic_parse",
        "progress": 30.0,
    }


async def save_to_database(state: QuestionIntakeState) -> Dict[str, Any]:
    """
    数据存储节点 - 保存到数据库
    """
    logger.info(f"[save_to_database] Task {state.get('task_id')}: Saving to DB")
    
    from ..db.session import async_session_maker
    from ..crud.crud_question import create_question
    from ..schemas.question import QuestionCreate, SubjectType, DifficultyLevel
    
    structured_data = state.get("structured_data", {})
    user_id = state.get("user_id")
    
    if not user_id:
        return {
            "errors": ["缺少用户ID"],
            "current_step": "save_to_database",
            "progress": 40.0,
        }
    
    try:
        # 映射学科
        subject_map = {
            "数学": SubjectType.MATH,
            "math": SubjectType.MATH,
            "物理": SubjectType.PHYSICS,
            "physics": SubjectType.PHYSICS,
            "化学": SubjectType.CHEMISTRY,
            "chemistry": SubjectType.CHEMISTRY,
            "生物": SubjectType.BIOLOGY,
            "biology": SubjectType.BIOLOGY,
            "英语": SubjectType.ENGLISH,
            "english": SubjectType.ENGLISH,
            "语文": SubjectType.CHINESE,
            "chinese": SubjectType.CHINESE,
        }
        subject = subject_map.get(
            structured_data.get("subject", "").lower(),
            SubjectType.OTHER
        )
        
        # 映射难度
        difficulty_map = {
            "初级": DifficultyLevel.EASY,
            "easy": DifficultyLevel.EASY,
            "中级": DifficultyLevel.MEDIUM,
            "medium": DifficultyLevel.MEDIUM,
            "高级": DifficultyLevel.HARD,
            "hard": DifficultyLevel.HARD,
        }
        difficulty = difficulty_map.get(
            structured_data.get("difficulty", "").lower(),
            DifficultyLevel.MEDIUM
        )
        
        # 创建题目
        question_data = QuestionCreate(
            content=structured_data.get("question_body", state.get("raw_input", "")),
            title=structured_data.get("chapter", ""),
            subject=subject,
            difficulty=difficulty,
            image_urls=state.get("image_urls", []),
            student_answer=structured_data.get("student_answer"),
            correct_answer=structured_data.get("correct_answer"),
            source=structured_data.get("source"),
            chapter=structured_data.get("chapter"),
            tags=structured_data.get("knowledge_points", []),
        )
        
        async with async_session_maker() as session:
            question = await create_question(session, question_data, user_id)
            await session.commit()
            question_id = question.id
        
        logger.info(f"[save_to_database] Created question ID: {question_id}")
        
        return {
            "question_id": question_id,
            "current_step": "save_to_database",
            "progress": 50.0,
        }
    
    except Exception as e:
        logger.error(f"[save_to_database] Error: {e}")
        return {
            "errors": [f"保存失败: {str(e)}"],
            "current_step": "save_to_database",
            "progress": 40.0,
        }


async def trigger_embedding(state: QuestionIntakeState) -> Dict[str, Any]:
    """
    触发异步Embedding节点
    根据设计文档4.1节: 将question_id和question_body发送至消息队列
    """
    logger.info(f"[trigger_embedding] Task {state.get('task_id')}: Triggering embedding")
    
    from ..services.embedding_service import get_embedding_service
    from ..services.vector_store_service import get_vector_store_service
    
    question_id = state.get("question_id")
    structured_data = state.get("structured_data", {})
    
    if not question_id:
        return {
            "errors": ["缺少question_id，无法生成embedding"],
            "current_step": "trigger_embedding",
            "progress": 60.0,
        }
    
    try:
        # 获取题目内容用于embedding
        question_body = structured_data.get("question_body", state.get("raw_input", ""))
        knowledge_points = state.get("knowledge_points", [])
        
        # 合并知识点以增强embedding
        if knowledge_points:
            question_body = f"{question_body}\n知识点: {', '.join(knowledge_points)}"
        
        # 根据学科选择Embedding模型 (设计文档4.1节)
        subject = state.get("subject", "")
        embedding_service = get_embedding_service()
        
        # 生成embedding
        embedding = await embedding_service.embed_text(question_body)
        
        if embedding:
            # 存入向量数据库
            vector_store = get_vector_store_service()
            await vector_store.initialize()
            
            metadata = {
                "user_id": state.get("user_id"),
                "subject": subject,
                "grade": state.get("grade", ""),
                "difficulty": state.get("difficulty", ""),
                "knowledge_points": ",".join(knowledge_points),
            }
            
            await vector_store.add_embedding(
                doc_id=str(question_id),
                embedding=embedding,
                metadata=metadata,
                document=question_body,
            )
            
            logger.info(f"[trigger_embedding] Embedding saved for question {question_id}")
        
        return {
            "embedding": embedding,
            "current_step": "trigger_embedding",
            "progress": 70.0,
        }
    
    except Exception as e:
        logger.error(f"[trigger_embedding] Error: {e}")
        return {
            "errors": [f"Embedding生成失败: {str(e)}"],
            "current_step": "trigger_embedding",
            "progress": 60.0,
        }


async def analyze_error(state: QuestionIntakeState) -> Dict[str, Any]:
    """
    错因分析节点
    """
    logger.info(f"[analyze_error] Task {state.get('task_id')}: Analyzing error")
    
    from ..services.llm_service import get_llm_service
    from .prompts import get_error_analysis_prompt, get_subject_name_cn
    
    llm = get_llm_service()
    structured_data = state.get("structured_data", {})
    subject = state.get("subject", "")
    
    # 获取学科专用Prompt
    prompt_template = get_error_analysis_prompt(subject)
    
    prompt = prompt_template.format(
        subject=get_subject_name_cn(subject),
        question_body=structured_data.get("question_body", state.get("raw_input", "")),
        student_answer=structured_data.get("student_answer", "未提供"),
        correct_answer=structured_data.get("correct_answer", "未提供"),
        knowledge_points=", ".join(state.get("knowledge_points", ["未知"])),
        grade=state.get("grade", "未知"),
        chapter=state.get("chapter", "未知"),
    )
    
    error_analysis = await llm.generate(
        prompt=prompt,
        system_prompt="你是学习小书童，一位温暖有耐心的老师。",
        temperature=0.7,
        max_tokens=2000,
    )
    
    if not error_analysis:
        return {
            "error_analysis": "分析生成失败，请稍后重试。",
            "current_step": "analyze_error",
            "progress": 85.0,
        }
    
    return {
        "error_analysis": error_analysis,
        "current_step": "analyze_error",
        "progress": 85.0,
    }


async def update_result(state: QuestionIntakeState) -> Dict[str, Any]:
    """
    更新最终结果节点
    """
    logger.info(f"[update_result] Task {state.get('task_id')}: Updating result")
    
    from ..db.session import async_session_maker
    from ..crud.crud_question import update_question_analysis
    from ..crud.crud_task import complete_task
    
    question_id = state.get("question_id")
    task_id = state.get("task_id")
    
    if question_id:
        try:
            async with async_session_maker() as session:
                await update_question_analysis(
                    db=session,
                    question_id=question_id,
                    error_analysis=state.get("error_analysis"),
                    knowledge_points=state.get("knowledge_points", []),
                )
                
                if task_id:
                    await complete_task(session, task_id, question_id)
                
                await session.commit()
            
            logger.info(f"[update_result] Updated question {question_id}")
        except Exception as e:
            logger.error(f"[update_result] Error: {e}")
    
    return {
        "current_step": "update_result",
        "progress": 100.0,
    }


# ============ Graph Definition ============

def create_intake_graph():
    """
    创建错题录入Agent的工作流图
    
    流程:
    1. ocr_process: OCR处理图片
    2. semantic_parse: 语义解析提取结构化信息
    3. save_to_database: 保存到数据库
    4. trigger_embedding: 触发异步Embedding
    5. analyze_error: 错因分析
    6. update_result: 更新最终结果
    """
    workflow = StateGraph(QuestionIntakeState)
    
    # 添加节点
    workflow.add_node("ocr_process", ocr_process)
    workflow.add_node("semantic_parse", semantic_parse)
    workflow.add_node("save_to_database", save_to_database)
    workflow.add_node("trigger_embedding", trigger_embedding)
    workflow.add_node("analyze_error", analyze_error)
    workflow.add_node("update_result", update_result)
    
    # 定义边
    workflow.set_entry_point("ocr_process")
    workflow.add_edge("ocr_process", "semantic_parse")
    workflow.add_edge("semantic_parse", "save_to_database")
    workflow.add_edge("save_to_database", "trigger_embedding")
    workflow.add_edge("trigger_embedding", "analyze_error")
    workflow.add_edge("analyze_error", "update_result")
    workflow.add_edge("update_result", END)
    
    return workflow.compile()

