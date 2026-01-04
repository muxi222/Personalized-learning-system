"""
Question Schemas - Pydantic models for question-related API operations
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
import json
from pydantic import BaseModel, Field, ConfigDict, field_validator
from enum import Enum

class SubjectType(str, Enum):
    """学科类型"""
    MATH = "math"
    PHYSICS = "physics"
    CHEMISTRY = "chemistry"
    BIOLOGY = "biology"
    ENGLISH = "english"
    CHINESE = "chinese"
    HISTORY = "history"
    GEOGRAPHY = "geography"
    OTHER = "other"

class DifficultyLevel(str, Enum):
    """难度级别"""
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"

class QuestionBase(BaseModel):
    """Question基础Schema"""
    content: str = Field(..., min_length=1, description="题目内容")
    title: Optional[str] = Field(None, max_length=255, description="题目标题")
    subject: SubjectType = Field(SubjectType.OTHER, description="学科")
    difficulty: DifficultyLevel = Field(DifficultyLevel.MEDIUM, description="难度")
    image_urls: List[str] = Field(default_factory=list, description="题目图片URL列表")

    @field_validator("content", mode="before")
    @classmethod
    def normalize_content(cls, v: Any) -> str:
        """
        防止历史数据/异常流程写入空字符串导致 response_model 校验失败。
        """
        if v is None:
            return "题目内容待补充"
        if isinstance(v, str) and not v.strip():
            return "题目内容待补充"
        return v

class QuestionCreate(QuestionBase):
    """创建错题请求Schema"""
    student_answer: Optional[str] = Field(None, description="学生的错误答案")
    correct_answer: Optional[str] = Field(None, description="正确答案")
    explanation: Optional[str] = Field(None, description="原题解析")
    source: Optional[str] = Field(None, description="题目来源")
    chapter: Optional[str] = Field(None, description="章节")
    tags: List[str] = Field(default_factory=list, description="标签")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "content": "已知函数f(x) = x³ - 3x + 1，求f(x)的极值点。",
                "title": "导数应用-极值问题",
                "subject": "math",
                "difficulty": "medium",
                "student_answer": "极大值点为x=1，极小值点为x=-1",
                "correct_answer": "极大值点为x=-1，极小值点为x=1",
                "source": "高考真题2023",
                "chapter": "导数及其应用",
                "tags": ["导数", "极值", "函数"]
            }
        }
    )

class QuestionUpdate(BaseModel):
    """更新错题请求Schema"""
    title: Optional[str] = None
    content: Optional[str] = None
    subject: Optional[SubjectType] = None
    difficulty: Optional[DifficultyLevel] = None
    student_answer: Optional[str] = None
    correct_answer: Optional[str] = None
    explanation: Optional[str] = None
    tags: Optional[List[str]] = None
    mastery_level: Optional[float] = Field(None, ge=0, le=1)

class QuestionResponse(QuestionBase):
    """错题响应Schema"""
    id: int
    user_id: int
    student_answer: Optional[str] = None
    correct_answer: Optional[str] = None
    # 图片维度聚合/展示
    source_image_id: Optional[int] = None
    # OCR/批改结果（可选）
    is_correct: Optional[bool] = None
    score: Optional[float] = None
    max_score: Optional[float] = None
    knowledge_points: List[str] = []
    tags: List[str] = []
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class SuggestedQuestion(BaseModel):
    """举一反三题目Schema"""
    content: str = Field(..., description="题目内容")
    answer: str = Field(..., description="参考答案")
    difficulty: DifficultyLevel = Field(DifficultyLevel.MEDIUM)
    knowledge_points: List[str] = Field(default_factory=list)
    explanation: Optional[str] = Field(None, description="解题思路")

class QuestionDetail(QuestionResponse):
    """错题详情Schema (包含AI分析结果)"""
    explanation: Optional[str] = None
    error_analysis: Optional[str] = None
    suggested_questions: List[SuggestedQuestion] = []
    source: Optional[str] = None
    chapter: Optional[str] = None
    # Frontend-facing explanation of answer sources & grading basis (optional; derived in endpoints)
    answer_sources: Optional[Dict[str, Any]] = None

    @field_validator("suggested_questions", mode="before")
    @classmethod
    def normalize_suggested_questions(cls, v: Any):
        """
        Backward-compatible normalizer.
        Historical data may store suggested_questions as:
        - list[str]
        - list[dict] but with different keys (e.g. "question" instead of "content")
        - JSON-encoded string
        Normalize to List[SuggestedQuestion]-compatible dicts.
        """
        if v is None:
            return []

        # JSON string fallback
        if isinstance(v, str):
            s = v.strip()
            if (s.startswith("[") and s.endswith("]")) or (s.startswith("{") and s.endswith("}")):
                try:
                    v = json.loads(s)
                except Exception:
                    return []
            else:
                # single string -> one suggested question
                return [
                    {
                        "content": s,
                        "answer": "",
                        "difficulty": DifficultyLevel.MEDIUM,
                        "knowledge_points": [],
                        "explanation": None,
                    }
                ]

        if not isinstance(v, list):
            return []

        out: List[Dict[str, Any]] = []
        for item in v:
            if item is None:
                continue
            if isinstance(item, str):
                text = item.strip()
                if not text:
                    continue
                out.append(
                    {
                        "content": text,
                        "answer": "",
                        "difficulty": DifficultyLevel.MEDIUM,
                        "knowledge_points": [],
                        "explanation": None,
                    }
                )
                continue
            if isinstance(item, dict):
                content = (item.get("content") or item.get("question") or item.get("title") or "").strip() if isinstance(item.get("content") or item.get("question") or item.get("title") or "", str) else ""
                if not content:
                    continue
                answer = item.get("answer")
                if not isinstance(answer, str):
                    # backward compat: allow "solution" or missing
                    answer = item.get("solution") if isinstance(item.get("solution"), str) else ""
                difficulty = item.get("difficulty") or DifficultyLevel.MEDIUM
                # normalize knowledge_points
                kps = item.get("knowledge_points") or item.get("knowledge_point") or []
                if isinstance(kps, str):
                    kps = [k.strip() for k in kps.split(",") if k.strip()]
                if not isinstance(kps, list):
                    kps = []
                kps = [str(x).strip() for x in kps if str(x).strip()]
                explanation = item.get("explanation")
                if explanation is not None and not isinstance(explanation, str):
                    explanation = None
                out.append(
                    {
                        "content": content,
                        "answer": answer,
                        "difficulty": difficulty,
                        "knowledge_points": kps,
                        "explanation": explanation,
                    }
                )
                continue
            # unknown type -> ignore
        return out

    # 学习追踪
    review_count: int = 0
    mastery_level: float = 0.0
    next_review_at: Optional[datetime] = None
    last_reviewed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)

class QuestionListResponse(BaseModel):
    """错题列表响应Schema"""
    total: int
    page: int
    page_size: int
    items: List[QuestionResponse]

class QuestionGroup(BaseModel):
    """
    错题分组（用于错题本展示）
    - group_by='upload'：按上传图片/文本维度聚合（同一张图里的多道题会在同一组）
    - group_by='chapter'：按题目类型（章节/分类）聚合
    """
    group_key: str
    group_by: str
    subject: SubjectType
    chapter: Optional[str] = None
    knowledge_point: Optional[str] = None
    upload_type: str = Field(..., description="image 或 text")
    preview_image_url: Optional[str] = None
    # Group-level metadata for list display / filtering
    created_at: Optional[datetime] = None
    tags: List[str] = Field(default_factory=list, description="该组题目的聚合标签(去重)")
    count: int
    questions: List[QuestionResponse]

class QuestionGroupedListResponse(BaseModel):
    """错题列表（分组版）"""
    # 为兼容前端分页：total 表示分组数量（用于分页）
    total: int
    # 额外字段：真实错题数量
    total_questions: int
    total_groups: int
    page: int
    page_size: int
    group_by: str
    items: List[QuestionGroup]

class ChapterCount(BaseModel):
    chapter: str
    count: int

class SubjectChapterStats(BaseModel):
    subject: SubjectType
    total: int
    chapters: List[ChapterCount]

class QuestionChaptersResponse(BaseModel):
    """返回各学科的题目类型(章节/分类)统计"""
    items: List[SubjectChapterStats]

class KnowledgePointCount(BaseModel):
    knowledge_point: str
    count: int

class SubjectKnowledgePointStats(BaseModel):
    subject: SubjectType
    total: int
    knowledge_points: List[KnowledgePointCount]

class QuestionKnowledgePointsResponse(BaseModel):
    """返回各学科的知识点(knowledge_points)统计"""
    items: List[SubjectKnowledgePointStats]

class QuestionAnalysisRequest(BaseModel):
    """请求重新分析错题"""
    question_id: int
    force_reanalyze: bool = Field(False, description="强制重新分析")

class SimilarQuestionQuery(BaseModel):
    """查询相似题目请求"""
    question_id: Optional[int] = None
    content: Optional[str] = None
    knowledge_points: List[str] = Field(default_factory=list)
    limit: int = Field(5, ge=1, le=20)
