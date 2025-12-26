"""
Task Schemas - Pydantic models for async task operations
"""

from datetime import datetime
from typing import Optional, Any, Dict
from pydantic import BaseModel, Field, ConfigDict
from enum import Enum


class TaskStatus(str, Enum):
    """任务状态"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskCreate(BaseModel):
    """创建任务请求 (内部使用)"""
    question_id: Optional[int] = None
    task_type: str = "analyze_question"


class TaskResponse(BaseModel):
    """任务创建响应"""
    task_id: str = Field(..., description="任务ID")
    status: TaskStatus = Field(TaskStatus.PENDING, description="任务状态")
    message: str = Field("Task created successfully", description="消息")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "task_id": "550e8400-e29b-41d4-a716-446655440000",
                "status": "pending",
                "message": "Task created successfully"
            }
        }
    )


class TaskStatusResponse(BaseModel):
    """任务状态查询响应"""
    task_id: str
    status: TaskStatus
    progress: float = Field(0.0, ge=0, le=100, description="进度百分比")
    current_step: Optional[str] = Field(None, description="当前步骤")
    result_id: Optional[int] = Field(None, description="结果ID (question_id)")
    error_message: Optional[str] = Field(None, description="错误信息")
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "task_id": "550e8400-e29b-41d4-a716-446655440000",
                "status": "completed",
                "progress": 100.0,
                "current_step": "update_final_result",
                "result_id": 42,
                "error_message": None,
                "started_at": "2024-01-15T10:30:00Z",
                "completed_at": "2024-01-15T10:30:15Z",
                "created_at": "2024-01-15T10:30:00Z"
            }
        }
    )


class TaskResult(BaseModel):
    """任务结果详情"""
    task_id: str
    status: TaskStatus
    question_id: Optional[int] = None
    error_analysis: Optional[str] = None
    suggested_questions: Optional[list] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

