"""
Database Session Management
支持 PostgreSQL (生产) 和 SQLite (开发)
"""

import os
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    AsyncEngine,
    create_async_engine,
    async_sessionmaker,
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.pool import StaticPool

from ..base_config import get_base_settings

settings = get_base_settings()

# Create Base class for declarative models
Base = declarative_base()


def _create_engine() -> AsyncEngine:
    """Create async database engine based on configuration"""
    database_url = settings.DATABASE_URL

    # SQLite specific configuration
    if "sqlite" in database_url:
        # Ensure directory exists
        db_path = database_url.split("///")[-1]
        if db_path != ":memory:":
            os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

        return create_async_engine(
            database_url,
            echo=settings.DATABASE_ECHO,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

    # PostgreSQL configuration
    return create_async_engine(
        database_url,
        echo=settings.DATABASE_ECHO,
        pool_size=settings.DATABASE_POOL_SIZE,
        max_overflow=settings.DATABASE_MAX_OVERFLOW,
        pool_pre_ping=True,
    )


# Create engine instance
engine = _create_engine()

# Create async session factory
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency for getting async database session.
    Usage:
        @app.get("/items")
        async def get_items(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Initialize database tables"""
    async with engine.begin() as conn:
        # Import all models to ensure they are registered with Base
        from ..db import models  # noqa: F401

        await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Close database connections"""
    await engine.dispose()

