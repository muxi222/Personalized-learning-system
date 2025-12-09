"""
API Tests
"""

import pytest
from httpx import AsyncClient


class TestHealthEndpoints:
    """Test health and root endpoints"""

    @pytest.mark.asyncio
    async def test_health_check(self, client: AsyncClient):
        """Test health check endpoint"""
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data

    @pytest.mark.asyncio
    async def test_root(self, client: AsyncClient):
        """Test root endpoint"""
        response = await client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "message" in data
        assert "docs" in data


class TestUserEndpoints:
    """Test user authentication endpoints"""

    @pytest.mark.asyncio
    async def test_register_user(self, client: AsyncClient):
        """Test user registration"""
        response = await client.post(
            "/api/v1/users/register",
            json={
                "username": "newuser",
                "email": "newuser@example.com",
                "password": "password123",
                "full_name": "New User",
                "grade": "高一",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["username"] == "newuser"
        assert data["email"] == "newuser@example.com"
        assert "id" in data

    @pytest.mark.asyncio
    async def test_register_duplicate_username(self, client: AsyncClient, test_user):
        """Test registration with duplicate username"""
        response = await client.post(
            "/api/v1/users/register",
            json={
                "username": "testuser",  # Same as test_user
                "email": "another@example.com",
                "password": "password123",
            },
        )
        assert response.status_code == 400
        assert "already registered" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_login(self, client: AsyncClient, test_user):
        """Test user login"""
        response = await client.post(
            "/api/v1/users/token",
            json={
                "username": "testuser",
                "password": "testpassword123",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, client: AsyncClient, test_user):
        """Test login with wrong password"""
        response = await client.post(
            "/api/v1/users/token",
            json={
                "username": "testuser",
                "password": "wrongpassword",
            },
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_get_current_user(self, client: AsyncClient, auth_headers):
        """Test get current user info"""
        response = await client.get("/api/v1/users/me", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "testuser"


class TestQuestionEndpoints:
    """Test question-related endpoints"""

    @pytest.mark.asyncio
    async def test_create_question(self, client: AsyncClient, auth_headers):
        """Test creating a new question"""
        response = await client.post(
            "/api/v1/questions/",
            headers=auth_headers,
            json={
                "content": "已知函数f(x)=x²-2x+1，求f(x)的最小值。",
                "title": "二次函数最值问题",
                "subject": "math",
                "difficulty": "easy",
                "student_answer": "最小值为0，当x=0时取得",
                "correct_answer": "最小值为0，当x=1时取得",
            },
        )
        assert response.status_code == 202
        data = response.json()
        assert "task_id" in data
        assert data["status"] == "pending"

    @pytest.mark.asyncio
    async def test_list_questions(self, client: AsyncClient, auth_headers):
        """Test listing questions"""
        response = await client.get("/api/v1/questions/", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert "page" in data

    @pytest.mark.asyncio
    async def test_list_questions_with_filters(self, client: AsyncClient, auth_headers):
        """Test listing questions with filters"""
        response = await client.get(
            "/api/v1/questions/",
            headers=auth_headers,
            params={"subject": "math", "difficulty": "easy"},
        )
        assert response.status_code == 200


class TestTaskEndpoints:
    """Test task-related endpoints"""

    @pytest.mark.asyncio
    async def test_get_nonexistent_task(self, client: AsyncClient):
        """Test getting a non-existent task"""
        response = await client.get("/api/v1/tasks/nonexistent-task-id")
        assert response.status_code == 404


class TestFeedbackEndpoints:
    """Test feedback endpoints"""

    @pytest.mark.asyncio
    async def test_get_feedback_stats(self, client: AsyncClient, auth_headers):
        """Test getting feedback statistics"""
        response = await client.get("/api/v1/feedback/stats", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert "total_feedbacks" in data
        assert "helpful_count" in data
        assert "feedback_rate" in data

