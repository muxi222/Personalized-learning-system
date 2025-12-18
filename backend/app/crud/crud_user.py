"""
User CRUD Operations
用户数据库操作
"""

import hashlib
import logging
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from passlib.context import CryptContext

from ..db.models import User
from ..schemas.user import UserCreate

logger = logging.getLogger(__name__)

# Support both legacy bcrypt hashes and new bcrypt-sha256 hashes.
# Default to bcrypt_sha256 for new passwords to avoid the 72-byte limit.
pwd_context = CryptContext(
    schemes=["bcrypt_sha256", "bcrypt"],
    deprecated="auto",
    bcrypt__truncate_error=False,
)

_BCRYPT_MAX_INPUT_BYTES = 72


def _normalize_password(password: str) -> str:
    """
    Normalize password so bcrypt never sees inputs longer than 72 bytes.

    Passlib's bcrypt variants raise ValueError when the encoded password exceeds
    72 bytes. To keep supporting arbitrarily long UTF-8 passwords we hash them
    with SHA-256 first (similar to passlib.hash.bcrypt_sha256) and return the
    hex digest. Short passwords are returned verbatim to preserve compatibility.
    """
    password_bytes = password.encode("utf-8")
    if len(password_bytes) <= _BCRYPT_MAX_INPUT_BYTES:
        return password
    digest = hashlib.sha256(password_bytes).hexdigest()
    logger.debug("Normalized password exceeding bcrypt limit (len=%s bytes)", len(password_bytes))
    return digest


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    normalized = _normalize_password(plain_password)
    if pwd_context.verify(normalized, hashed_password):
        return True
    # Fallback for legacy hashes that stored the raw (non-normalized) password.
    if normalized != plain_password:
        try:
            return pwd_context.verify(plain_password, hashed_password)
        except Exception:
            return False
    return False


def get_password_hash(password: str) -> str:
    """获取密码哈希"""
    normalized = _normalize_password(password)
    return pwd_context.hash(normalized)


async def create_user(
    db: AsyncSession,
    user_data: UserCreate,
) -> User:
    """创建新用户"""
    hashed_password = get_password_hash(user_data.password)
    db_user = User(
        username=user_data.username,
        email=user_data.email,
        hashed_password=hashed_password,
        full_name=user_data.full_name,
        grade=user_data.grade,
    )
    db.add(db_user)
    await db.flush()
    await db.refresh(db_user)
    return db_user


async def get_user(
    db: AsyncSession,
    user_id: int,
) -> Optional[User]:
    """通过ID获取用户"""
    query = select(User).where(User.id == user_id)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_user_by_username(
    db: AsyncSession,
    username: str,
) -> Optional[User]:
    """通过用户名获取用户"""
    query = select(User).where(User.username == username)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_user_by_email(
    db: AsyncSession,
    email: str,
) -> Optional[User]:
    """通过邮箱获取用户"""
    query = select(User).where(User.email == email)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def authenticate_user(
    db: AsyncSession,
    username: str,
    password: str,
) -> Optional[User]:
    """验证用户登录"""
    user = await get_user_by_username(db, username)
    if not user:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user


async def update_user(
    db: AsyncSession,
    user_id: int,
    **kwargs,
) -> Optional[User]:
    """更新用户信息"""
    user = await get_user(db, user_id)
    if not user:
        return None

    for field, value in kwargs.items():
        if value is not None and hasattr(user, field):
            if field == "password":
                value = get_password_hash(value)
                field = "hashed_password"
            setattr(user, field, value)

    await db.flush()
    await db.refresh(user)
    return user

