"""
Wzy - Gemini OCR Prompt Provider

本模块用于承载“可按模块/学科拆分”的内容：
- 学科提示词（subject prompt）
- 试卷分析/错题录入 prompt 构建
- OCR 模型选择、temperature/max_tokens 等可配置项
- LLM 调试日志开关与截断长度配置

核心公共逻辑仍在 `backend/core/services/gemini_ocr_service.py`：
- HTTP 调用、重试、JSON 解析、结果结构封装等
"""

import os
from typing import Optional, Dict, Any


def get_subject_prompt(subject: str) -> str:
    """按学科返回分析提示（文案迁移自 core gemini_ocr_service）。"""
    s = (subject or "").strip().lower()
    if s == "math":
        return """
你是一位资深的数学老师。请特别注意:
- 计算过程的每一步是否正确
- 公式运用是否恰当
- 逻辑推理是否严密
- 几何证明步骤是否完整
"""
    if s == "physics":
        return """
你是一位资深的物理老师。请特别注意:
- 物理概念理解是否准确
- 公式选择是否正确
- 单位换算是否正确
- 物理量的方向和正负号
"""


def is_intake_mode(trace_stage: str, user_hint: Optional[str]) -> bool:
    """
    判断是否为“错题识别/录入”场景（迁移自 core gemini_ocr_service）。
    该场景需要更短输出以降低 finish_reason=length 风险。
    """
    stage = str(trace_stage or "").strip().lower()
    hint = user_hint or ""
    return stage in ("ocr_extract", "ocr_agent", "question_intake_ocr") or ("错题识别" in hint)


def _grade_info(grade: str) -> str:
    return f"学生年级: {grade}" if grade else ""


def _hint_info(user_hint: Optional[str]) -> str:
    return f"额外提示: {user_hint}" if user_hint else ""


def build_exam_analysis_prompt(*, subject: str, grade: str, user_hint: Optional[str], intake_mode: bool) -> str:
    """
    构建试卷分析 prompt（迁移自 core gemini_ocr_service，保持原逻辑/文案）。
    """
    subject_prompt = get_subject_prompt(subject)
    grade_info = _grade_info(grade)
    hint_info = _hint_info(user_hint)

    if intake_mode:
        # Compact schema: keep output small and stable for multi-question images.
        return f"""
{subject_prompt}

{grade_info}
{hint_info}

这是“错题识别/录入”场景：一张图片可能包含多道题。请按图片从上到下（如有左右分栏，先左后右）的顺序识别所有题目。

输出要求（非常重要）：
1) 只输出 JSON，不要输出 markdown code block
2) questions 必须包含图片中所有可识别题目；不要只输出第一题
3) 禁止输出冗长解题步骤/大段分析（不要输出 solution_steps；overall_analysis 可省略）
4) question_text 尽量完整，但单题不超过 600 字；其它字段尽量短
5) 识别“学生作答 vs 老师批阅”的规则（尽量提高准确度）：
   - 通常黑色/铅笔/原印刷为学生作答或题干；红色/蓝色等彩色笔迹更可能是老师批改或学生自标
   - teacher_marked_is_correct 只有在明确看到“√/✓/✔/对”或“×/✗/✘/错”且能对应到该题时才填写；不确定就填 null
   - teacher_marked_color 仅在能明显判断颜色时填写（red/blue/black），否则填 unknown 或省略
   - teacher_marked_evidence 用 <=30 字说明你看到的证据（例如“红色√在第2题旁”或“蓝色×在A选项旁”）
6) 选择题纠错示例（务必按卷面批改为准）：
   - 学生选 B，老师红笔把 B 划掉并标注正确答案 C => student_answer_raw="B", teacher_marked_answer="C", teacher_marked_mark="cross", teacher_marked_is_correct=false

JSON 格式（字段缺失可省略，但 questions 必须有）：
{{
  "subject": "{(subject or '').strip().lower()}",
  "grade": "{grade}",
  "questions": [
    {{
      "question_number": 1,
      "question_type": "选择题/填空题/解答题",
      "question_text": "完整题目内容",
      "student_answer_raw": "学生卷面原始答案（尽量按卷面抄写，可包含被划掉内容/改写，不可包含老师批改/学生自行标注的正确答案）",
      "teacher_marked_answer": "老师批改/学生自行标注的正确答案（如卷面可见；不可见则为空字符串）",
      "teacher_marked_is_correct": true/false/null,
      "teacher_marked_mark": "tick/cross/none",
      "teacher_marked_color": "red/blue/black/unknown",
      "teacher_marked_evidence": "简短证据（<=30字）",
      "model_inferred_answer": "模型根据题目推断的正确答案（用于参考；如无法推断则为空字符串）",
      "student_answer": "学生答案（可做适度清洗；如不确定可与 student_answer_raw 相同）",
      "correct_answer": "正确答案（优先使用 teacher_marked_answer；否则可填 model_inferred_answer）",
      "is_correct": true/false/null,
      "score": 0,
      "max_score": 0
    }}
  ]
}}
""".strip()

    return f"""
{subject_prompt}

{grade_info}
{hint_info}

请仔细分析这张试卷图片，完成以下任务:

1. **OCR识别**: 提取所有题目内容和学生的解答
2. **批改打分**: 判断每道题的对错并打分
3. **错因分析**: 对错误的题目分析错误原因
4. **知识点归纳**: 总结每道题涉及的知识点
5. **解题步骤**: 对错题提供详细的解题步骤

请严格按照以下JSON格式输出:

```json
{{
    "subject": "学科名称",
    "grade": "年级",
    "total_score": 实际得分,
    "max_score": 满分,
    "accuracy_rate": 正确率(0-1),
    "questions": [
        {{
            "question_number": 题号,
            "question_type": "选择题/填空题/解答题",
            "question_text": "完整题目内容",
            "student_answer_raw": "学生卷面原始答案（尽量按卷面抄写，可包含被划掉内容/改写）",
            "teacher_marked_answer": "老师批改/学生自行标注的正确答案（如卷面可见；不可见则为空字符串）",
            "teacher_marked_is_correct": true/false/null,
            "teacher_marked_mark": "tick/cross/none",
            "teacher_marked_color": "red/blue/black/unknown",
            "teacher_marked_evidence": "简短证据描述（<=30字）",
            "model_inferred_answer": "模型根据题目推断的正确答案（用于参考；如无法推断则为空字符串）",
            "student_answer": "学生答案（可做适度清洗；如不确定可与 student_answer_raw 相同）",
            "correct_answer": "正确答案（优先使用 teacher_marked_answer；否则可填 model_inferred_answer）",
            "score": 得分,
            "max_score": 该题满分,
            "is_correct": true/false,
            "error_analysis": "错误原因分析(如果错误)",
            "knowledge_points": ["知识点1", "知识点2"],
            "solution_steps": ["步骤1", "步骤2"],
            "difficulty": "easy/medium/hard"
        }}
    ],
    "overall_analysis": "整体表现分析",
    "weak_points": ["薄弱知识点1", "薄弱知识点2"],
    "improvement_suggestions": ["建议1", "建议2"]
}}
```

请确保输出的是有效的JSON格式。
"""


def build_compact_retry_prompt(*, subject: str, grade: str, user_hint: Optional[str]) -> str:
    """
    finish_reason=length 时的“短输出”重试提示（迁移自 core gemini_ocr_service 的拼接逻辑）。
    """
    subject_prompt = get_subject_prompt(subject)
    grade_info = _grade_info(grade)
    hint_info = _hint_info(user_hint)
    return (
        f"{subject_prompt}\n\n{grade_info}\n{hint_info}\n\n"
        "请只输出 JSON（不要 code block），并且不要输出 solution_steps/overall_analysis。"
        "questions 必须包含图片里所有题目。每题尽量短。"
    )


def resolve_ocr_model(*, default_model: str) -> str:
    """
    OCR/图像识别模型选择（保持原行为：OCR_VISION_MODEL -> TONY_OCR_VISION_MODEL -> default）。
    """
    return os.getenv("OCR_VISION_MODEL") or os.getenv("TONY_OCR_VISION_MODEL") or default_model


def resolve_temperature(*, intake_mode: bool) -> float:
    """
    temperature 选择（保持原行为）。
    """
    if intake_mode:
        return float(os.getenv("OCR_INTAKE_TEMPERATURE") or os.getenv("OCR_TEMPERATURE") or "0.1")
    return float(os.getenv("OCR_TEMPERATURE") or "0.3")


def resolve_max_tokens() -> int:
    """max_tokens 选择（保持原行为）。"""
    return int(os.getenv("OCR_MAX_TOKENS") or "8192")


def get_logging_config() -> Dict[str, Any]:
    """
    LLM 调试日志配置（保持原行为与 env var 名称）。
    """
    log_prompt = str(os.getenv("TONY_LLM_LOG_PROMPT", "true")).lower() in ("1", "true", "yes", "y", "on")
    log_response = str(os.getenv("TONY_LLM_LOG_RESPONSE", "true")).lower() in ("1", "true", "yes", "y", "on")
    prompt_limit = int(os.getenv("TONY_LLM_LOG_PROMPT_CHARS") or "12000")
    resp_limit = int(os.getenv("TONY_LLM_LOG_RESPONSE_CHARS") or "12000")
    return {
        "log_prompt": log_prompt,
        "log_response": log_response,
        "prompt_limit": prompt_limit,
        "resp_limit": resp_limit,
    }


