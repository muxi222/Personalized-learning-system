"""
SQLAlchemy Database Models
数据库模型定义
"""

from datetime import datetime
from typing import Optional, List
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    Float,
    Boolean,
    ForeignKey,
    JSON,
    Enum as SQLEnum,
)
from sqlalchemy.orm import relationship
import enum

from .session import Base


class SubjectEnum(str, enum.Enum):
    """学科枚举"""
    MATH = "math"
    PHYSICS = "physics"
    CHEMISTRY = "chemistry"
    BIOLOGY = "biology"
    ENGLISH = "english"
    CHINESE = "chinese"
    OTHER = "other"


class DifficultyEnum(str, enum.Enum):
    """难度枚举"""
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class TaskStatusEnum(str, enum.Enum):
    """任务状态枚举"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class User(Base):
    """用户模型"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    email = Column(String(100), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(100), nullable=True)
    grade = Column(String(20), nullable=True)  # 年级
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    questions = relationship("Question", back_populates="user")
    feedbacks = relationship("Feedback", back_populates="user")


class Question(Base):
    """错题模型 - 根据设计文档4.1节"""
    __tablename__ = "questions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # 基本信息 (设计文档4.1节结构化字段)
    title = Column(String(255), nullable=True)
    content = Column(Text, nullable=False)  # 题目内容 (question_body)
    image_urls = Column(JSON, default=list)  # 图片URL列表
    subject = Column(SQLEnum(SubjectEnum), default=SubjectEnum.OTHER, index=True)  # 学科
    grade = Column(String(20), nullable=True, index=True)  # 年级 (高一, 初三等)
    difficulty = Column(SQLEnum(DifficultyEnum), default=DifficultyEnum.MEDIUM)  # 难度
    options = Column(JSON, default=list)  # 选项 (选择题)

    # 答案相关
    student_answer = Column(Text, nullable=True)  # 学生的错误答案
    correct_answer = Column(Text, nullable=True)  # 正确答案
    explanation = Column(Text, nullable=True)  # 原题解析

    # AI分析结果
    knowledge_points = Column(JSON, default=list)  # 涉及的知识点
    error_analysis = Column(Text, nullable=True)  # AI错因分析
    suggested_questions = Column(JSON, default=list)  # 举一反三题目

    # 元数据
    source = Column(String(100), nullable=True)  # 题目来源
    chapter = Column(String(100), nullable=True)  # 章节
    tags = Column(JSON, default=list)  # 标签

    # 学习追踪
    review_count = Column(Integer, default=0)  # 复习次数
    mastery_level = Column(Float, default=0.0)  # 掌握程度 (0-1)
    next_review_at = Column(DateTime, nullable=True)  # 下次复习时间
    last_reviewed_at = Column(DateTime, nullable=True)  # 上次复习时间

    # 时间戳
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="questions")
    feedbacks = relationship("Feedback", back_populates="question")
    tasks = relationship("AgentTask", back_populates="question")


class AgentTask(Base):
    """Agent任务模型"""
    __tablename__ = "agent_tasks"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(String(36), unique=True, index=True, nullable=False)  # UUID
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=True)

    # 任务状态
    status = Column(SQLEnum(TaskStatusEnum), default=TaskStatusEnum.PENDING, index=True)
    progress = Column(Float, default=0.0)  # 进度 (0-100)
    current_step = Column(String(100), nullable=True)  # 当前步骤

    # 结果和错误信息
    result = Column(JSON, nullable=True)
    error_message = Column(Text, nullable=True)

    # 时间追踪
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    # Relationships
    question = relationship("Question", back_populates="tasks")


class Feedback(Base):
    """用户反馈模型"""
    __tablename__ = "feedbacks"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=False)

    # 反馈内容
    feedback_type = Column(String(50), nullable=False)  # helpful, not_helpful, incorrect
    rating = Column(Integer, nullable=True)  # 1-5 star rating
    comment = Column(Text, nullable=True)

    # 用于RLHF
    original_response = Column(Text, nullable=True)
    preferred_response = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="feedbacks")
    question = relationship("Question", back_populates="feedbacks")


class KnowledgePoint(Base):
    """知识点模型 (用于知识图谱)"""
    __tablename__ = "knowledge_points"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False, index=True)
    subject = Column(SQLEnum(SubjectEnum), nullable=False, index=True)
    description = Column(Text, nullable=True)

    # 层级关系
    parent_id = Column(Integer, ForeignKey("knowledge_points.id"), nullable=True)
    level = Column(Integer, default=1)  # 知识点层级

    # 元数据
    difficulty_avg = Column(Float, default=0.5)  # 平均难度
    importance = Column(Float, default=0.5)  # 重要性权重

    created_at = Column(DateTime, default=datetime.utcnow)

    # Self-referential relationship for prerequisite knowledge
    parent = relationship("KnowledgePoint", remote_side=[id], backref="children")

