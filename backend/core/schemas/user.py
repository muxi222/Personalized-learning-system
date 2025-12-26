"""
User Schemas - Pydantic models for user operations
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, EmailStr, ConfigDict


class UserBase(BaseModel):
    """User基础Schema"""
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    full_name: Optional[str] = Field(None, max_length=100)
    grade: Optional[str] = Field(None, max_length=20, description="年级")


class UserCreate(UserBase):
    """用户注册请求"""
    password: str = Field(..., min_length=6, max_length=500)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "username": "student001",
                "email": "student@example.com",
                "password": "securepassword123",
                "full_name": "张三",
                "grade": "高三"
            }
        }
    )


class UserUpdate(BaseModel):
    """用户更新请求"""
    full_name: Optional[str] = None
    grade: Optional[str] = None
    password: Optional[str] = Field(None, min_length=6, max_length=500)


class UserResponse(UserBase):
    """用户响应Schema"""
    id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserLogin(BaseModel):
    """用户登录请求"""
    username: str
    password: str


class Token(BaseModel):
    """JWT Token响应"""
    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(..., description="过期时间(秒)")


class TokenPayload(BaseModel):
    """Token载荷"""
    sub: str  # user_id
    exp: datetime
    iat: datetime

