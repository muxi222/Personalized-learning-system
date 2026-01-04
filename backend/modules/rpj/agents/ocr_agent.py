"""
OCR识别Agent (RPJ模块 - 语文/英语/道法专用版本)

基于 backend/modules/tony/agents/ocr_agent.py 实现的OCR识别Agent
专门支持语文、英语、道法三个学科的试卷识别与分析
"""

import logging
import json
import os
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from langgraph.graph import StateGraph, END
from PIL import Image
try:
    import pytesseract  # type: ignore
except Exception:  # pragma: no cover
    pytesseract = None

from backend.core.agents.state import AgentState
from backend.core.agents.base_agent import BaseAgent
from backend.modules.rpj.config import settings

logger = logging.getLogger(__name__)

class RPJOCRAgentState(AgentState):
    """
    RPJ OCR Agent 专用状态
    针对语文、英语、道法学科优化
    """
    # 输入数据
    image_path: str
    image_urls: List[str] = []
    user_id: Optional[int] = None
    task_id: str
    subject: str = "chinese"  # chinese, english, morality

    # OCR 处理结果
    ocr_text: str = ""
    raw_text: str = ""  # 原始识别文本
    processed_text: str = ""  # 处理后文本
    questions: List[Dict[str, Any]] = []

    # 学科特定数据
    # 语文
    composition_score: float = 0.0  # 作文分数
    composition_feedback: str = ""  # 作文评语
    classical_chinese: List[Dict[str, Any]] = []  # 文言文题目

    # 英语
    listening_score: float = 0.0  # 听力分数
    writing_score: float = 0.0  # 写作分数
    vocabulary_errors: List[str] = []  # 词汇错误

    # 道法
    subjective_score: float = 0.0  # 主观题分数
    political_concepts: List[str] = []  # 政治概念掌握情况
    case_analysis: List[Dict[str, Any]] = []  # 案例分析题

    # 批改结果
    grading_result: Dict[str, Any] = {}
    total_score: float = 0.0
    total_possible: float = 100.0
    corrected_image_path: str = ""

    # 分析结果
    weak_points: List[str] = []
    improvement_suggestions: List[str] = []
    error_analysis: str = ""

    # 输出结果
    saved_question_ids: List[int] = []
    suggested_questions: List[Dict[str, Any]] = []
    practice_plan: Dict[str, Any] = {}  # 个性化学习计划

    # 进度跟踪
    current_step: str = ""
    progress: float = 0.0
    errors: List[str] = []

# ============ 语文专用处理函数 ============

def analyze_chinese_composition(text: str) -> Dict[str, Any]:
    """分析语文作文"""
    # 简单规则分析（实际应使用LLM或更复杂的分析）
    score = 0.0
    feedback = []

    # 检查字数
    word_count = len(text)
    if word_count < 400:
        score -= 10
        feedback.append("字数不足400字，请充实内容")
    elif word_count > 1000:
        score += 5
        feedback.append("字数充足，内容丰富")

    # 检查标点使用
    punctuation_count = sum(1 for char in text if char in '，。！？；："「」《》')
    if punctuation_count < word_count / 20:
        feedback.append("标点使用较少，请注意句子停顿")

    # 检查常见错误
    common_errors = {
        "的地得": ["的", "地", "得"],
        "错别字": ["象(像)", "做(作)", "那(哪)"],
        "标点": ["。。", "！！", "？？"]
    }

    for error_type, patterns in common_errors.items():
        for pattern in patterns:
            if pattern in text:
                feedback.append(f"注意{error_type}的使用：{pattern}")

    # 计算分数（40分制）
    base_score = 30.0
    if len(feedback) < 3:
        base_score += 5
    if word_count > 600:
        base_score += 5

    return {
        "score": min(base_score + score, 40.0),
        "total_score": 40.0,
        "feedback": feedback,
        "word_count": word_count,
        "structure_analysis": "建议：开头点题，中间展开，结尾升华",
        "common_errors": common_errors
    }

def extract_classical_chinese(text: str) -> List[Dict[str, Any]]:
    """提取文言文题目"""
    classical_keywords = ["曰", "之", "乎", "者", "也", "矣", "焉", "哉", "文言文", "古文"]
    lines = text.split('\n')

    classical_questions = []
    current_question = None

    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue

        # 检查是否是文言文题目
        is_classical = any(keyword in line for keyword in classical_keywords)

        if is_classical:
            if current_question:
                classical_questions.append(current_question)

            current_question = {
                "type": "classical_chinese",
                "content": line,
                "line_number": i + 1,
                "difficulty": "medium",
                "suggested_approach": "先理解关键字词，再通读全文"
            }
        elif current_question and line.startswith(("问题", "题目", "问：")):
            current_question["question"] = line
        elif current_question and line.startswith("答案"):
            current_question["answer"] = line.replace("答案：", "").replace("答案", "")

    if current_question:
        classical_questions.append(current_question)

    return classical_questions

# ============ 英语专用处理函数 ============

def analyze_english_writing(text: str) -> Dict[str, Any]:
    """分析英语作文"""
    score = 0.0
    feedback = []
    vocabulary_errors = []

    # 检查单词数量
    words = text.split()
    word_count = len(words)

    if word_count < 80:
        score -= 5
        feedback.append("单词数量不足，请充实内容")
    elif word_count > 150:
        score += 5
        feedback.append("内容丰富，单词数量充足")

    # 检查常见语法错误
    common_errors = [
        ("he do", "he does"),
        ("she go", "she goes"),
        ("I is", "I am"),
        ("they was", "they were"),
        ("very much good", "very good"),
        ("more better", "better"),
    ]

    for wrong, correct in common_errors:
        if wrong.lower() in text.lower():
            vocabulary_errors.append(f"{wrong} → {correct}")
            score -= 1

    # 检查连接词使用
    connectives = ["firstly", "secondly", "furthermore", "however", "therefore", "in conclusion"]
    used_connectives = [conn for conn in connectives if conn.lower() in text.lower()]

    if len(used_connectives) < 2:
        feedback.append("建议使用更多连接词使文章更连贯")
    else:
        score += 2
        feedback.append(f"使用了{len(used_connectives)}个连接词，文章结构清晰")

    # 检查句子结构
    sentences = text.replace('!', '.').replace('?', '.').split('.')
    sentence_count = len([s for s in sentences if len(s.strip()) > 5])

    if sentence_count < 5:
        feedback.append("句子数量较少，可以增加复杂句")

    # 计算分数（25分制）
    base_score = 15.0
    final_score = min(base_score + score, 25.0)

    return {
        "score": final_score,
        "total_score": 25.0,
        "feedback": feedback,
        "word_count": word_count,
        "sentence_count": sentence_count,
        "vocabulary_errors": vocabulary_errors,
        "used_connectives": used_connectives,
        "structure_suggestions": "建议使用三段式结构：Introduction-Body-Conclusion"
    }

def check_english_listening(answer_sheet: str, correct_answers: List[str]) -> Dict[str, Any]:
    """检查英语听力答案"""
    # 从答案卡提取答案
    answer_lines = answer_sheet.split('\n')
    student_answers = []

    for line in answer_lines:
        if line.strip() and any(c.isalpha() for c in line):
            # 提取可能的答案选项
            parts = line.split()
            for part in parts:
                if part.upper() in ['A', 'B', 'C', 'D']:
                    student_answers.append(part.upper())

    # 比对答案
    correct_count = 0
    errors = []

    for i, (student, correct) in enumerate(zip(student_answers, correct_answers)):
        if i < len(correct_answers):
            if student == correct:
                correct_count += 1
            else:
                errors.append(f"第{i+1}题：学生答案={student}，正确答案={correct}")

    total = len(correct_answers)
    score = (correct_count / total) * 30 if total > 0 else 0  # 听力30分

    return {
        "score": score,
        "total_score": 30.0,
        "correct_count": correct_count,
        "total_questions": total,
        "errors": errors,
        "accuracy": correct_count / total if total > 0 else 0
    }

# ============ 道法专用处理函数 ============

def analyze_morality_subjective(text: str) -> Dict[str, Any]:
    """分析道法主观题答案"""
    score = 0.0
    feedback = []
    political_concepts = []

    # 关键政治概念
    key_concepts = [
        "社会主义核心价值观", "中国特色社会主义", "党的领导",
        "人民民主", "依法治国", "和谐社会",
        "中国梦", "新发展理念", "共同富裕"
    ]

    # 检查是否包含关键概念
    for concept in key_concepts:
        if concept in text:
            political_concepts.append(concept)
            score += 2

    # 检查答案结构
    lines = text.split('\n')
    has_theory = any("理论" in line or "原理" in line for line in lines)
    has_practice = any("实践" in line or "实际" in line or "案例" in line for line in lines)
    has_summary = any("总之" in line or "综上所述" in line or "因此" in line for line in lines)

    if has_theory:
        score += 3
        feedback.append("答案包含理论阐述，很好")
    else:
        feedback.append("建议增加理论阐述")

    if has_practice:
        score += 3
        feedback.append("答案联系实际，有说服力")
    else:
        feedback.append("建议联系实际案例进行分析")

    if has_summary:
        score += 2
        feedback.append("有总结升华，结构完整")
    else:
        feedback.append("建议增加总结部分")

    # 检查答案长度
    word_count = len(text)
    if word_count < 100:
        score -= 5
        feedback.append("答案太简短，请详细阐述")
    elif word_count > 300:
        score += 3
        feedback.append("答案详细，论述充分")

    # 计算分数（40分制）
    base_score = 25.0
    final_score = min(base_score + score, 40.0)

    return {
        "score": final_score,
        "total_score": 40.0,
        "feedback": feedback,
        "political_concepts": political_concepts,
        "word_count": word_count,
        "structure_analysis": "建议采用理论+实践+总结的三段式结构",
        "key_concepts_found": len(political_concepts)
    }

def extract_case_analysis(text: str) -> List[Dict[str, Any]]:
    """提取案例分析题"""
    case_keywords = ["案例", "事例", "材料", "情境", "情景"]
    lines = text.split('\n')

    case_questions = []
    current_case = None
    collecting_content = False

    for i, line in enumerate(lines):
        line = line.strip()

        # 检查是否是案例开始
        if any(keyword in line for keyword in case_keywords):
            if current_case:
                case_questions.append(current_case)

            current_case = {
                "type": "case_analysis",
                "title": line,
                "content": [],
                "questions": [],
                "line_number": i + 1
            }
            collecting_content = True

        # 如果是案例内容
        elif collecting_content and current_case:
            if line.startswith(("问题", "题目", "问：")):
                current_case["questions"].append({
                    "question": line,
                    "answer": ""
                })
            elif line.startswith("答案"):
                if current_case["questions"]:
                    current_case["questions"][-1]["answer"] = line.replace("答案：", "").replace("答案", "")
            elif line:  # 非空行作为案例内容
                current_case["content"].append(line)

            # 遇到空行可能结束案例
            if not line and i > 0 and lines[i-1].strip():
                collecting_content = False

    if current_case:
        case_questions.append(current_case)

    return case_questions

# ============ Graph Nodes 实现 ============

async def rpj_ocr_extract(state: RPJOCRAgentState) -> Dict[str, Any]:
    """
    RPJ OCR提取节点 - 专门针对语文、英语、道法优化
    """
    logger.info(f"[RPJ OCR Extract] Task {state.get('task_id')}: 开始{state.get('subject')}试卷OCR识别")

    image_path = state.get("image_path", "")
    subject = state.get("subject", "chinese")

    if not image_path or not os.path.exists(image_path):
        return {
            "errors": ["图片文件不存在或路径错误"],
            "current_step": "rpj_ocr_extract",
            "progress": 10.0,
        }

    try:
        if pytesseract is None:
            # 学生模块环境可能未安装 pytesseract / tesseract：保持可运行，但返回明确错误信息
            return {
                "errors": ["RPJ OCR 依赖缺失：未安装 pytesseract/tesseract（学生TODO：安装依赖或改用在线OCR）"],
                "current_step": "rpj_ocr_extract",
                "progress": 10.0,
            }
        # 使用pytesseract进行OCR识别
        image = Image.open(image_path)

        # 根据学科选择语言包
        if subject == "chinese":
            lang = "chi_sim"  # 简体中文
        elif subject == "english":
            lang = "eng"  # 英语
        elif subject == "morality":
            lang = "chi_sim"  # 道法使用中文
        else:
            lang = "chi_sim+eng"  # 混合

        # 执行OCR识别
        raw_text = pytesseract.image_to_string(image, lang=lang)

        # 后处理：清理文本
        processed_text = raw_text.strip()
        processed_text = processed_text.replace('  ', ' ').replace('\n\n', '\n')

        logger.info(f"[RPJ OCR Extract] OCR识别完成，字符数: {len(processed_text)}")

        # 根据学科解析题目
        questions = []
        subject_specific_data = {}

        if subject == "chinese":
            # 查找作文部分
            if "作文" in processed_text or "写作" in processed_text:
                composition_start = processed_text.find("作文")
                if composition_start > -1:
                    composition_text = processed_text[composition_start:]
                    composition_result = analyze_chinese_composition(composition_text)
                    subject_specific_data.update({
                        "composition_score": composition_result["score"],
                        "composition_feedback": composition_result["feedback"],
                    })

            # 提取文言文题目
            classical_questions = extract_classical_chinese(processed_text)
            subject_specific_data["classical_chinese"] = classical_questions

            # 解析选择题和简答题
            questions = parse_chinese_questions(processed_text)

        elif subject == "english":
            # 查找写作部分
            if "Writing" in processed_text or "作文" in processed_text or "writing" in processed_text.lower():
                writing_section = extract_english_writing_section(processed_text)
                if writing_section:
                    writing_result = analyze_english_writing(writing_section)
                    subject_specific_data.update({
                        "writing_score": writing_result["score"],
                        "vocabulary_errors": writing_result["vocabulary_errors"],
                    })

            # 解析题目
            questions = parse_english_questions(processed_text)

        elif subject == "morality":
            # 查找主观题部分
            if "论述" in processed_text or "分析" in processed_text or "简答" in processed_text:
                subjective_section = extract_subjective_section(processed_text)
                if subjective_section:
                    subjective_result = analyze_morality_subjective(subjective_section)
                    subject_specific_data.update({
                        "subjective_score": subjective_result["score"],
                        "political_concepts": subjective_result["political_concepts"],
                    })

            # 提取案例分析题
            case_questions = extract_case_analysis(processed_text)
            subject_specific_data["case_analysis"] = case_questions

            # 解析题目
            questions = parse_morality_questions(processed_text)

        # 计算总分
        total_score = 0
        total_possible = 100

        for q in questions:
            total_score += q.get("score", 0)
            total_possible = max(total_possible, sum(q.get("total_score", 0) for q in questions))

        # 添加学科特定分数
        if subject == "chinese" and "composition_score" in subject_specific_data:
            total_score += subject_specific_data["composition_score"]
        elif subject == "english" and "writing_score" in subject_specific_data:
            total_score += subject_specific_data["writing_score"]
        elif subject == "morality" and "subjective_score" in subject_specific_data:
            total_score += subject_specific_data["subjective_score"]

        return {
            "raw_text": raw_text,
            "processed_text": processed_text,
            "questions": questions,
            "total_score": total_score,
            "total_possible": total_possible,
            **subject_specific_data,
            "current_step": "rpj_ocr_extract",
            "progress": 40.0,
        }

    except Exception as e:
        logger.error(f"[RPJ OCR Extract] 错误: {e}")
        return {
            "errors": [f"OCR识别失败: {str(e)}"],
            "current_step": "rpj_ocr_extract",
            "progress": 10.0,
        }

async def rpj_analyze_errors(state: RPJOCRAgentState) -> Dict[str, Any]:
    """
    RPJ 错误分析节点 - 针对语文、英语、道法优化
    """
    logger.info(f"[RPJ Analyze Errors] Task {state.get('task_id')}: 分析{state.get('subject')}错误模式")

    subject = state.get("subject", "chinese")
    questions = state.get("questions", [])

    # 学科特定的错误分析
    weak_points = []
    suggestions = []
    error_analysis = ""

    if subject == "chinese":
        # 语文错误分析
        weak_points = analyze_chinese_weak_points(questions, state)
        suggestions = generate_chinese_suggestions(weak_points, state)
        error_analysis = generate_chinese_error_analysis(state)

    elif subject == "english":
        # 英语错误分析
        weak_points = analyze_english_weak_points(questions, state)
        suggestions = generate_english_suggestions(weak_points, state)
        error_analysis = generate_english_error_analysis(state)

    elif subject == "morality":
        # 道法错误分析
        weak_points = analyze_morality_weak_points(questions, state)
        suggestions = generate_morality_suggestions(weak_points, state)
        error_analysis = generate_morality_error_analysis(state)

    return {
        "weak_points": weak_points,
        "improvement_suggestions": suggestions,
        "error_analysis": error_analysis,
        "current_step": "rpj_analyze_errors",
        "progress": 60.0,
    }

async def rpj_save_results(state: RPJOCRAgentState) -> Dict[str, Any]:
    """
    RPJ 保存结果节点 - 保存学科特定数据
    """
    logger.info(f"[RPJ Save Results] Task {state.get('task_id')}: 保存{state.get('subject')}分析结果")

    user_id = state.get("user_id")
    task_id = state.get("task_id", "")
    subject = state.get("subject", "chinese")

    if not user_id:
        return {
            "current_step": "rpj_save_results",
            "progress": 80.0,
        }

    try:
        # 创建保存目录
        save_dir = f"data/rpj/{subject}/{user_id}"
        os.makedirs(save_dir, exist_ok=True)

        # 生成文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{save_dir}/{task_id}_{timestamp}.json"

        # 准备保存数据
        save_data = {
            "user_id": user_id,
            "task_id": task_id,
            "subject": subject,
            "timestamp": timestamp,

            # 批改结果
            "total_score": state.get("total_score", 0),
            "total_possible": state.get("total_possible", 100),
            "questions": state.get("questions", []),

            # 学科特定数据
            "subject_specific": {},

            # 分析结果
            "weak_points": state.get("weak_points", []),
            "improvement_suggestions": state.get("improvement_suggestions", []),
            "error_analysis": state.get("error_analysis", ""),
        }

        # 添加学科特定数据
        if subject == "chinese":
            save_data["subject_specific"] = {
                "composition_score": state.get("composition_score", 0),
                "composition_feedback": state.get("composition_feedback", []),
                "classical_chinese": state.get("classical_chinese", []),
            }
        elif subject == "english":
            save_data["subject_specific"] = {
                "writing_score": state.get("writing_score", 0),
                "listening_score": state.get("listening_score", 0),
                "vocabulary_errors": state.get("vocabulary_errors", []),
            }
        elif subject == "morality":
            save_data["subject_specific"] = {
                "subjective_score": state.get("subjective_score", 0),
                "political_concepts": state.get("political_concepts", []),
                "case_analysis": state.get("case_analysis", []),
            }

        # 保存到文件
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(save_data, f, ensure_ascii=False, indent=2)

        logger.info(f"[RPJ Save Results] 结果已保存到 {filename}")

        # 模拟保存的题目ID
        saved_question_ids = list(range(1, len(state.get("questions", [])) + 1))

        return {
            "saved_question_ids": saved_question_ids,
            "saved_file": filename,
            "current_step": "rpj_save_results",
            "progress": 80.0,
        }

    except Exception as e:
        logger.error(f"[RPJ Save Results] 错误: {e}")
        return {
            "errors": [f"保存失败: {str(e)}"],
            "current_step": "rpj_save_results",
            "progress": 80.0,
        }

async def rpj_generate_practice(state: RPJOCRAgentState) -> Dict[str, Any]:
    """
    RPJ 生成练习节点 - 生成学科特定练习题
    """
    logger.info(f"[RPJ Generate Practice] Task {state.get('task_id')}: 生成{state.get('subject')}练习题")

    subject = state.get("subject", "chinese")
    weak_points = state.get("weak_points", [])
    user_id = state.get("user_id")

    if not weak_points:
        return {
            "suggested_questions": [],
            "practice_plan": {},
            "current_step": "rpj_generate_practice",
            "progress": 100.0,
        }

    try:
        suggested_questions = []
        practice_plan = {}

        if subject == "chinese":
            suggested_questions = generate_chinese_practice(weak_points)
            practice_plan = create_chinese_study_plan(weak_points, state)

        elif subject == "english":
            suggested_questions = generate_english_practice(weak_points, state)
            practice_plan = create_english_study_plan(weak_points, state)

        elif subject == "morality":
            suggested_questions = generate_morality_practice(weak_points, state)
            practice_plan = create_morality_study_plan(weak_points, state)

        return {
            "suggested_questions": suggested_questions[:5],  # 最多5题
            "practice_plan": practice_plan,
            "current_step": "rpj_generate_practice",
            "progress": 100.0,
        }

    except Exception as e:
        logger.error(f"[RPJ Generate Practice] 错误: {e}")
        return {
            "suggested_questions": [],
            "practice_plan": {},
            "current_step": "rpj_generate_practice",
            "progress": 100.0,
        }

# ============ 辅助函数 ============

def parse_chinese_questions(text: str) -> List[Dict[str, Any]]:
    """解析语文题目"""
    questions = []
    lines = text.split('\n')

    current_question = None
    question_number = 1

    for line in lines:
        line = line.strip()

        # 检测新题目
        if line and (line.startswith(tuple(str(i) for i in range(1, 20))) or
                     line.startswith(("一、", "二、", "三、", "（一）", "（二）"))):
            if current_question:
                questions.append(current_question)
                question_number += 1

            current_question = {
                "number": question_number,
                "type": "unknown",
                "content": line,
                "student_answer": "",
                "correct_answer": "",
                "score": 0,
                "total_score": 0,
                "knowledge_points": [],
            }

            # 判断题型
            if "选择" in line:
                current_question["type"] = "choice"
                current_question["total_score"] = 2  # 每题2分
            elif "填空" in line:
                current_question["type"] = "fill"
                current_question["total_score"] = 3  # 每题3分
            elif "简答" in line or "问答" in line:
                current_question["type"] = "short_answer"
                current_question["total_score"] = 5  # 每题5分
            elif "文言文" in line or "古诗" in line:
                current_question["type"] = "classical"
                current_question["total_score"] = 10  # 每题10分

        # 提取答案
        elif current_question:
            if "答案：" in line or "答：" in line:
                answer_text = line.replace("答案：", "").replace("答：", "").strip()
                if not current_question["student_answer"]:
                    current_question["student_answer"] = answer_text
                current_question["correct_answer"] = answer_text

                # 简单评分（实际需要更复杂的逻辑）
                if len(answer_text) > 3:
                    current_question["score"] = current_question["total_score"] * 0.8
                else:
                    current_question["score"] = current_question["total_score"] * 0.5

    # 添加最后一个题目
    if current_question:
        questions.append(current_question)

    return questions

def parse_english_questions(text: str) -> List[Dict[str, Any]]:
    """解析英语题目"""
    questions = []
    lines = text.split('\n')

    current_question = None
    question_number = 1

    for line in lines:
        line = line.strip()

        # 检测新题目
        if line and (line[0].isdigit() and line[1] in '.、)' or
                     line.startswith(("I.", "II.", "III.", "A.", "B.", "C."))):
            if current_question:
                questions.append(current_question)
                question_number += 1

            current_question = {
                "number": question_number,
                "type": "unknown",
                "content": line,
                "student_answer": "",
                "correct_answer": "",
                "score": 0,
                "total_score": 0,
                "knowledge_points": [],
            }

            # 判断题型
            if "Listening" in line or "听力" in line:
                current_question["type"] = "listening"
                current_question["total_score"] = 1  # 听力每题1分
            elif "Choice" in line or "选择" in line:
                current_question["type"] = "choice"
                current_question["total_score"] = 2  # 选择每题2分
            elif "Cloze" in line or "完形" in line:
                current_question["type"] = "cloze"
                current_question["total_score"] = 1.5  # 完形每题1.5分
            elif "Reading" in line or "阅读" in line:
                current_question["type"] = "reading"
                current_question["total_score"] = 2  # 阅读每题2分

        # 提取答案
        elif current_question:
            if "Answer:" in line or "答案：" in line or "A." in line[:3]:
                answer_text = line.replace("Answer:", "").replace("答案：", "").strip()
                if not current_question["student_answer"]:
                    current_question["student_answer"] = answer_text
                current_question["correct_answer"] = answer_text

    if current_question:
        questions.append(current_question)

    return questions

def parse_morality_questions(text: str) -> List[Dict[str, Any]]:
    """解析道法题目"""
    questions = []
    lines = text.split('\n')

    current_question = None
    question_number = 1

    for line in lines:
        line = line.strip()

        # 检测新题目
        if line and (line[0].isdigit() and line[1] in '.、)' or
                     "题" in line and any(num in line for num in ["一", "二", "三", "1", "2", "3"])):
            if current_question:
                questions.append(current_question)
                question_number += 1

            current_question = {
                "number": question_number,
                "type": "unknown",
                "content": line,
                "student_answer": "",
                "correct_answer": "",
                "score": 0,
                "total_score": 0,
                "knowledge_points": [],
            }

            # 判断题型
            if "选择" in line:
                current_question["type"] = "choice"
                current_question["total_score"] = 2  # 选择每题2分
            elif "简答" in line:
                current_question["type"] = "short_answer"
                current_question["total_score"] = 5  # 简答每题5分
            elif "论述" in line or "分析" in line:
                current_question["type"] = "essay"
                current_question["total_score"] = 10  # 论述每题10分
            elif "辨析" in line:
                current_question["type"] = "analysis"
                current_question["total_score"] = 8  # 辨析每题8分

        # 提取答案
        elif current_question:
            if "答案：" in line or "答：" in line:
                answer_text = line.replace("答案：", "").replace("答：", "").strip()
                if not current_question["student_answer"]:
                    current_question["student_answer"] = answer_text
                current_question["correct_answer"] = answer_text

    if current_question:
        questions.append(current_question)

    return questions

def analyze_chinese_weak_points(questions: List[Dict[str, Any]], state: Dict[str, Any]) -> List[str]:
    """分析语文薄弱点"""
    weak_points = []

    # 从错题中提取知识点
    wrong_questions = [q for q in questions if q.get("score", 0) < q.get("total_score", 1) * 0.6]

    for q in wrong_questions:
        if q.get("type") == "classical":
            weak_points.append("文言文理解")
        elif q.get("type") == "choice":
            weak_points.append("基础知识")
        elif q.get("type") == "short_answer":
            weak_points.append("简答题表达")

    # 从作文分析
    composition_score = state.get("composition_score", 0)
    if composition_score < 30:  # 作文40分制，30分以下需要改进
        weak_points.append("作文写作")

    # 去重
    return list(set(weak_points))

def generate_chinese_suggestions(weak_points: List[str], state: Dict[str, Any]) -> List[str]:
    """生成语文学习建议"""
    suggestions = []

    if "文言文理解" in weak_points:
        suggestions.extend([
            "每天背诵一篇文言文片段",
            "重点掌握常见文言实词和虚词",
            "多读文言文翻译，理解文意"
        ])

    if "作文写作" in weak_points:
        suggestions.extend([
            "每周写一篇作文，并请老师批改",
            "积累优秀作文素材和好词好句",
            "学习作文结构：开头-主体-结尾"
        ])

    if "基础知识" in weak_points:
        suggestions.extend([
            "每天复习10个生字词",
            "掌握常见病句类型",
            "背诵古诗文名句"
        ])

    if not suggestions:
        suggestions = [
            "保持每日阅读习惯",
            "定期复习错题本",
            "加强作文训练"
        ]

    return suggestions[:5]  # 最多5条建议

# ============ Graph Definition ============

def create_rpj_ocr_agent_graph():
    """
    创建RPJ OCR Agent工作流图
    """
    workflow = StateGraph(RPJOCRAgentState)

    # 添加节点
    workflow.add_node("rpj_ocr_extract", rpj_ocr_extract)
    workflow.add_node("rpj_analyze_errors", rpj_analyze_errors)
    workflow.add_node("rpj_save_results", rpj_save_results)
    workflow.add_node("rpj_generate_practice", rpj_generate_practice)

    # 定义工作流
    workflow.set_entry_point("rpj_ocr_extract")
    workflow.add_edge("rpj_ocr_extract", "rpj_analyze_errors")
    workflow.add_edge("rpj_analyze_errors", "rpj_save_results")
    workflow.add_edge("rpj_save_results", "rpj_generate_practice")
    workflow.add_edge("rpj_generate_practice", END)

    return workflow.compile()

# 懒加载编译的图
_rpj_ocr_graph = None

def get_rpj_ocr_graph():
    """获取RPJ OCR Agent图（懒加载）"""
    global _rpj_ocr_graph
    if _rpj_ocr_graph is None:
        _rpj_ocr_graph = create_rpj_ocr_agent_graph()
    return _rpj_ocr_graph

class OCRAgent(BaseAgent):
    """
    RPJ OCR识别Agent类

    专门支持语文、英语、道法三个学科
    """

    def __init__(self):
        # 只支持语文、英语、道法
        supported_subjects = ["chinese", "english", "morality"]
        super().__init__(subjects=supported_subjects)
        self.graph = get_rpj_ocr_graph()
        logger.info(f"[{settings.MODULE_NAME.upper()}] RPJ OCRAgent 初始化完成，支持学科: {supported_subjects}")

    async def process(
        self,
        image_path: str,
        user_id: int,
        task_id: str,
        subject: str = "chinese",
        **kwargs
    ) -> Dict[str, Any]:
        """
        处理试卷图片的主方法

        Args:
            image_path: 图片路径
            user_id: 用户ID
            task_id: 任务ID
            subject: 学科类型 (chinese, english, morality)

        Returns:
            处理结果字典
        """
        logger.info(f"[RPJ OCRAgent] 开始处理任务 {task_id}, 学科: {subject}")

        # 验证学科
        if not self.validate_subject(subject):
            return {
                "task_id": task_id,
                "success": False,
                "errors": [f"学科 '{subject}' 不支持，支持的学科: {self.subjects}"],
            }

        # 初始化状态
        initial_state: RPJOCRAgentState = {
            "image_path": image_path,
            "image_urls": [image_path],
            "user_id": user_id,
            "task_id": task_id,
            "subject": subject,
            "errors": [],
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
            logger.error(f"[RPJ OCRAgent] 工作流执行错误: {e}")
            return {
                "task_id": task_id,
                "success": False,
                "errors": [f"处理失败: {str(e)}"],
            }

        # 构建返回结果
        if final_state:
            result = {
                "task_id": task_id,
                "success": not bool(final_state.get("errors", [])),
                "total_score": final_state.get("total_score", 0),
                "total_possible": final_state.get("total_possible", 100),
                "questions": final_state.get("questions", []),
                "weak_points": final_state.get("weak_points", []),
                "suggestions": final_state.get("improvement_suggestions", []),
                "error_analysis": final_state.get("error_analysis", ""),
                "similar_questions": final_state.get("suggested_questions", []),
                "practice_plan": final_state.get("practice_plan", {}),
                "subject_specific": {},
                "errors": final_state.get("errors", []),
                "progress": final_state.get("progress", 0),
                "current_step": final_state.get("current_step", ""),
            }

            # 添加学科特定数据
            subject = final_state.get("subject", "chinese")
            if subject == "chinese":
                result["subject_specific"] = {
                    "composition_score": final_state.get("composition_score", 0),
                    "composition_feedback": final_state.get("composition_feedback", []),
                    "classical_chinese": final_state.get("classical_chinese", []),
                }
            elif subject == "english":
                result["subject_specific"] = {
                    "writing_score": final_state.get("writing_score", 0),
                    "listening_score": final_state.get("listening_score", 0),
                    "vocabulary_errors": final_state.get("vocabulary_errors", []),
                }
            elif subject == "morality":
                result["subject_specific"] = {
                    "subjective_score": final_state.get("subjective_score", 0),
                    "political_concepts": final_state.get("political_concepts", []),
                    "case_analysis": final_state.get("case_analysis", []),
                }
        else:
            result = {
                "task_id": task_id,
                "success": False,
                "errors": ["处理失败，未生成有效结果"],
            }

        logger.info(f"[RPJ OCRAgent] 任务 {task_id} 处理完成，成功: {result['success']}")
        return result

    async def get_subject_analysis(self, subject: str) -> Dict[str, Any]:
        """
        获取学科分析报告

        Args:
            subject: 学科类型

        Returns:
            学科分析报告
        """
        subject_analysis = {
            "chinese": {
                "name": "语文",
                "focus_areas": ["阅读理解", "作文写作", "文言文", "基础知识"],
                "exam_structure": "选择题(30%) + 阅读理解(30%) + 作文(40%)",
                "learning_tips": [
                    "每日阅读30分钟",
                    "每周背诵一篇古诗文",
                    "积累作文素材",
                    "多做真题训练"
                ]
            },
            "english": {
                "name": "英语",
                "focus_areas": ["听力", "阅读", "写作", "语法"],
                "exam_structure": "听力(30%) + 阅读(40%) + 写作(30%)",
                "learning_tips": [
                    "每天听英语30分钟",
                    "阅读英文文章",
                    "练习写作",
                    "背诵单词"
                ]
            },
            "morality": {
                "name": "道法",
                "focus_areas": ["政治概念", "案例分析", "时事政治", "法律知识"],
                "exam_structure": "选择题(30%) + 简答题(40%) + 论述题(30%)",
                "learning_tips": [
                    "关注时事新闻",
                    "理解政治概念",
                    "学习案例分析",
                    "掌握法律知识"
                ]
            }
        }

        return subject_analysis.get(subject, {})
