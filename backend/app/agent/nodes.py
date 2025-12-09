"""
Agent Graph Nodes
智能体图的各个节点实现
"""

import logging
import json
from typing import Dict, Any

from .graph import AgentState
from .prompts import (
    EXTRACT_INFO_PROMPT,
    GENERATE_SUGGESTIONS_PROMPT,
    get_error_analysis_prompt,
)

logger = logging.getLogger(__name__)


async def extract_info(state: AgentState) -> Dict[str, Any]:
    """
    节点1: 提取结构化信息
    使用LLM解析原始输入，提取题目、答案、知识点等
    """
    logger.info(f"[extract_info] Task {state.get('task_id')}: Starting extraction")

    from ..services.llm_service import get_llm_service

    llm = get_llm_service()

    # Prepare prompt
    raw_input = state.get("raw_input", "")
    prompt = EXTRACT_INFO_PROMPT.format(raw_input=raw_input)

    # Call LLM for structured extraction
    result = await llm.generate_json(
        prompt=prompt,
        temperature=0.3,  # Lower temperature for more consistent extraction
    )

    if not result:
        logger.error("[extract_info] Failed to extract structured data")
        return {
            "structured_data": {"content": raw_input},
            "errors": ["Failed to extract structured information from input"],
            "current_step": "extract_info",
            "progress": 10.0,
        }

    logger.info(f"[extract_info] Extracted: {list(result.keys())}")

    return {
        "structured_data": result,
        "subject": result.get("subject", "other"),
        "difficulty": result.get("difficulty", "medium"),
        "knowledge_points": result.get("knowledge_points", []),
        "current_step": "extract_info",
        "progress": 15.0,
    }


async def save_to_db(state: AgentState) -> Dict[str, Any]:
    """
    节点2: 保存到数据库
    将结构化数据保存到PostgreSQL
    """
    logger.info(f"[save_to_db] Task {state.get('task_id')}: Saving to database")

    from ..db.session import async_session_maker
    from ..crud.crud_question import create_question
    from ..schemas.question import QuestionCreate, SubjectType, DifficultyLevel

    structured_data = state.get("structured_data", {})
    user_id = state.get("user_id")

    if not user_id:
        logger.error("[save_to_db] No user_id provided")
        return {
            "errors": ["User ID is required"],
            "current_step": "save_to_db",
            "progress": 20.0,
        }

    try:
        # Map subject string to enum
        subject_map = {
            "math": SubjectType.MATH,
            "physics": SubjectType.PHYSICS,
            "chemistry": SubjectType.CHEMISTRY,
            "biology": SubjectType.BIOLOGY,
            "english": SubjectType.ENGLISH,
            "chinese": SubjectType.CHINESE,
        }
        subject = subject_map.get(
            structured_data.get("subject", "").lower(),
            SubjectType.OTHER
        )

        # Map difficulty
        difficulty_map = {
            "easy": DifficultyLevel.EASY,
            "medium": DifficultyLevel.MEDIUM,
            "hard": DifficultyLevel.HARD,
        }
        difficulty = difficulty_map.get(
            structured_data.get("difficulty", "").lower(),
            DifficultyLevel.MEDIUM
        )

        # Create question data
        question_data = QuestionCreate(
            title=structured_data.get("title"),
            content=structured_data.get("content", state.get("raw_input", "")),
            subject=subject,
            difficulty=difficulty,
            image_urls=state.get("image_urls", []),
            student_answer=structured_data.get("student_answer"),
            correct_answer=structured_data.get("correct_answer"),
            explanation=structured_data.get("explanation"),
            source=structured_data.get("source"),
            chapter=structured_data.get("chapter"),
            tags=structured_data.get("tags", []),
        )

        async with async_session_maker() as session:
            question = await create_question(session, question_data, user_id)
            await session.commit()
            question_id = question.id

        logger.info(f"[save_to_db] Created question with ID: {question_id}")

        return {
            "question_id": question_id,
            "current_step": "save_to_db",
            "progress": 30.0,
        }

    except Exception as e:
        logger.error(f"[save_to_db] Database error: {e}")
        return {
            "errors": [f"Database error: {str(e)}"],
            "current_step": "save_to_db",
            "progress": 20.0,
        }


async def generate_embedding(state: AgentState) -> Dict[str, Any]:
    """
    节点3: 生成向量表示
    使用Embedding模型生成题目的向量
    """
    logger.info(f"[generate_embedding] Task {state.get('task_id')}: Generating embedding")

    from ..services.embedding_service import get_embedding_service

    embedding_service = get_embedding_service()

    # Get content to embed
    structured_data = state.get("structured_data", {})
    content = structured_data.get("content", state.get("raw_input", ""))

    # Include knowledge points in embedding text
    knowledge_points = state.get("knowledge_points", [])
    if knowledge_points:
        content = f"{content}\n知识点: {', '.join(knowledge_points)}"

    # Generate embedding
    embedding = await embedding_service.embed_text(content)

    if not embedding:
        logger.error("[generate_embedding] Failed to generate embedding")
        return {
            "errors": ["Failed to generate embedding"],
            "current_step": "generate_embedding",
            "progress": 40.0,
        }

    logger.info(f"[generate_embedding] Generated embedding with dimension: {len(embedding)}")

    return {
        "embedding": embedding,
        "current_step": "generate_embedding",
        "progress": 45.0,
    }


async def save_to_vectorstore(state: AgentState) -> Dict[str, Any]:
    """
    节点4: 保存到向量数据库
    将embedding存入ChromaDB用于相似题目检索
    """
    logger.info(f"[save_to_vectorstore] Task {state.get('task_id')}: Saving to vector store")

    from ..services.vector_store_service import get_vector_store_service

    vector_store = get_vector_store_service()
    await vector_store.initialize()

    embedding = state.get("embedding")
    question_id = state.get("question_id")

    if not embedding or not question_id:
        logger.error("[save_to_vectorstore] Missing embedding or question_id")
        return {
            "errors": ["Missing embedding or question_id"],
            "current_step": "save_to_vectorstore",
            "progress": 50.0,
        }

    # Prepare metadata
    structured_data = state.get("structured_data", {})
    metadata = {
        "user_id": state.get("user_id"),
        "subject": state.get("subject", "other"),
        "difficulty": state.get("difficulty", "medium"),
        "knowledge_points": ",".join(state.get("knowledge_points", [])),
    }

    # Save to vector store
    success = await vector_store.add_embedding(
        doc_id=str(question_id),
        embedding=embedding,
        metadata=metadata,
        document=structured_data.get("content", ""),
    )

    if not success:
        logger.error("[save_to_vectorstore] Failed to save embedding")
        return {
            "errors": ["Failed to save to vector store"],
            "current_step": "save_to_vectorstore",
            "progress": 50.0,
        }

    logger.info(f"[save_to_vectorstore] Saved embedding for question: {question_id}")

    return {
        "current_step": "save_to_vectorstore",
        "progress": 55.0,
    }


async def analyze_error(state: AgentState) -> Dict[str, Any]:
    """
    节点5: 错因分析
    使用LLM分析学生的错误原因，给出针对性指导
    """
    logger.info(f"[analyze_error] Task {state.get('task_id')}: Analyzing error")

    from ..services.llm_service import get_llm_service

    llm = get_llm_service()

    # Get data for analysis
    structured_data = state.get("structured_data", {})
    subject = state.get("subject", "other")

    # Get subject-specific prompt
    prompt_template = get_error_analysis_prompt(subject)
    prompt = prompt_template.format(
        content=structured_data.get("content", state.get("raw_input", "")),
        subject=subject,
        student_answer=structured_data.get("student_answer", "未提供"),
        correct_answer=structured_data.get("correct_answer", "未提供"),
        knowledge_points=", ".join(state.get("knowledge_points", ["未知"])),
    )

    # Generate analysis
    error_analysis = await llm.generate(
        prompt=prompt,
        system_prompt="你是一位专业的教育专家，擅长分析学生的学习问题并给出针对性指导。",
        temperature=0.7,
        max_tokens=2000,
    )

    if not error_analysis:
        logger.error("[analyze_error] Failed to generate error analysis")
        return {
            "error_analysis": "分析生成失败，请稍后重试。",
            "errors": ["Failed to generate error analysis"],
            "current_step": "analyze_error",
            "progress": 70.0,
        }

    logger.info(f"[analyze_error] Generated analysis ({len(error_analysis)} chars)")

    return {
        "error_analysis": error_analysis,
        "current_step": "analyze_error",
        "progress": 75.0,
    }


async def generate_suggestions(state: AgentState) -> Dict[str, Any]:
    """
    节点6: 生成举一反三题目
    根据错题分析生成相关练习题
    """
    logger.info(f"[generate_suggestions] Task {state.get('task_id')}: Generating suggestions")

    from ..services.llm_service import get_llm_service

    llm = get_llm_service()

    # Prepare prompt
    structured_data = state.get("structured_data", {})
    prompt = GENERATE_SUGGESTIONS_PROMPT.format(
        subject=state.get("subject", "other"),
        content=structured_data.get("content", state.get("raw_input", "")),
        knowledge_points=", ".join(state.get("knowledge_points", [])),
        error_analysis=state.get("error_analysis", ""),
    )

    # Generate suggestions
    suggestions = await llm.generate_json(
        prompt=prompt,
        temperature=0.7,
        max_tokens=3000,
    )

    if not suggestions or not isinstance(suggestions, list):
        logger.error("[generate_suggestions] Failed to generate suggestions")
        return {
            "suggested_questions": [],
            "errors": ["Failed to generate practice questions"],
            "current_step": "generate_suggestions",
            "progress": 90.0,
        }

    logger.info(f"[generate_suggestions] Generated {len(suggestions)} practice questions")

    return {
        "suggested_questions": suggestions,
        "current_step": "generate_suggestions",
        "progress": 92.0,
    }


async def update_final_result(state: AgentState) -> Dict[str, Any]:
    """
    节点7: 更新最终结果
    将分析结果和推荐题目更新回数据库
    """
    logger.info(f"[update_final_result] Task {state.get('task_id')}: Updating final result")

    from ..db.session import async_session_maker
    from ..crud.crud_question import update_question_analysis
    from ..crud.crud_task import complete_task

    question_id = state.get("question_id")
    task_id = state.get("task_id")

    if not question_id:
        logger.error("[update_final_result] No question_id to update")
        return {
            "errors": ["No question_id to update"],
            "current_step": "update_final_result",
            "progress": 100.0,
        }

    try:
        async with async_session_maker() as session:
            # Update question with analysis results
            await update_question_analysis(
                db=session,
                question_id=question_id,
                error_analysis=state.get("error_analysis"),
                suggested_questions=state.get("suggested_questions", []),
                knowledge_points=state.get("knowledge_points", []),
            )

            # Mark task as completed
            if task_id:
                await complete_task(
                    db=session,
                    task_id=task_id,
                    question_id=question_id,
                    result={
                        "error_analysis_length": len(state.get("error_analysis", "")),
                        "suggestions_count": len(state.get("suggested_questions", [])),
                    },
                )

            await session.commit()

        logger.info(f"[update_final_result] Updated question {question_id}")

        return {
            "current_step": "update_final_result",
            "progress": 100.0,
        }

    except Exception as e:
        logger.error(f"[update_final_result] Database error: {e}")
        return {
            "errors": [f"Failed to update results: {str(e)}"],
            "current_step": "update_final_result",
            "progress": 100.0,
        }

