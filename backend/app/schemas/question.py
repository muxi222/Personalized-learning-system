"""
Question Schemas - Pydantic models for question-related API operations
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, ConfigDict
from enum import Enum


class SubjectType(str, Enum):
    """学科类型"""
    MATH = "math"
    PHYSICS = "physics"
    CHEMISTRY = "chemistry"
    BIOLOGY = "biology"
    ENGLISH = "english"
    CHINESE = "chinese"
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

