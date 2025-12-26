"""
Users API Endpoints
用户认证与管理API
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from jose import jwt

from backend.core.db.session import get_db
from backend.core.crud import crud_user
from backend.core.schemas.user import (
    UserCreate,
    UserResponse,
    UserLogin,
    Token,
)
from backend.modules.default.config import settings
from backend.modules.default.api.deps import get_current_user, get_current_user_id

logger = logging.getLogger(__name__)

router = APIRouter()


def create_access_token(user_id: int, expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT access token"""
    expire = datetime.utcnow() + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode = {
        "sub": str(user_id),
        "exp": expire,
        "iat": datetime.utcnow(),
    }
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


@router.post("/register", response_model=UserResponse, status_code=201)
async def register_user(
    user_data: UserCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    用户注册
    """
    # Debug 级别日志：详细记录接收到的数据（不记录密码明文）
    logger.debug(
        f"Registration request received: "
        f"username='{user_data.username}' (len={len(user_data.username)}, type={type(user_data.username).__name__}), "
        f"email='{user_data.email}' (type={type(user_data.email).__name__}), "
        f"full_name={repr(user_data.full_name)} (type={type(user_data.full_name).__name__ if user_data.full_name else 'None'}), "
        f"grade={repr(user_data.grade)} (type={type(user_data.grade).__name__ if user_data.grade else 'None'}), "
        f"password_length={len(user_data.password) if user_data.password else 0} (type={type(user_data.password).__name__ if user_data.password else 'None'})"
    )
    
    # Info 级别日志：简要记录
    logger.info(f"Registration attempt: username={user_data.username}, email={user_data.email}")
    
    # Check if username exists
    logger.debug(f"Checking if username '{user_data.username}' exists")
    existing = await crud_user.get_user_by_username(db, user_data.username)
    if existing:
        logger.warning(f"Registration failed: username '{user_data.username}' already exists")
        raise HTTPException(
            status_code=400,
            detail="Username already registered"
        )

    # Check if email exists
    logger.debug(f"Checking if email '{user_data.email}' exists")
    existing = await crud_user.get_user_by_email(db, user_data.email)
    if existing:
        logger.warning(f"Registration failed: email '{user_data.email}' already exists")
        raise HTTPException(
            status_code=400,
            detail="Email already registered"
        )

    # Create user
    logger.debug("Creating user in database")
    try:
        user = await crud_user.create_user(db, user_data)
        logger.debug(f"User created successfully, id={user.id}")
    except ValueError as exc:
        logger.error(f"Registration failed (ValueError): {exc}")
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(f"Registration failed (unexpected error): {exc}", exc_info=True)
        await db.rollback()
        raise HTTPException(status_code=500, detail="Registration failed due to server error") from exc
    
    await db.commit()
    logger.info(f"New user registered successfully: id={user.id}, username={user.username}, email={user.email}")
    return UserResponse.model_validate(user)


@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """
    用户登录 (OAuth2 兼容)
    """
    user = await crud_user.authenticate_user(
        db, form_data.username, form_data.password
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled"
        )

    access_token = create_access_token(user.id)

    logger.info(f"User logged in: {user.username}")
    return Token(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/token", response_model=Token)
async def login_for_token(
    user_data: UserLogin,
    db: AsyncSession = Depends(get_db),
):
    """
    用户登录 (JSON body)
    """
    user = await crud_user.authenticate_user(
        db, user_data.username, user_data.password
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled"
        )

    access_token = create_access_token(user.id)

    return Token(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """
    获取当前用户信息
    """
    user = await crud_user.get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse.model_validate(user)


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
):
    """
    获取用户信息 (仅能查看自己)
    """
    if user_id != current_user_id:
        raise HTTPException(status_code=403, detail="Not authorized")

    user = await crud_user.get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return UserResponse.model_validate(user)

