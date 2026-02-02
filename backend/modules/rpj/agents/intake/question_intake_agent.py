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

from backend.core.agents.state import QuestionIntakeState
from backend.core.agents.prompts import QUESTION_INTAKE_PROMPT
from backend.core.agents.base_agent import BaseAgent
from backend.modules.rpj.config import settings

logger = logging.getLogger(__name__)

class QuestionIntakeAgent(BaseAgent):
    """
    错题录入Agent
    负责接收、解析、存储错题
    """

    def __init__(self):
        super().__init__(subjects=settings.SUBJECTS)
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
        # Validate subject if provided
        if subject and not self.validate_subject(subject):
            logger.error(f"Subject '{subject}' not supported by RPJ module")
            return {
                "task_id": task_id,
                "question_id": None,
                "success": False,
                "errors": [f"Subject '{subject}' not supported by RPJ module. Supported: {settings.SUBJECTS}"],
            }

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

    from backend.core.services.llm_service import get_llm_service

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

    # 根据学科调整Prompt
    subject = state.get("subject", "")
    
    # 基础Prompt（可针对文科特点进行调整）
    if subject in ["语文", "chinese"]:
        prompt = f"""
        作为语文学习助手，请从以下输入中提取结构化信息：

        输入内容：{combined_input}

        请提取以下信息：
        1. 题目主体 (question_body): 完整题目内容
        2. 学生答案 (student_answer): 学生的回答内容（如果有）
        3. 正确答案 (correct_answer): 正确答案或参考答案（如果有）
        4. 题目类型 (question_type): 选择题/填空题/阅读理解/作文/文言文翻译/诗词鉴赏等
        5. 学科 (subject): 语文
        6. 难度 (difficulty): 初级/中级/高级
        7. 年级 (grade): 如：初一/初二/初三/高一/高二/高三
        8. 章节 (chapter): 所属章节或单元
        9. 知识点 (knowledge_points): 如：[古诗词默写, 文言文实词, 现代文阅读技巧]
        10. 错因类型 (error_type): 如：字词错误/理解偏差/答题不规范

        请以JSON格式返回。
        """
    elif subject in ["英语", "english"]:
        prompt = f"""
        As an English learning assistant, please extract structured information from the following input:

        Input content: {combined_input}

        Please extract the following information:
        1. question_body: Complete question content
        2. student_answer: Student's answer (if any)
        3. correct_answer: Correct answer or reference answer (if any)
        4. question_type: Multiple choice/Blank filling/Reading comprehension/Writing/Translation, etc.
        5. subject: English
        6. difficulty: Easy/Medium/Hard
        7. grade: e.g., Grade 7/Grade 8/Grade 9/Grade 10/Grade 11/Grade 12
        8. chapter: Relevant chapter or unit
        9. knowledge_points: e.g., [Grammar tense, Vocabulary usage, Reading skills]
        10. error_type: e.g., Grammatical error/Vocabulary misuse/Comprehension mistake

        Please return in JSON format.
        """
    elif subject in ["道法", "moral_education"]:
        prompt = f"""
        作为道德与法治学习助手，请从以下输入中提取结构化信息：

        输入内容：{combined_input}

        请提取以下信息：
        1. 题目主体 (question_body): 完整题目内容
        2. 学生答案 (student_answer): 学生的回答内容（如果有）
        3. 正确答案 (correct_answer): 正确答案或参考答案（如果有）
        4. 题目类型 (question_type): 选择题/判断题/简答题/材料分析题/案例分析题等
        5. 学科 (subject): 道法
        6. 难度 (difficulty): 初级/中级/高级
        7. 年级 (grade): 如：初一/初二/初三/高一/高二/高三
        8. 章节 (chapter): 所属章节或单元
        9. 知识点 (knowledge_points): 如：[法律常识, 道德规范, 社会公德]
        10. 核心素养 (core_competencies): 如：[法治意识, 道德认知, 社会责任]

        请以JSON格式返回。
        """
    else:
        # 使用通用的QUESTION_INTAKE_PROMPT
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
        "subject": result.get("subject", "语文"),
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

    from backend.core.db.session import async_session_maker
    from backend.core.crud.crud_question import create_question
    from backend.core.schemas.question import QuestionCreate, SubjectType, DifficultyLevel

    structured_data = state.get("structured_data", {})
    user_id = state.get("user_id")

    if not user_id:
        return {
            "errors": ["缺少用户ID"],
            "current_step": "save_to_database",
            "progress": 40.0,
        }

    try:
        # 映射学科 - 支持语文、英语、道法
        subject_map = {
            "语文": SubjectType.CHINESE,
            "chinese": SubjectType.CHINESE,
            "英语": SubjectType.ENGLISH,
            "english": SubjectType.ENGLISH,
            "道法": SubjectType.MORAL_EDUCATION,
            "moral_education": SubjectType.MORAL_EDUCATION,
            "道德与法治": SubjectType.MORAL_EDUCATION,
            "历史": SubjectType.HISTORY,
            "history": SubjectType.HISTORY,
            "地理": SubjectType.GEOGRAPHY,
            "geography": SubjectType.GEOGRAPHY,
            "其他": SubjectType.OTHER,
            "other": SubjectType.OTHER,
        }
        subject = subject_map.get(
            structured_data.get("subject", "").lower(),
            SubjectType.OTHER
        )

        # 映射难度
        difficulty_map = {
            "初级": DifficultyLevel.EASY,
            "easy": DifficultyLevel.EASY,
            "低级": DifficultyLevel.EASY,
            "低": DifficultyLevel.EASY,
            "中级": DifficultyLevel.MEDIUM,
            "medium": DifficultyLevel.MEDIUM,
            "中": DifficultyLevel.MEDIUM,
            "高级": DifficultyLevel.HARD,
            "hard": DifficultyLevel.HARD,
            "高": DifficultyLevel.HARD,
        }
        difficulty = difficulty_map.get(
            structured_data.get("difficulty", "").lower(),
            DifficultyLevel.MEDIUM
        )

        # 创建题目
        question_data = QuestionCreate(
            content=structured_data.get("question_body", state.get("raw_input", "")),
            title=structured_data.get("title") or structured_data.get("chapter", ""),
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

    from backend.core.services.embedding_service import get_embedding_service
    from backend.core.services.vector_store_service import get_vector_store_service

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

        # 对于文科题目，可以添加学科特定的文本增强
        subject = state.get("subject", "")
        if subject in ["语文", "chinese"]:
            # 语文题目可以添加文学体裁、作者等信息
            question_body = f"{question_body}\n学科: 语文"
            if knowledge_points:
                question_body = f"{question_body}\n知识点: {', '.join(knowledge_points)}"
        elif subject in ["英语", "english"]:
            # 英语题目可以添加语言技能等信息
            question_body = f"{question_body}\n学科: 英语"
            if knowledge_points:
                question_body = f"{question_body}\nSkills: {', '.join(knowledge_points)}"
        elif subject in ["道法", "moral_education"]:
            # 道法题目可以添加核心素养等信息
            question_body = f"{question_body}\n学科: 道德与法治"
            core_competencies = structured_data.get("core_competencies", [])
            if core_competencies:
                question_body = f"{question_body}\n核心素养: {', '.join(core_competencies)}"

        # 根据学科选择Embedding模型 (设计文档4.1节)
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
    错因分析节点 - 针对文科特点优化
    """
    logger.info(f"[analyze_error] Task {state.get('task_id')}: Analyzing error")

    from backend.core.services.llm_service import get_llm_service
    from backend.core.agents.prompts import get_error_analysis_prompt, get_subject_name_cn

    llm = get_llm_service()
    structured_data = state.get("structured_data", {})
    subject = state.get("subject", "")

    # 获取学科专用Prompt
    prompt_template = get_error_analysis_prompt(subject)

    # 根据学科调整分析角度
    if subject in ["语文", "chinese"]:
        # 语文错因分析：字词、理解、表达、格式
        prompt = f"""
        请作为语文老师，分析以下错题的错因：

        题目：{structured_data.get("question_body", state.get("raw_input", ""))}
        学生答案：{structured_data.get("student_answer", "未提供")}
        正确答案：{structured_data.get("correct_answer", "未提供")}
        涉及知识点：{', '.join(state.get("knowledge_points", ["未知"]))}
        年级：{state.get("grade", "未知")}
        章节：{state.get("chapter", "未知")}

        请从以下角度分析：
        1. 字词错误：错别字、词语使用不当
        2. 理解偏差：对题目、文章或文言文理解有误
        3. 表达问题：语言表达不准确、不流畅
        4. 格式问题：答题格式不规范
        5. 文化常识：文学常识、文化背景知识缺乏
        6. 建议：如何改进学习，提高语文能力

        请用温暖、鼓励的语气进行错因分析。
        """
    elif subject in ["英语", "english"]:
        # 英语错因分析：语法、词汇、理解、表达
        prompt = f"""
        Please act as an English teacher and analyze the error causes for the following wrong question:

        Question: {structured_data.get("question_body", state.get("raw_input", ""))}
        Student's answer: {structured_data.get("student_answer", "Not provided")}
        Correct answer: {structured_data.get("correct_answer", "Not provided")}
        Related knowledge points: {', '.join(state.get("knowledge_points", ["Unknown"]))}
        Grade: {state.get("grade", "Unknown")}
        Chapter: {state.get("chapter", "Unknown")}

        Please analyze from the following perspectives:
        1. Grammar errors: Tense, sentence structure, grammar rules
        2. Vocabulary issues: Wrong word choice, spelling mistakes
        3. Comprehension problems: Misunderstanding of the question or reading material
        4. Expression issues: Inaccurate or unclear expression
        5. Learning suggestions: How to improve English learning

        Please use a warm and encouraging tone.
        """
    elif subject in ["道法", "moral_education"]:
        # 道法错因分析：法律、道德、价值观、案例分析
        prompt = f"""
        请作为道德与法治老师，分析以下错题的错因：

        题目：{structured_data.get("question_body", state.get("raw_input", ""))}
        学生答案：{structured_data.get("student_answer", "未提供")}
        正确答案：{structured_data.get("correct_answer", "未提供")}
        涉及知识点：{', '.join(state.get("knowledge_points", ["未知"]))}
        年级：{state.get("grade", "未知")}
        章节：{state.get("chapter", "未知")}

        请从以下角度分析：
        1. 法律常识：对法律条文、法律概念理解不清
        2. 道德判断：道德认知、价值判断存在偏差
        3. 案例分析：分析案例、解决问题的能力不足
        4. 社会责任：对社会责任、公民意识理解不足
        5. 建议：如何提高法治意识和道德素养

        请用温暖、鼓励的语气进行错因分析。
        """
    else:
        # 使用通用Prompt
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

    from backend.core.db.session import async_session_maker
    from backend.core.crud.crud_question import update_question_analysis
    from backend.core.crud.crud_task import complete_task

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