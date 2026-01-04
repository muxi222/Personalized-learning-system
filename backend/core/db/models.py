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
    POLITICS = "politics"      # 政治
    ECONOMICS = "economics"    # 经济学
    HISTORY = "history"        # 历史
    GEOGRAPHY = "geography"    # 地理
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

class QuestionSourceEnum(str, enum.Enum):
    """错题来源枚举"""
    MANUAL = "manual"  # 手动录入
    AI_CORRECTION = "ai_correction"  # AI批注识别

class ImageFileTypeEnum(str, enum.Enum):
    """图片文件类型枚举"""
    ORIGINAL = "original"  # 原始图片（用户上传）
    CORRECTED = "corrected"  # 批改后图片（AI生成）

class ImageFile(Base):
    """图片文件模型 - 用于去重"""
    __tablename__ = "image_files"

    id = Column(Integer, primary_key=True, index=True)
    file_hash = Column(String(64), unique=True, index=True, nullable=False)  # SHA256哈希值
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)  # 首次上传的用户
    file_type = Column(String(20), nullable=False, index=True)  # corrections 或 questions
    image_type = Column(String(20), default=ImageFileTypeEnum.ORIGINAL.value, index=True)  # original 或 corrected (使用字符串存储枚举值)
    subject = Column(String(20), nullable=True, index=True)  # 学科
    original_image_id = Column(Integer, ForeignKey("image_files.id"), nullable=True, index=True)  # 批改后图片对应的原始图片ID（用于关联）
    file_path = Column(String(500), nullable=False)  # 文件存储路径（使用hash值作为文件名）
    file_size = Column(Integer, nullable=False)  # 文件大小（字节）
    mime_type = Column(String(50), nullable=True)  # MIME类型
    reference_count = Column(Integer, default=1)  # 引用计数（有多少记录引用了这个文件）
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", backref="image_files")
    original_image = relationship("ImageFile", remote_side=[id], foreign_keys=[original_image_id], backref="derived_images")  # 原始图片关系

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
    exam_corrections = relationship("ExamCorrection", back_populates="user")

class Question(Base):
    """错题模型 - 根据设计文档4.1节"""
    __tablename__ = "questions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    exam_correction_id = Column(Integer, ForeignKey("exam_corrections.id"), nullable=True, index=True)  # 关联的批注记录

    # 基本信息 (设计文档4.1节结构化字段)
    title = Column(String(255), nullable=True)
    content = Column(Text, nullable=False)  # 题目内容 (question_body)
    image_urls = Column(JSON, default=list)  # 图片URL列表
    # 题目来源图片（与 image_files 表关联）。用于“按上传图片维度”聚合与稳定的图片展示 URL 生成。
    source_image_id = Column(Integer, ForeignKey("image_files.id"), nullable=True, index=True)
    subject = Column(SQLEnum(SubjectEnum), default=SubjectEnum.OTHER, index=True)  # 学科
    grade = Column(String(20), nullable=True, index=True)  # 年级 (高一, 初三等)
    difficulty = Column(SQLEnum(DifficultyEnum), default=DifficultyEnum.MEDIUM)  # 难度
    options = Column(JSON, default=list)  # 选项 (选择题)

    # 答案相关
    student_answer = Column(Text, nullable=True)  # 学生的错误答案
    correct_answer = Column(Text, nullable=True)  # 正确答案
    explanation = Column(Text, nullable=True)  # 原题解析

    # OCR/批改相关（录入错题/批改历史均可复用）
    is_correct = Column(Boolean, nullable=True)  # 是否答对（None 表示未知）
    score = Column(Float, nullable=True)  # 得分（可选）
    max_score = Column(Float, nullable=True)  # 满分（可选）

    # 录入错题功能专用字段
    original_input = Column(Text, nullable=True)  # 原始输入（文字录入时的原始JSON）
    summarized_input = Column(Text, nullable=True)  # 大模型总结后的输入

    # AI分析结果
    knowledge_points = Column(JSON, default=list)  # 涉及的知识点
    error_analysis = Column(Text, nullable=True)  # AI错因分析
    suggested_questions = Column(JSON, default=list)  # 举一反三题目

    # 元数据
    source = Column(SQLEnum(QuestionSourceEnum), default=QuestionSourceEnum.MANUAL, index=True)  # 错题来源
    source_description = Column(String(100), nullable=True)  # 来源描述
    chapter = Column(String(100), nullable=True)  # 章节
    tags = Column(JSON, default=list)  # 标签

    # 展示顺序（按一次“上传/录入”分组）
    # - upload_group_id: 同一次上传（图片/文本）的分组标识（通常可用 task_id）
    # - upload_index: 同一组内的题目顺序（按试卷从上到下/从左到右的顺序）
    upload_group_id = Column(String(64), nullable=True, index=True)
    upload_index = Column(Integer, nullable=True)

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
    exam_correction = relationship("ExamCorrection", back_populates="questions")

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

class ExamCorrection(Base):
    """AI批注记录模型"""
    __tablename__ = "exam_corrections"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    # 基本信息
    subject = Column(SQLEnum(SubjectEnum), default=SubjectEnum.OTHER, index=True)
    grade = Column(String(20), nullable=True, index=True)
    exam_title = Column(String(255), nullable=True)  # 试卷标题

    # 图片ID（关联image_files表）
    original_image_id = Column(Integer, ForeignKey("image_files.id"), nullable=False, index=True)  # 原始试卷图片ID
    corrected_image_id = Column(Integer, ForeignKey("image_files.id"), nullable=True, index=True)  # 批改后图片ID

    # Relationships
    original_image = relationship("ImageFile", foreign_keys=[original_image_id], backref="exam_corrections_as_original")
    corrected_image = relationship("ImageFile", foreign_keys=[corrected_image_id], backref="exam_corrections_as_corrected")

    # 统计数据
    total_score = Column(Float, default=0.0)  # 总得分
    max_score = Column(Float, default=100.0)  # 满分
    accuracy_rate = Column(Float, default=0.0)  # 正确率 (0-1)
    question_count = Column(Integer, default=0)  # 题目总数
    correct_count = Column(Integer, default=0)  # 答对题数
    wrong_count = Column(Integer, default=0)  # 答错题数

    # 分析结果
    overall_analysis = Column(Text, nullable=True)  # 总体分析
    weak_points = Column(JSON, default=list)  # 薄弱知识点
    improvement_suggestions = Column(JSON, default=list)  # 改进建议
    questions_detail = Column(JSON, default=list)  # 所有题目详情

    # 时间戳
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="exam_corrections")
    questions = relationship("Question", back_populates="exam_correction")

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
