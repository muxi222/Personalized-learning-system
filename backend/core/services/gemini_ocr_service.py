"""
Gemini OCR Service - 智能试卷分析与批改服务

功能:
1. gemini-2.5-flash + thinking_config(16384):
   - 试卷照片 → 提取「题目 + 学生解答」
   - 自动纠错 + 解析 + 打分 (JSON 结构化输出)

2. gemini-2.5-flash (image generation):
   - 根据解析生成「黑板讲解图」
   - 在原卷面上进行「红笔批改、写评语」的图像编辑

实现方式:
- 通过统一的 LLM API 端点访问 Gemini 模型
- 使用 httpx 进行 HTTP 请求
- 支持多模态输入（文本 + 图像）
"""

import os
import json
import base64
import logging
from typing import List, Optional, Dict, Any
from functools import lru_cache
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import httpx

from ..base_config import get_base_settings

settings = get_base_settings()

logger = logging.getLogger(__name__)

# 中文学科名称到英文的映射
SUBJECT_NAME_MAP = {
    "数学": "math",
    "英语": "english",
    "物理": "physics",
    "化学": "chemistry",
    "语文": "chinese",
    "生物": "biology",
    "政治": "politics",
    "经济学": "economics",
    "历史": "history",
    "地理": "geography",
    "其他": "other",
}


class SubjectType(str, Enum):
    """学科类型"""
    MATH = "math"
    ENGLISH = "english"
    PHYSICS = "physics"
    CHEMISTRY = "chemistry"
    CHINESE = "chinese"
    BIOLOGY = "biology"
    POLITICS = "politics"
    ECONOMICS = "economics"
    HISTORY = "history"
    GEOGRAPHY = "geography"
    OTHER = "other"


def parse_subject_type(subject: str) -> SubjectType:
    """
    解析学科类型，支持中文和英文输入
    
    Args:
        subject: 学科名称（中文或英文）
    
    Returns:
        SubjectType 枚举值
    """
    if not subject:
        return SubjectType.OTHER
    
    # 先尝试中文映射
    subject_en = SUBJECT_NAME_MAP.get(subject, subject.lower())
    
    # 然后尝试枚举解析
    try:
        return SubjectType(subject_en)
    except ValueError:
        return SubjectType.OTHER


@dataclass
class QuestionItem:
    """单道题目解析结果"""
    question_number: int
    question_type: str  # 选择题, 填空题, 解答题
    question_text: str
    student_answer: str
    correct_answer: Optional[str] = None
    score: float = 0.0
    max_score: float = 0.0
    is_correct: bool = False
    error_analysis: str = ""
    knowledge_points: List[str] = field(default_factory=list)
    solution_steps: List[str] = field(default_factory=list)
    difficulty: str = "medium"


@dataclass
class ExamAnalysisResult:
    """试卷分析结果"""
    subject: SubjectType
    grade: str
    total_score: float
    max_score: float
    accuracy_rate: float
    questions: List[QuestionItem]
    overall_analysis: str
    weak_points: List[str]
    improvement_suggestions: List[str]
    raw_response: Optional[str] = None


@dataclass
class CorrectionImageResult:
    """批改图像结果"""
    original_image_path: str
    corrected_image_base64: Optional[str] = None
    correction_notes: List[str] = field(default_factory=list)
    success: bool = False
    error_message: str = ""


class GeminiOCRService:
    """
    Gemini OCR 服务

    使用 Gemini 2.5 Flash 模型进行:
    1. 试卷图片 OCR + 结构化解析
    2. 自动批改 + 打分
    3. 生成讲解图 (黑板风格)
    4. 红笔批改效果
    """

    def __init__(self):
        self._http_client: Optional[httpx.AsyncClient] = None
        self._initialized = False
        self._api_endpoint = settings.LLM_API_ENDPOINT
        self._api_key = settings.LLM_API_KEY

    async def initialize(self) -> bool:
        """初始化 HTTP 客户端"""
        if self._initialized:
            return True

        try:
            if not self._api_endpoint:
                logger.error("LLM_API_ENDPOINT not configured")
                return False

            if not self._api_key:
                logger.error("LLM_API_KEY not configured")
                return False

            # 创建 HTTP 客户端
            self._http_client = httpx.AsyncClient(
                base_url=self._api_endpoint,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                timeout=120.0,
            )

            self._initialized = True
            logger.info(f"Gemini OCR service initialized with endpoint: {self._api_endpoint}")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize Gemini OCR service: {e}")
            return False

    async def close(self):
        """关闭 HTTP 客户端"""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
            self._initialized = False

    def _load_image_as_base64(self, image_path: str) -> Optional[str]:
        """将图片文件转换为 base64"""
        try:
            with open(image_path, 'rb') as f:
                return base64.b64encode(f.read()).decode('utf-8')
        except Exception as e:
            logger.error(f"Failed to load image: {e}")
            return None

    def _get_subject_prompt(self, subject: SubjectType) -> str:
        """获取学科专用的分析提示"""
        prompts = {
            SubjectType.MATH: """
你是一位资深的数学老师。请特别注意:
- 计算过程的每一步是否正确
- 公式运用是否恰当
- 逻辑推理是否严密
- 几何证明步骤是否完整
""",
            SubjectType.PHYSICS: """
你是一位资深的物理老师。请特别注意:
- 物理概念理解是否准确
- 公式选择是否正确
- 单位换算是否正确
- 物理量的方向和正负号
""",
            SubjectType.CHEMISTRY: """
你是一位资深的化学老师。请特别注意:
- 化学方程式是否配平
- 反应条件是否正确标注
- 离子方程式书写是否规范
- 有机物结构式是否正确
""",
            SubjectType.ENGLISH: """
你是一位资深的英语老师。请特别注意:
- 语法错误 (时态、主谓一致、冠词等)
- 词汇使用是否恰当
- 句子结构是否正确
- 拼写错误
""",
            SubjectType.CHINESE: """
你是一位资深的语文老师。请特别注意:
- 字词书写是否规范
- 语句是否通顺
- 文章结构是否合理
- 主题表达是否清晰
""",
        }
        return prompts.get(subject, "你是一位经验丰富的老师。")

    async def analyze_exam_image(
        self,
        image_path: str,
        subject: SubjectType = SubjectType.OTHER,
        grade: str = "",
        user_hint: Optional[str] = None,
    ) -> ExamAnalysisResult:
        """
        分析试卷图片

        使用 gemini-2.5-flash + thinking_config 进行深度分析:
        1. OCR 提取题目和学生解答
        2. 自动纠错
        3. 详细解析
        4. 打分

        Args:
            image_path: 图片路径
            subject: 学科类型
            grade: 年级
            user_hint: 用户提供的额外提示

        Returns:
            ExamAnalysisResult: 结构化分析结果
        """
        if not self._initialized:
            await self.initialize()

        try:
            # 加载图片
            image_data = self._load_image_as_base64(image_path)
            if not image_data:
                return self._create_error_result("无法加载图片")

            # 检测图片类型
            image_ext = Path(image_path).suffix.lower()
            mime_types = {
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.png': 'image/png',
                '.gif': 'image/gif',
                '.webp': 'image/webp',
            }
            mime_type = mime_types.get(image_ext, 'image/jpeg')

            # 构建 prompt
            subject_prompt = self._get_subject_prompt(subject)
            grade_info = f"学生年级: {grade}" if grade else ""
            hint_info = f"额外提示: {user_hint}" if user_hint else ""

            prompt = f"""
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
            "student_answer": "学生的答案",
            "correct_answer": "正确答案",
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

            # 构建 API 请求（OpenAI Vision API 格式）
            request_data = {
                "model": settings.GEMINI_MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": prompt
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{mime_type};base64,{image_data}"
                                }
                            }
                        ]
                    }
                ],
                "temperature": 0.3,
                "max_tokens": 8192,
            }

            # 调用 API
            logger.info(f"Sending request to {self._api_endpoint}/chat/completions")
            response = await self._http_client.post(
                "/chat/completions",
                json=request_data,
            )

            response.raise_for_status()
            response_data = response.json()

            # 提取响应文本
            if "choices" not in response_data or not response_data["choices"]:
                return self._create_error_result("API 返回格式错误", str(response_data))

            response_text = response_data["choices"][0]["message"]["content"]
            logger.debug(f"Gemini response: {response_text[:500]}...")

            # 提取 JSON
            result_data = self._extract_json(response_text)
            if not result_data:
                return self._create_error_result("无法解析分析结果", response_text)

            # 构建结果
            questions = []
            for q in result_data.get('questions', []):
                questions.append(QuestionItem(
                    question_number=q.get('question_number', 0),
                    question_type=q.get('question_type', ''),
                    question_text=q.get('question_text', ''),
                    student_answer=q.get('student_answer', ''),
                    correct_answer=q.get('correct_answer'),
                    score=q.get('score', 0),
                    max_score=q.get('max_score', 0),
                    is_correct=q.get('is_correct', False),
                    error_analysis=q.get('error_analysis', ''),
                    knowledge_points=q.get('knowledge_points', []),
                    solution_steps=q.get('solution_steps', []),
                    difficulty=q.get('difficulty', 'medium'),
                ))

            # 始终使用用户传入的学科类型，不使用模型推断的
            # 这样可以确保入库的学科与用户选择的学科一致
            parsed_subject = subject
            logger.info(f"Using user-provided subject: {parsed_subject.value}")

            return ExamAnalysisResult(
                subject=parsed_subject,
                grade=result_data.get('grade', grade),
                total_score=result_data.get('total_score', 0),
                max_score=result_data.get('max_score', 0),
                accuracy_rate=result_data.get('accuracy_rate', 0),
                questions=questions,
                overall_analysis=result_data.get('overall_analysis', ''),
                weak_points=result_data.get('weak_points', []),
                improvement_suggestions=result_data.get('improvement_suggestions', []),
                raw_response=response_text,
            )

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error during exam analysis: {e.response.status_code} - {e.response.text}")
            return self._create_error_result(f"API 请求失败: {e.response.status_code}")
        except Exception as e:
            logger.error(f"Exam analysis error: {e}")
            return self._create_error_result(str(e))

    async def generate_explanation_image(
        self,
        question: QuestionItem,
        style: str = "blackboard",
    ) -> Optional[str]:
        """
        生成讲解图

        使用 Gemini 图像生成能力创建黑板风格的讲解图

        Args:
            question: 题目信息
            style: 图像风格 (blackboard, whiteboard, notebook)

        Returns:
            base64 编码的图像数据
        """
        if not self._initialized:
            await self.initialize()

        try:
            style_prompts = {
                "blackboard": "Create a blackboard-style educational illustration with chalk writing",
                "whiteboard": "Create a whiteboard-style educational diagram with marker writing",
                "notebook": "Create a notebook-style handwritten explanation",
            }

            prompt = f"""
{style_prompts.get(style, style_prompts['blackboard'])}

题目: {question.question_text}

正确答案: {question.correct_answer}

解题步骤:
{chr(10).join(f'{i+1}. {step}' for i, step in enumerate(question.solution_steps))}

知识点: {', '.join(question.knowledge_points)}

请生成一张清晰、美观的讲解图，包含:
1. 题目简述
2. 关键解题步骤
3. 重要公式或概念
4. 答案标注

风格要求: 教学用途，清晰易懂，适合学生理解
"""

            # Note: Gemini 2.5 Flash 主要用于理解，图像生成能力有限
            # 这里提供一个框架，实际应用中可能需要结合其他服务
            logger.info("Explanation image generation requested (placeholder)")

            return None  # 返回 None 表示功能待实现

        except Exception as e:
            logger.error(f"Failed to generate explanation image: {e}")
            return None

    def _load_chinese_font(self, size: int = 24) -> "ImageFont.FreeTypeFont":
        """
        加载支持中文的字体
        
        尝试多个系统字体路径，确保中文正确显示
        """
        from PIL import ImageFont
        
        # 按优先级尝试不同操作系统的中文字体
        font_paths = [
            # macOS
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/STHeiti Medium.ttc",
            "/System/Library/Fonts/Hiragino Sans GB.ttc",
            "/Library/Fonts/Arial Unicode.ttf",
            # Linux
            "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            # Windows
            "C:\\Windows\\Fonts\\simhei.ttf",
            "C:\\Windows\\Fonts\\msyh.ttc",
            "C:\\Windows\\Fonts\\simsun.ttc",
        ]
        
        for font_path in font_paths:
            try:
                font = ImageFont.truetype(font_path, size)
                logger.debug(f"Loaded font: {font_path}")
                return font
            except Exception:
                continue
        
        # 如果所有字体都失败，记录警告并使用默认字体（会显示方框）
        logger.warning(
            "Failed to load any Chinese font. Text may display as boxes. "
            "Install a Chinese font or specify FONT_PATH in config."
        )
        return ImageFont.load_default()

    async def create_correction_overlay(
        self,
        image_path: str,
        analysis_result: ExamAnalysisResult,
        correction_style: str = "red_pen",
    ) -> CorrectionImageResult:
        """
        在原试卷上添加批改效果

        模拟「红笔批改」效果，在原图上添加:
        - 对勾/叉号
        - 分数标注
        - 评语

        Args:
            image_path: 原始试卷图片路径
            analysis_result: 分析结果
            correction_style: 批改风格 (red_pen, blue_pen, stamp)

        Returns:
            CorrectionImageResult: 包含批改后的图像
        """
        try:
            from PIL import Image, ImageDraw

            # 加载原图
            img = Image.open(image_path)
            draw = ImageDraw.Draw(img)

            # 加载中文字体
            font = self._load_chinese_font(size=24)
            small_font = self._load_chinese_font(size=16)

            # 颜色设置
            colors = {
                "red_pen": "#FF0000",
                "blue_pen": "#0000FF",
                "stamp": "#8B0000",
            }
            color = colors.get(correction_style, "#FF0000")

            correction_notes = []

            # 添加总分
            total_text = f"总分: {analysis_result.total_score}/{analysis_result.max_score}"
            draw.text((img.width - 200, 30), total_text, fill=color, font=font)
            correction_notes.append(total_text)

            # 添加评语
            if analysis_result.overall_analysis:
                # 在底部添加评语
                comment = f"评语: {analysis_result.overall_analysis[:50]}..."
                draw.text((30, img.height - 60), comment, fill=color, font=small_font)
                correction_notes.append(f"评语: {analysis_result.overall_analysis}")

            # 保存为 base64
            import io
            buffer = io.BytesIO()
            img.save(buffer, format='PNG')
            img_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')

            return CorrectionImageResult(
                original_image_path=image_path,
                corrected_image_base64=img_base64,
                correction_notes=correction_notes,
                success=True,
            )

        except Exception as e:
            logger.error(f"Failed to create correction overlay: {e}")
            return CorrectionImageResult(
                original_image_path=image_path,
                success=False,
                error_message=str(e),
            )

    def _extract_json(self, text: str) -> Optional[Dict]:
        """从文本中提取 JSON"""
        try:
            # 尝试直接解析
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 尝试从 markdown 代码块中提取
        import re
        json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # 尝试找到第一个 { 到最后一个 }
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1:
            try:
                return json.loads(text[start:end+1])
            except json.JSONDecodeError:
                pass

        return None

    def _create_error_result(
        self,
        error_message: str,
        raw_response: Optional[str] = None
    ) -> ExamAnalysisResult:
        """创建错误结果"""
        return ExamAnalysisResult(
            subject=SubjectType.OTHER,
            grade="",
            total_score=0,
            max_score=0,
            accuracy_rate=0,
            questions=[],
            overall_analysis=f"分析失败: {error_message}",
            weak_points=[],
            improvement_suggestions=[],
            raw_response=raw_response,
        )


# Singleton instance
_gemini_ocr_service: Optional[GeminiOCRService] = None


@lru_cache()
def get_gemini_ocr_service() -> GeminiOCRService:
    """Get singleton Gemini OCR service instance"""
    global _gemini_ocr_service
    if _gemini_ocr_service is None:
        _gemini_ocr_service = GeminiOCRService()
    return _gemini_ocr_service
