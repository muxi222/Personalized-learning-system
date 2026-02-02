"""
RPJ - Gemini OCR Prompt Provider

专门针对语文、英语和道法的OCR提示词提供器
RPJ (Reading Comprehension & Answer Justification) 模块

功能:
- 提供语文、英语、道法的学科专属提示词
- 构建文科专项试卷分析prompt
- 配置OCR模型和生成参数
- 提供文科错题识别专用逻辑

注意: RPJ模块只支持语文、英语和道法三个学科
"""

import os
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# RPJ支持的学科
RPJ_SUBJECTS = {"chinese", "english", "morality"}


def get_subject_prompt(subject: str) -> str:
    """
    RPJ学科专属提示词
    
    针对语文、英语、道法提供专业化的分析指导
    """
    s = (subject or "").strip().lower()
    
    if s == "chinese":
        return """
你是一位资深的语文老师，专注于阅读理解、写作分析和语言表达的教学。

请特别注意:
- 字词书写是否规范、准确
- 语句是否通顺、表达是否清晰
- 文章结构是否合理、逻辑是否连贯
- 主题表达是否明确、中心思想是否突出
- 修辞手法运用是否恰当
- 文言文翻译是否准确、意境是否到位
- 阅读理解题的分析是否深入、全面
- 作文的结构、内容、语言是否优秀

语文专项关注点:
1. 语言表达: 词语搭配、句式运用、表达效果
2. 阅读理解: 文章主旨、细节理解、推理判断
3. 写作能力: 立意构思、结构布局、语言表达
4. 文学素养: 文学常识、文化内涵、审美鉴赏
"""
    
    elif s == "english":
        return """
你是一位资深的英语老师，专注于英语阅读理解、写作和语法教学。

请特别注意:
- 语法错误 (时态、主谓一致、冠词、介词等)
- 词汇使用是否恰当、拼写是否正确
- 句子结构是否完整、表达是否地道
- 阅读理解题的定位和理解是否准确
- 写作的逻辑性、连贯性和表达能力
- 听力理解的关键信息捕捉
- 英语文化的恰当运用

英语专项关注点:
1. 语法准确性: 时态、语态、句式结构
2. 词汇运用: 词义理解、固定搭配、词性转换
3. 阅读理解: 快速定位、细节理解、推理判断
4. 写作能力: 逻辑连贯、表达地道、内容丰富
5. 语言技能: 听说读写综合运用
"""
    
    elif s == "morality":
        return """
你是一位资深的道法老师，专注于道德与法治教育。

请特别注意:
- 道德观念是否正确、价值判断是否合理
- 法治观念是否清晰、法律知识是否准确
- 案例分析是否全面、深入
- 观点表达是否明确、论据是否充分
- 理论联系实际的能力
- 社会责任感和社会参与意识

道法专项关注点:
1. 道德认知: 道德规范、价值判断、道德实践
2. 法治素养: 法律知识、法治观念、法律运用
3. 案例分析: 问题识别、原因分析、解决方案
4. 社会参与: 社会责任、公民意识、社会实践
"""
    
    else:
        # RPJ模块只支持语文、英语、道法
        logger.warning(f"RPJ模块不支持学科: {subject}，将使用通用提示词")
        return "你是一位经验丰富的老师，请仔细分析题目内容。"


def is_intake_mode(trace_stage: str, user_hint: Optional[str]) -> bool:
    """
    判断是否为"错题识别/录入"场景
    
    RPJ模块的错题识别主要针对文科题目，需要特殊处理
    """
    stage = str(trace_stage or "").strip().lower()
    hint = user_hint or ""
    
    # RPJ特定的intake模式判断逻辑
    rpj_intake_stages = {
        "ocr_extract",           # OCR提取
        "ocr_agent",             # OCR代理
        "question_intake_ocr",   # 题目录入OCR
        "rpj_reading_intake",    # RPJ阅读题录入
        "rpj_writing_intake",    # RPJ写作题录入
        "rpj_moral_case_intake", # 道法案例录入
    }
    
    # RPJ特定的hint关键词
    rpj_intake_hints = {
        "错题识别", "题目录入", "试卷分析", 
        "阅读题", "写作题", "完形填空",
        "语文错题", "英语错题", "道法错题"
    }
    
    # RPJ模块的intake模式判断
    if stage in rpj_intake_stages:
        return True
    
    # 检查hint中是否包含RPJ特定的关键词
    for keyword in rpj_intake_hints:
        if keyword in hint:
            return True
    
    # 特殊处理：RPJ的写作题和阅读题通常需要intake模式
    if "写作" in hint or "作文" in hint or "阅读理解" in hint:
        return True
    
    return False


def _grade_info(grade: str) -> str:
    """年级信息格式化"""
    if not grade:
        return ""
    return f"学生年级: {grade}"


def _hint_info(user_hint: Optional[str]) -> str:
    """提示信息格式化"""
    if not user_hint:
        return ""
    return f"额外提示: {user_hint}"


def build_exam_analysis_prompt(*, subject: str, grade: str, user_hint: Optional[str], intake_mode: bool) -> str:
    """
    构建RPJ试卷分析prompt
    
    针对语文、英语、道法的特点提供专项分析
    """
    # 确保学科是RPJ支持的
    subject_lower = (subject or "").strip().lower()
    if subject_lower not in RPJ_SUBJECTS:
        logger.warning(f"RPJ模块不支持的学科: {subject}，将使用通用分析")
    
    subject_prompt = get_subject_prompt(subject)
    grade_info = _grade_info(grade)
    hint_info = _hint_info(user_hint)
    
    if intake_mode:
        # RPJ错题识别模式 - 针对文科题目优化
        return f"""
{subject_prompt}

{grade_info}
{hint_info}

这是"文科错题识别/录入"场景：一张图片可能包含多道语文、英语或道法题目。

## RPJ专项要求：
1. **学科特点**：请根据学科特点进行识别和分析
2. **题目类型**：特别关注阅读理解、写作、完形填空、简答题等文科题型
3. **文字处理**：注意中文的段落结构、英文的语法结构、道法的案例描述

## 输出要求（非常重要）：
1. 只输出JSON，不要输出markdown code block
2. questions数组必须包含图片中所有可识别题目
3. 对于文科题目，重点关注：
   - 语文：文章主旨、作者观点、修辞手法
   - 英语：语法结构、词汇搭配、阅读理解
   - 道法：道德判断、法律适用、案例分析
4. 识别规则优化：
   - 文科题目可能有大段文字，请确保question_text尽量完整
   - 对于写作题，需要识别作文标题、开头、主体、结尾
   - 对于阅读题，需要识别文章内容和问题
5. 选择题的答案可能是多个（如多选题），请用逗号分隔

## JSON格式（针对RPJ优化）：
{{
  "subject": "{subject_lower}",
  "grade": "{grade}",
  "analysis_mode": "rpj_intake",
  "questions": [
    {{
      "question_number": 1,
      "question_type": "选择题/填空题/解答题/阅读理解/写作/完形填空",
      "question_text": "完整的题目或文章内容（尽量完整，不超过800字）",
      "article_text": "如果是阅读理解，这里是完整的文章内容",
      "student_answer_raw": "学生的原始答案",
      "teacher_marked_answer": "老师批改的答案（如可见）",
      "teacher_marked_is_correct": true/false/null,
      "teacher_marked_mark": "tick/cross/none",
      "teacher_marked_color": "red/blue/black/unknown",
      "teacher_marked_evidence": "简短证据描述",
      "model_inferred_answer": "模型推断的参考答案",
      
      # RPJ专项字段
      "reading_comprehension_level": "easy/medium/hard",  # 阅读理解难度
      "writing_quality": "poor/fair/good/excellent",      # 写作质量
      "grammar_errors": ["错误1", "错误2"],               # 语法错误
      "vocabulary_level": "basic/intermediate/advanced",  # 词汇水平
      "moral_judgment": "correct/incorrect/unclear",      # 道德判断
      
      "student_answer": "清洗后的学生答案",
      "correct_answer": "正确答案",
      "is_correct": true/false/null,
      "score": 0,
      "max_score": 0
    }}
  ],
  "rpj_analysis": {{
    "total_reading_questions": 0,
    "total_writing_questions": 0,
    "average_reading_level": "medium",
    "key_vocabulary": ["词汇1", "词汇2"],
    "moral_themes": ["主题1", "主题2"]
  }}
}}
""".strip()
    
    # 完整试卷分析模式 - 针对RPJ优化
    return f"""
{subject_prompt}

{grade_info}
{hint_info}

请仔细分析这张文科试卷图片，完成以下专项任务:

## 1. OCR识别与提取
- 提取所有题目内容、文章和学生的解答
- 特别注意中文的段落结构、英文的语法结构
- 识别作文题目的完整内容

## 2. RPJ专项分析
### 语文专项:
- 分析阅读理解的主旨大意、细节信息
- 评估作文的立意、结构、语言表达
- 检查字词书写、标点使用是否规范
- 分析文言文翻译的准确性

### 英语专项:
- 分析语法错误的类型和频率
- 评估词汇运用的恰当性和丰富性
- 分析阅读理解的准确性和速度
- 评估写作的逻辑性和表达地道性

### 道法专项:
- 分析道德判断的正确性和深度
- 评估法律知识掌握的准确性
- 分析案例分析的全面性和深度
- 评估价值观念的合理性

## 3. 批改与反馈
- 判断每道题的对错并打分
- 对错误的题目提供具体的错误原因分析
- 给出针对性的改进建议

## 4. 学习建议
- 总结薄弱环节和需要加强的技能
- 提供专项练习建议
- 推荐适合的阅读材料和学习资源

请严格按照以下JSON格式输出:

```json
{{
    "subject": "{subject_lower}",
    "grade": "{grade}",
    "total_score": 实际得分,
    "max_score": 满分,
    "accuracy_rate": 正确率(0-1),
    "rpj_analysis": {{
        "reading_comprehension_score": 阅读理解得分,
        "writing_score": 写作得分,
        "grammar_score": 语法得分,
        "vocabulary_score": 词汇得分,
        "moral_cognition_score": 道德认知得分,
        "key_strengths": ["优势1", "优势2"],
        "weak_areas": ["薄弱点1", "薄弱点2"]
    }},
    "questions": [
        {{
            "question_number": 题号,
            "question_type": "选择题/填空题/解答题/阅读理解/写作/完形填空",
            "question_text": "完整题目内容",
            "article_text": "阅读理解的完整文章内容（如适用）",
            "student_answer_raw": "学生卷面原始答案",
            "teacher_marked_answer": "老师批改的答案",
            "teacher_marked_is_correct": true/false/null,
            "teacher_marked_mark": "tick/cross/none",
            "teacher_marked_color": "red/blue/black/unknown",
            "teacher_marked_evidence": "简短证据描述",
            "model_inferred_answer": "模型推断的参考答案",
            
            // RPJ专项分析字段
            "reading_comprehension_analysis": "阅读理解分析",
            "writing_quality_analysis": "写作质量分析",
            "grammar_error_analysis": "语法错误分析",
            "vocabulary_usage_analysis": "词汇运用分析",
            "moral_judgment_analysis": "道德判断分析",
            
            "student_answer": "清洗后的学生答案",
            "correct_answer": "正确答案",
            "score": 得分,
            "max_score": 该题满分,
            "is_correct": true/false,
            "error_analysis": "错误原因分析",
            "knowledge_points": ["知识点1", "知识点2"],
            "solution_steps": ["步骤1", "步骤2"],
            "difficulty": "easy/medium/hard",
            
            // 改进建议
            "improvement_suggestions": ["建议1", "建议2"],
            "recommended_practice": "推荐练习类型"
        }}
    ],
    "overall_analysis": "整体表现分析（特别是RPJ方面的表现）",
    "weak_points": ["薄弱知识点1", "薄弱知识点2"],
    "improvement_suggestions": ["建议1", "建议2"],
    "recommended_reading_materials": ["材料1", "材料2"],
    "learning_plan_suggestions": "学习计划建议"
}}