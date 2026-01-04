"""
API Dependencies
认证和通用依赖
"""

import logging
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession

from backend.modules.wzy.config import settings
from backend.core.db.session import get_db
from backend.core.crud import crud_user
from backend.core.db.models import User

logger = logging.getLogger(__name__)

# OAuth2 scheme
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_PREFIX}/users/login",
    auto_error=False,  # Don't auto-error, handle manually for better messages
)

async def get_current_user_id(
    token: Optional[str] = Depends(oauth2_scheme),
) -> int:
    """
    Get current user ID from JWT token

    For development: if no token provided, return default user ID 1
    For production: require valid token
    """
    if not token:
        if settings.is_development:
            # Development mode: allow unauthenticated access with default user
            logger.warning("No auth token - using default user ID 1 (dev mode)")
            return 1
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        user_id_str: str = payload.get("sub")
        if user_id_str is None:
            raise credentials_exception

        user_id = int(user_id_str)
        return user_id

    except JWTError as e:
        logger.warning(f"JWT decode error: {e}")
        raise credentials_exception
    except ValueError:
        logger.warning("Invalid user ID in token")
        raise credentials_exception

async def get_current_user(
    db: AsyncSession = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
) -> User:
    """
    Get current user object from database
    """
    user = await crud_user.get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="User account is disabled")

    return user

async def get_optional_user_id(
    token: Optional[str] = Depends(oauth2_scheme),
) -> Optional[int]:
    """
    Get user ID if authenticated, None otherwise
    Useful for endpoints that work both authenticated and unauthenticated
    """
    if not token:
        return None

    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        user_id_str: str = payload.get("sub")
        if user_id_str:
            return int(user_id_str)
    except (JWTError, ValueError):
        pass

    return None
