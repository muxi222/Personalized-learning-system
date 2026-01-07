"""XMX - Users API（学生实现版 / Stub）

仅保留主要入口 endpoints 的定义，删除具体实现。
参考：`backend/modules/tony/api/endpoints/shared/users.py`
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.db.session import get_db
from backend.core.schemas.user import UserCreate, UserResponse, UserLogin, Token
from backend.modules.xmx.api.deps import get_current_user_id

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(user_data: UserCreate, db: AsyncSession = Depends(get_db)):
    """用户注册入口。"""
    raise HTTPException(status_code=501, detail="Not Implemented: register")


@router.post("/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    """用户登录入口（OAuth2 兼容）。"""
    raise HTTPException(status_code=501, detail="Not Implemented: login")


@router.post("/token", response_model=Token)
async def login_for_token(user_data: UserLogin, db: AsyncSession = Depends(get_db)):
    """用户登录入口（JSON body）。"""
    raise HTTPException(status_code=501, detail="Not Implemented: token")


@router.get("/me", response_model=UserResponse)
async def me(db: AsyncSession = Depends(get_db), user_id: int = Depends(get_current_user_id)):
    """当前用户信息入口。"""
    raise HTTPException(status_code=501, detail="Not Implemented: me")


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(user_id: int, db: AsyncSession = Depends(get_db)):
    """按ID查询用户入口。"""
    raise HTTPException(status_code=501, detail="Not Implemented: get_user")

