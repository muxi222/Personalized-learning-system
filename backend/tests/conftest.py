"""
Pytest Configuration and Fixtures
"""

import asyncio
import pytest
import pytest_asyncio
from typing import AsyncGenerator
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.session import Base, get_db
from app.core.config import settings

# Test database URL (in-memory SQLite)
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest_asyncio.fixture(scope="function")
async def test_engine():
    """Create test database engine"""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()

@pytest_asyncio.fixture(scope="function")
async def test_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create test database session"""
    async_session = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session() as session:
        yield session

@pytest_asyncio.fixture(scope="function")
async def client(test_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Create test HTTP client"""
    from main import app

    # Override get_db dependency
    async def override_get_db():
        yield test_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()

@pytest_asyncio.fixture(scope="function")
async def test_user(test_session: AsyncSession):
    """Create a test user"""
    from app.crud.crud_user import create_user
    from app.schemas.user import UserCreate

    user_data = UserCreate(
        username="testuser",
        email="test@example.com",
        password="testpassword123",
        full_name="Test User",
        grade="高三",
    )

    user = await create_user(test_session, user_data)
    await test_session.commit()
    return user

@pytest_asyncio.fixture(scope="function")
async def auth_headers(test_user) -> dict:
    """Get auth headers for test user"""
    from app.api.v1.endpoints.users import create_access_token

    token = create_access_token(test_user.id)
    return {"Authorization": f"Bearer {token}"}
