"""
错题录入Agent - Question Intake Agent (RPJ模块 - 学生实现版本)

基于 backend/modules/tony/agents/question_intake_agent.py 实现
专门支持语文、英语、道法三个学科的错题录入
"""

import logging
import json
import os
from typing import Dict, Any, Optional, List
from datetime import datetime
from langgraph.graph import StateGraph, END
from PIL import Image
import pytesseract

from backend.core.agents.state import QuestionIntakeState
from backend.core.agents.base_agent import BaseAgent
from backend.modules.rpj.config import settings

logger = logging.getLogger(__name__)


class RPJQuestionIntakeState(QuestionIntakeState):
    """
    RPJ错题录入专用状态
    针对语文、英语、道法学科优化
    """
    # 输入数据
    raw_input: str = ""  # 原始文本输入
    image_paths: List[str] = []  # 图片路径列表
    user_id: Optional[int] = None
    task_id: str = ""
    
    # 学科相关
    subject: str = "chinese"  # chinese, english, morality
    grade: str = ""  # 年级
    difficulty: str = "medium"  # 难度
    
    # 处理过程
    ocr_result: str = ""  # OCR识别结果
    combined_text: str = ""  # 合并后的文本
    structured_data: Dict[str, Any] = {}  # 结构化数据
    errors: List[str] = []  # 错误信息
    
    # 解析结果
    question_body: str = ""  # 题目正文
    student_answer: str = ""  # 学生答案
    correct_answer: str = ""  # 正确答案
    knowledge_points: List[str] = []  # 知识点
    chapter: str = ""  # 章节
    source: str = ""  # 来源
    
    # 输出结果
    question_id: Optional[int] = None  # 保存后的题目ID
    embedding: List[float] = []  # 向量嵌入
    error_analysis: str = ""  # 错因分析
    
    # 进度跟踪
    current_step: str = ""
    progress: float = 0.0
    parse_attempts: int = 0
    parse_success: bool = False


# ============ Prompt 模板 ============

QUESTION_INTAKE_PROMPT = """
请从以下题目文本中提取结构化信息，并按JSON格式返回。

题目文本：
{user_input_text}

请提取以下信息：
1. question_body: 题目正文
2. subject: 学科（语文、英语、道法）
3. grade: 年级（如：七年级、八年级、九年级）
4. difficulty: 难度（初级、中级、高级）
5. chapter: 章节或单元
6. knowledge_points: 知识点列表
7. student_answer: 学生答案（如果没有则留空）
8. correct_answer: 正确答案（如果没有则留空）
9. source: 来源（如：教材名称、试卷名称）

JSON格式示例：
{{
    "question_body": "题目完整内容",
    "subject": "语文",
    "grade": "八年级",
    "difficulty": "中级",
    "chapter": "第一单元 文言文阅读",
    "knowledge_points": ["文言文", "虚词用法", "句子翻译"],
    "student_answer": "学生的错误答案",
    "correct_answer": "正确答案",
    "source": "人教版八年级语文上册"
}}

请直接返回JSON，不要有其他内容。
"""

# 学科专用Prompt
CHINESE_QUESTION_PROMPT = """
你是一位语文老师，请分析以下语文题目：

题目文本：
{user_input_text}

作为语文老师，请特别关注：
1. 题型（选择题、填空题、阅读理解、文言文、作文等）
2. 文学知识点（修辞手法、文学常识、文言文知识等）
3. 语言表达（病句修改、句子排序、词语运用等）

请以JSON格式返回分析结果。
"""

ENGLISH_QUESTION_PROMPT = """
You are an English teacher, please analyze the following English question:

Question Text:
{user_input_text}

As an English teacher, please pay special attention to:
1. Question type (multiple choice, cloze test, reading comprehension, writing, etc.)
2. Grammar points (tenses, prepositions, sentence structures, etc.)
3. Vocabulary (key words, phrases, collocations)
4. Language skills (listening, reading, writing, translation)

Please return the analysis results in JSON format.
"""

MORALITY_QUESTION_PROMPT = """
你是一位道法老师，请分析以下道法题目：

题目文本：
{user_input_text}

作为道法老师，请特别关注：
1. 题目类型（选择题、简答题、论述题、案例分析题）
2. 政治概念（社会主义核心价值观、法律知识、道德规范等）
3. 答题要点（观点明确、论述充分、联系实际）

请以JSON格式返回分析结果。
"""

# 错因分析Prompt
ERROR_ANALYSIS_PROMPT = """
请分析以下错题的错因：

【题目】
{question_body}

【学生答案】
{student_answer}

【正确答案】
{correct_answer}

【知识点】
{knowledge_points}

请分析：
1. 错误类型（知识性错误、理解性错误、粗心错误等）
2. 具体错因
3. 改进建议
4. 相似题目练习建议

请用温暖鼓励的语气回复。
"""


# ============ Graph Nodes 实现 ============

async def rpj_ocr_process(state: RPJQuestionIntakeState) -> Dict[str, Any]:
    """
    OCR处理节点 - 处理图片输入
    """
    logger.info(f"[RPJ OCR Process] Task {state.get('task_id')}: 处理图片")
    
    image_paths = state.get("image_paths", [])
    
    if not image_paths:
        return {
            "ocr_result": "",
            "current_step": "rpj_ocr_process",
            "progress": 10.0,
        }
    
    try:
        ocr_texts = []
        
        for image_path in image_paths:
            if os.path.exists(image_path):
                # 使用pytesseract进行OCR识别
                image = Image.open(image_path)
                
                # 根据学科选择语言
                subject = state.get("subject", "chinese")
                if subject == "english":
                    lang = "eng"
                else:
                    lang = "chi_sim"  # 中文（简体）
                
                text = pytesseract.image_to_string(image, lang=lang)
                ocr_texts.append(text)
                
                logger.info(f"[RPJ OCR Process] 识别图片: {image_path}, 字符数: {len(text)}")
            else:
                logger.warning(f"[RPJ OCR Process] 图片不存在: {image_path}")
        
        ocr_result = "\n".join(ocr_texts)
        
        return {
            "ocr_result": ocr_result,
            "current_step": "rpj_ocr_process",
            "progress": 20.0,
        }
        
    except Exception as e:
        logger.error(f"[RPJ OCR Process] OCR错误: {e}")
        return {
            "errors": [f"OCR处理失败: {str(e)}"],
            "current_step": "rpj_ocr_process",
            "progress": 10.0,
        }


async def rpj_semantic_parse(state: RPJQuestionIntakeState) -> Dict[str, Any]:
    """
    语义解析节点 - 使用LLM提取结构化信息
    针对语文、英语、道法优化
    """
    logger.info(f"[RPJ Semantic Parse] Task {state.get('task_id')}: 解析题目")
    
    # 合并原始输入和OCR结果
    raw_input = state.get("raw_input", "")
    ocr_result = state.get("ocr_result", "")
    combined_text = f"{raw_input}\n{ocr_result}".strip()
    
    if not combined_text:
        return {
            "errors": ["输入内容为空"],
            "parse_success": False,
            "current_step": "rpj_semantic_parse",
            "progress": 30.0,
        }
    
    # 选择学科专用Prompt
    subject = state.get("subject", "chinese")
    if subject == "chinese":
        prompt_template = CHINESE_QUESTION_PROMPT
    elif subject == "english":
        prompt_template = ENGLISH_QUESTION_PROMPT
    elif subject == "morality":
        prompt_template = MORALITY_QUESTION_PROMPT
    else:
        prompt_template = QUESTION_INTAKE_PROMPT
    
    prompt = prompt_template.format(user_input_text=combined_text)
    
    try:
        # TODO: 调用LLM服务
        # 这里使用模拟数据，实际应调用真实的LLM API
        # from openai import AsyncOpenAI
        # client = AsyncOpenAI(api_key="your-api-key")
        # response = await client.chat.completions.create(...)
        
        # 模拟LLM响应
        if subject == "chinese":
            structured_data = {
                "question_body": combined_text[:200] + "..." if len(combined_text) > 200 else combined_text,
                "subject": "语文",
                "grade": "八年级",
                "difficulty": "中级",
                "chapter": "第一单元 文言文阅读",
                "knowledge_points": ["文言文", "实词解释", "句子翻译"],
                "student_answer": state.get("student_answer", ""),
                "correct_answer": state.get("correct_answer", ""),
                "source": "人教版八年级语文上册",
            }
        elif subject == "english":
            structured_data = {
                "question_body": combined_text[:200] + "..." if len(combined_text) > 200 else combined_text,
                "subject": "英语",
                "grade": "Grade 8",
                "difficulty": "Medium",
                "chapter": "Unit 1 How can we become good learners?",
                "knowledge_points": ["Vocabulary", "Grammar", "Reading Comprehension"],
                "student_answer": state.get("student_answer", ""),
                "correct_answer": state.get("correct_answer", ""),
                "source": "人教版八年级英语上册",
            }
        elif subject == "morality":
            structured_data = {
                "question_body": combined_text[:200] + "..." if len(combined_text) > 200 else combined_text,
                "subject": "道法",
                "grade": "八年级",
                "difficulty": "中级",
                "chapter": "第一单元 走进社会生活",
                "knowledge_points": ["社会规则", "社会责任", "社会主义核心价值观"],
                "student_answer": state.get("student_answer", ""),
                "correct_answer": state.get("correct_answer", ""),
                "source": "人教版八年级道法上册",
            }
        else:
            structured_data = {
                "question_body": combined_text,
                "subject": "其他",
                "grade": "",
                "difficulty": "medium",
                "chapter": "",
                "knowledge_points": [],
                "student_answer": state.get("student_answer", ""),
                "correct_answer": state.get("correct_answer", ""),
                "source": "",
            }
        
        # 从structured_data中提取关键字段
        knowledge_points = structured_data.get("knowledge_points", [])
        if isinstance(knowledge_points, str):
            knowledge_points = [kp.strip() for kp in knowledge_points.split(",") if kp.strip()]
        
        logger.info(f"[RPJ Semantic Parse] 解析成功，知识点: {knowledge_points}")
        
        return {
            "combined_text": combined_text,
            "structured_data": structured_data,
            "question_body": structured_data.get("question_body", ""),
            "subject": structured_data.get("subject", subject),
            "grade": structured_data.get("grade", ""),
            "difficulty": structured_data.get("difficulty", "medium"),
            "chapter": structured_data.get("chapter", ""),
            "knowledge_points": knowledge_points,
            "student_answer": structured_data.get("student_answer", ""),
            "correct_answer": structured_data.get("correct_answer", ""),
            "source": structured_data.get("source", ""),
            "parse_success": True,
            "parse_attempts": state.get("parse_attempts", 0) + 1,
            "current_step": "rpj_semantic_parse",
            "progress": 40.0,
        }
        
    except Exception as e:
        logger.error(f"[RPJ Semantic Parse] 解析错误: {e}")
        return {
            "errors": [f"题目解析失败: {str(e)}"],
            "parse_success": False,
            "parse_attempts": state.get("parse_attempts", 0) + 1,
            "current_step": "rpj_semantic_parse",
            "progress": 30.0,
        }


async def rpj_save_to_database(state: RPJQuestionIntakeState) -> Dict[str, Any]:
    """
    数据存储节点 - 保存到数据库
    针对语文、英语、道法优化
    """
    logger.info(f"[RPJ Save to Database] Task {state.get('task_id')}: 保存题目")
    
    user_id = state.get("user_id")
    question_body = state.get("question_body", "")
    subject = state.get("subject", "chinese")
    
    if not user_id:
        return {
            "errors": ["缺少用户ID"],
            "current_step": "rpj_save_to_database",
            "progress": 50.0,
        }
    
    if not question_body:
        return {
            "errors": ["题目内容为空"],
            "current_step": "rpj_save_to_database",
            "progress": 50.0,
        }
    
    try:
        # TODO: 实际保存到数据库
        # 这里使用文件系统模拟数据库
        
        # 创建保存目录
        save_dir = f"data/rpj/questions/{subject}/{user_id}"
        os.makedirs(save_dir, exist_ok=True)
        
        # 生成题目ID（使用时间戳模拟）
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        question_id = int(timestamp[-6:])  # 取后6位作为模拟ID
        
        # 准备保存数据
        question_data = {
            "question_id": question_id,
            "user_id": user_id,
            "task_id": state.get("task_id", ""),
            "created_at": timestamp,
            
            # 题目内容
            "question_body": question_body,
            "subject": subject,
            "grade": state.get("grade", ""),
            "difficulty": state.get("difficulty", "medium"),
            "chapter": state.get("chapter", ""),
            
            # 答案信息
            "student_answer": state.get("student_answer", ""),
            "correct_answer": state.get("correct_answer", ""),
            
            # 知识点和标签
            "knowledge_points": state.get("knowledge_points", []),
            "source": state.get("source", ""),
            
            # 图片信息
            "image_paths": state.get("image_paths", []),
            
            # 状态信息
            "parse_success": state.get("parse_success", False),
            "errors": state.get("errors", []),
        }
        
        # 保存到JSON文件
        filename = f"{save_dir}/question_{question_id}.json"
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(question_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"[RPJ Save to Database] 题目已保存，ID: {question_id}, 文件: {filename}")
        
        return {
            "question_id": question_id,
            "saved_file": filename,
            "current_step": "rpj_save_to_database",
            "progress": 60.0,
        }
        
    except Exception as e:
        logger.error(f"[RPJ Save to Database] 保存错误: {e}")
        return {
            "errors": [f"保存失败: {str(e)}"],
            "current_step": "rpj_save_to_database",
            "progress": 50.0,
        }


async def rpj_trigger_embedding(state: RPJQuestionIntakeState) -> Dict[str, Any]:
    """
    触发异步Embedding节点
    为题目生成向量表示
    """
    logger.info(f"[RPJ Trigger Embedding] Task {state.get('task_id')}: 生成向量")
    
    question_id = state.get("question_id")
    question_body = state.get("question_body", "")
    knowledge_points = state.get("knowledge_points", [])
    subject = state.get("subject", "chinese")
    
    if not question_id:
        return {
            "errors": ["缺少题目ID"],
            "current_step": "rpj_trigger_embedding",
            "progress": 70.0,
        }
    
    if not question_body:
        return {
            "errors": ["题目内容为空"],
            "current_step": "rpj_trigger_embedding",
            "progress": 70.0,
        }
    
    try:
        # TODO: 调用Embedding服务
        # 这里使用模拟向量
        
        # 构建文本用于Embedding
        embedding_text = question_body
        
        # 添加知识点信息增强语义
        if knowledge_points:
            embedding_text += f"\n知识点: {', '.join(knowledge_points)}"
        
        # 添加学科信息
        embedding_text += f"\n学科: {subject}"
        
        # 生成模拟向量（实际应使用BERT等模型）
        # 这里生成一个384维的随机向量（模拟sentence-transformers模型）
        import random
        embedding_dim = 384  # 常用的小型模型维度
        embedding = [random.uniform(-1, 1) for _ in range(embedding_dim)]
        
        # 归一化向量（模拟）
        import math
        norm = math.sqrt(sum(x * x for x in embedding))
        if norm > 0:
            embedding = [x / norm for x in embedding]
        
        # 保存向量到文件（模拟向量数据库）
        vector_dir = f"data/rpj/vectors/{subject}"
        os.makedirs(vector_dir, exist_ok=True)
        
        vector_data = {
            "question_id": question_id,
            "embedding": embedding,
            "metadata": {
                "subject": subject,
                "knowledge_points": knowledge_points,
                "difficulty": state.get("difficulty", ""),
                "grade": state.get("grade", ""),
            },
            "text": embedding_text[:500],  # 保存前500字符
            "created_at": datetime.now().isoformat(),
        }
        
        vector_file = f"{vector_dir}/vector_{question_id}.json"
        with open(vector_file, 'w', encoding='utf-8') as f:
            json.dump(vector_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"[RPJ Trigger Embedding] 向量已生成，维度: {len(embedding)}, 文件: {vector_file}")
        
        return {
            "embedding": embedding,
            "embedding_dim": len(embedding),
            "vector_file": vector_file,
            "current_step": "rpj_trigger_embedding",
            "progress": 80.0,
        }
        
    except Exception as e:
        logger.error(f"[RPJ Trigger Embedding] 向量生成错误: {e}")
        return {
            "errors": [f"向量生成失败: {str(e)}"],
            "current_step": "rpj_trigger_embedding",
            "progress": 70.0,
        }


async def rpj_analyze_error(state: RPJQuestionIntakeState) -> Dict[str, Any]:
    """
    错因分析节点
    针对语文、英语、道法学科特点进行分析
    """
    logger.info(f"[RPJ Analyze Error] Task {state.get('task_id')}: 分析错因")
    
    question_body = state.get("question_body", "")
    student_answer = state.get("student_answer", "")
    correct_answer = state.get("correct_answer", "")
    knowledge_points = state.get("knowledge_points", [])
    subject = state.get("subject", "chinese")
    
    if not question_body:
        return {
            "error_analysis": "题目内容为空，无法分析错因",
            "current_step": "rpj_analyze_error",
            "progress": 90.0,
        }
    
    # 如果没有学生答案或正确答案，返回通用分析
    if not student_answer and not correct_answer:
        error_analysis = "该题已记录，但缺少答案信息，无法进行详细的错因分析。"
        
        # 根据知识点给出通用建议
        if knowledge_points:
            kp_str = "、".join(knowledge_points[:3])
            error_analysis += f"\n\n涉及知识点：{kp_str}，建议重点复习这些内容。"
        
        return {
            "error_analysis": error_analysis,
            "current_step": "rpj_analyze_error",
            "progress": 90.0,
        }
    
    try:
        # TODO: 调用LLM进行错因分析
        # 这里使用规则分析
        
        # 构建分析文本
        prompt = ERROR_ANALYSIS_PROMPT.format(
            question_body=question_body[:500],
            student_answer=student_answer[:200],
            correct_answer=correct_answer[:200],
            knowledge_points="、".join(knowledge_points) if knowledge_points else "未指定"
        )
        
        # 模拟LLM响应
        error_analysis = f"""
【错题分析报告】

题目类型：{subject}题目
涉及知识点：{'、'.join(knowledge_points) if knowledge_points else '未指定'}

【错误分析】
"""
        
        # 根据学科生成不同的分析
        if subject == "chinese":
            error_analysis += """
1. 错误类型：理解性错误
2. 具体错因：对文言文实词/虚词的理解不够准确，或者对文章主旨把握有偏差。
3. 改进建议：
   - 加强对文言文常见字词的积累
   - 多读文言文原文，培养语感
   - 学习文言文翻译的基本方法
4. 练习建议：建议练习类似文言文阅读理解题目3-5道。
"""
        elif subject == "english":
            error_analysis += """
1. Error Type: Grammatical Error
2. Specific Cause: Misunderstanding of tense usage or sentence structure.
3. Improvement Suggestions:
   - Review basic grammar rules
   - Practice sentence construction
   - Read more English articles
4. Practice Recommendations: Suggest practicing 3-5 similar grammar questions.
"""
        elif subject == "morality":
            error_analysis += """
1. 错误类型：概念理解错误
2. 具体错因：对社会主义核心价值观等政治概念理解不深入，或者答题时没有联系实际。
3. 改进建议：
   - 熟记基本概念和原理
   - 关注时事政治，理论联系实际
   - 学习答题规范和格式
4. 练习建议：建议练习类似论述题2-3道。
"""
        else:
            error_analysis += """
1. 错误类型：知识掌握不牢固
2. 具体错因：相关知识点掌握不够熟练，需要加强复习。
3. 改进建议：
   - 整理错题本，定期复习
   - 针对薄弱知识点专项练习
   - 请教老师或同学，及时解决问题
4. 练习建议：建议练习类似题目3-5道。
"""
        
        error_analysis += "\n【老师寄语】\n不要灰心，错误是学习的好机会。通过分析错题，你会变得更加强大！加油！"
        
        logger.info(f"[RPJ Analyze Error] 错因分析完成，字符数: {len(error_analysis)}")
        
        return {
            "error_analysis": error_analysis,
            "current_step": "rpj_analyze_error",
            "progress": 90.0,
        }
        
    except Exception as e:
        logger.error(f"[RPJ Analyze Error] 分析错误: {e}")
        return {
            "error_analysis": f"错因分析失败: {str(e)}",
            "current_step": "rpj_analyze_error",
            "progress": 90.0,
        }


async def rpj_update_result(state: RPJQuestionIntakeState) -> Dict[str, Any]:
    """
    更新最终结果节点
    将错因分析结果保存到题目记录中
    """
    logger.info(f"[RPJ Update Result] Task {state.get('task_id')}: 更新结果")
    
    question_id = state.get("question_id")
    error_analysis = state.get("error_analysis", "")
    
    if not question_id:
        return {
            "current_step": "rpj_update_result",
            "progress": 100.0,
        }
    
    try:
        # 更新题目文件，添加错因分析
        saved_file = state.get("saved_file", "")
        if saved_file and os.path.exists(saved_file):
            with open(saved_file, 'r', encoding='utf-8') as f:
                question_data = json.load(f)
            
            # 添加错因分析和更新状态
            question_data["error_analysis"] = error_analysis
            question_data["updated_at"] = datetime.now().isoformat()
            question_data["status"] = "completed"
            
            with open(saved_file, 'w', encoding='utf-8') as f:
                json.dump(question_data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"[RPJ Update Result] 题目 {question_id} 已更新，添加错因分析")
        
        return {
            "status": "completed",
            "current_step": "rpj_update_result",
            "progress": 100.0,
        }
        
    except Exception as e:
        logger.error(f"[RPJ Update Result] 更新错误: {e}")
        return {
            "errors": [f"结果更新失败: {str(e)}"],
            "current_step": "rpj_update_result",
            "progress": 100.0,
        }


# ============ Graph Definition ============

def create_rpj_intake_graph():
    """
    创建RPJ错题录入Agent的工作流图
    
    流程:
    1. rpj_ocr_process: OCR处理图片
    2. rpj_semantic_parse: 语义解析提取结构化信息
    3. rpj_save_to_database: 保存到数据库
    4. rpj_trigger_embedding: 触发异步Embedding
    5. rpj_analyze_error: 错因分析
    6. rpj_update_result: 更新最终结果
    """
    workflow = StateGraph(RPJQuestionIntakeState)
    
    # 添加节点
    workflow.add_node("rpj_ocr_process", rpj_ocr_process)
    workflow.add_node("rpj_semantic_parse", rpj_semantic_parse)
    workflow.add_node("rpj_save_to_database", rpj_save_to_database)
    workflow.add_node("rpj_trigger_embedding", rpj_trigger_embedding)
    workflow.add_node("rpj_analyze_error", rpj_analyze_error)
    workflow.add_node("rpj_update_result", rpj_update_result)
    
    # 定义工作流
    workflow.set_entry_point("rpj_ocr_process")
    workflow.add_edge("rpj_ocr_process", "rpj_semantic_parse")
    workflow.add_edge("rpj_semantic_parse", "rpj_save_to_database")
    workflow.add_edge("rpj_save_to_database", "rpj_trigger_embedding")
    workflow.add_edge("rpj_trigger_embedding", "rpj_analyze_error")
    workflow.add_edge("rpj_analyze_error", "rpj_update_result")
    workflow.add_edge("rpj_update_result", END)
    
    return workflow.compile()


# 懒加载编译的图
_rpj_intake_graph = None


def get_rpj_intake_graph():
    """获取RPJ错题录入Agent图（懒加载）"""
    global _rpj_intake_graph
    if _rpj_intake_graph is None:
        _rpj_intake_graph = create_rpj_intake_graph()
    return _rpj_intake_graph


class QuestionIntakeAgent(BaseAgent):
    """
    RPJ错题录入Agent类
    
    专门支持语文、英语、道法三个学科的错题录入
    """
    
    def __init__(self):
        # 只支持语文、英语、道法
        supported_subjects = ["chinese", "english", "morality"]
        super().__init__(subjects=supported_subjects)
        self.graph = get_rpj_intake_graph()
        logger.info(f"[{settings.MODULE_NAME.upper()}] RPJ QuestionIntakeAgent 初始化完成，支持学科: {supported_subjects}")
    
    async def process(
        self,
        raw_input: str,
        user_id: int,
        task_id: str,
        image_paths: Optional[List[str]] = None,
        subject: str = "chinese",
        student_answer: Optional[str] = None,
        correct_answer: Optional[str] = None,
        difficulty: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        处理错题录入的主方法
        
        Args:
            raw_input: 原始输入文本
            user_id: 用户ID
            task_id: 任务ID
            image_paths: 图片路径列表 (可选)
            subject: 学科类型 (chinese, english, morality)
            student_answer: 学生答案 (可选)
            correct_answer: 正确答案 (可选)
            difficulty: 难度 (可选)
            
        Returns:
            处理结果字典
        """
        logger.info(f"[RPJ QuestionIntakeAgent] 开始处理任务 {task_id}, 学科: {subject}")
        
        # 验证学科
        if not self.validate_subject(subject):
            return {
                "task_id": task_id,
                "question_id": None,
                "success": False,
                "errors": [f"学科 '{subject}' 不支持，支持的学科: {self.subjects}"],
            }
        
        # 初始化状态
        initial_state: RPJQuestionIntakeState = {
            "raw_input": raw_input,
            "user_id": user_id,
            "task_id": task_id,
            "image_paths": image_paths or [],
            "subject": subject,
            "student_answer": student_answer or "",
            "correct_answer": correct_answer or "",
            "difficulty": difficulty or "medium",
            "errors": [],
            "parse_attempts": 0,
            "parse_success": False,
        }
        
        # 执行工作流
        final_state = None
        try:
            async for state in self.graph.astream(initial_state):
                for node_name, node_output in state.items():
                    if isinstance(node_output, dict):
                        # 合并状态
                        final_state = {**initial_state, **(final_state or {}), **node_output}
        except Exception as e:
            logger.error(f"[RPJ QuestionIntakeAgent] 工作流执行错误: {e}")
            return {
                "task_id": task_id,
                "question_id": None,
                "success": False,
                "errors": [f"处理失败: {str(e)}"],
            }
        
        # 构建返回结果
        if final_state:
            result = {
                "task_id": task_id,
                "question_id": final_state.get("question_id"),
                "success": final_state.get("parse_success", False),
                "question_body": final_state.get("question_body", ""),
                "subject": final_state.get("subject", subject),
                "grade": final_state.get("grade", ""),
                "difficulty": final_state.get("difficulty", ""),
                "knowledge_points": final_state.get("knowledge_points", []),
                "error_analysis": final_state.get("error_analysis", ""),
                "saved_file": final_state.get("saved_file", ""),
                "embedding_dim": final_state.get("embedding_dim", 0),
                "errors": final_state.get("errors", []),
                "progress": final_state.get("progress", 0),
                "current_step": final_state.get("current_step", ""),
            }
        else:
            result = {
                "task_id": task_id,
                "question_id": None,
                "success": False,
                "errors": ["处理失败，未生成有效结果"],
            }
        
        logger.info(f"[RPJ QuestionIntakeAgent] 任务 {task_id} 处理完成，成功: {result['success']}, 题目ID: {result['question_id']}")
        return result
    
    async def batch_intake(
        self,
        questions: List[Dict[str, Any]],
        user_id: int,
        task_id_prefix: str = "batch"
    ) -> Dict[str, Any]:
        """
        批量录入错题
        
        Args:
            questions: 错题列表，每个元素包含题目信息
            user_id: 用户ID
            task_id_prefix: 任务ID前缀
            
        Returns:
            批量处理结果
        """
        logger.info(f"[RPJ QuestionIntakeAgent] 开始批量录入，共 {len(questions)} 道题目")
        
        results = []
        successful_count = 0
        
        for i, question in enumerate(questions):
            # 为每道题创建独立任务ID
            sub_task_id = f"{task_id_prefix}_{i+1}"
            
            # 提取题目信息
            raw_input = question.get("raw_input", "")
            subject = question.get("subject", "chinese")
            image_paths = question.get("image_paths", [])
            student_answer = question.get("student_answer")
            correct_answer = question.get("correct_answer")
            difficulty = question.get("difficulty")
            
            # 处理单道题目
            result = await self.process(
                raw_input=raw_input,
                user_id=user_id,
                task_id=sub_task_id,
                image_paths=image_paths,
                subject=subject,
                student_answer=student_answer,
                correct_answer=correct_answer,
                difficulty=difficulty,
            )
            
            results.append(result)
            
            if result.get("success"):
                successful_count += 1
        
        return {
            "total_questions": len(questions),
            "successful_questions": successful_count,
            "failed_questions": len(questions) - successful_count,
            "results": results,
            "summary": f"批量录入完成，成功 {successful_count}/{len(questions)}",
        }
    
    async def search_similar_questions(
        self,
        question_text: str,
        subject: str = "chinese",
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """
        搜索相似题目
        
        Args:
            question_text: 题目文本
            subject: 学科
            top_k: 返回数量
            
        Returns:
            相似题目列表
        """
        logger.info(f"[RPJ QuestionIntakeAgent] 搜索相似题目，学科: {subject}, top_k: {top_k}")
        
        # TODO: 实现向量搜索
        # 这里使用文件系统模拟
        
        vector_dir = f"data/rpj/vectors/{subject}"
        if not os.path.exists(vector_dir):
            return []
        
        # 简单的文本相似度匹配（模拟）
        import re
        
        # 提取关键词
        words = re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z]+', question_text)
        keywords = list(set(words))[:5]  # 取前5个不同的词作为关键词
        
        similar_questions = []
        
        # 遍历向量文件
        for filename in os.listdir(vector_dir):
            if filename.endswith(".json"):
                filepath = os.path.join(vector_dir, filename)
                
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        vector_data = json.load(f)
                    
                    # 简单的关键词匹配
                    text = vector_data.get("text", "")
                    match_score = 0
                    
                    for keyword in keywords:
                        if keyword in text:
                            match_score += 1
                    
                    # 计算相似度（关键词匹配比例）
                    if keywords:
                        similarity = match_score / len(keywords)
                    else:
                        similarity = 0
                    
                    if similarity > 0.3:  # 相似度阈值
                        similar_questions.append({
                            "question_id": vector_data.get("question_id"),
                            "similarity": similarity,
                            "text": text[:100] + "..." if len(text) > 100 else text,
                            "metadata": vector_data.get("metadata", {}),
                        })
                        
                        if len(similar_questions) >= top_k:
                            break
                            
                except Exception as e:
                    logger.warning(f"读取向量文件失败: {filepath}, 错误: {e}")
        
        # 按相似度排序
        similar_questions.sort(key=lambda x: x["similarity"], reverse=True)
        
        logger.info(f"[RPJ QuestionIntakeAgent] 找到 {len(similar_questions)} 道相似题目")
        return similar_questions