"""
Agent Tests
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock


class TestAgentState:
    """Test agent state definition"""

    def test_agent_state_creation(self):
        """Test creating agent state"""
        from app.agent.graph import AgentState

        state: AgentState = {
            "raw_input": "测试题目内容",
            "user_id": 1,
            "task_id": "test-task-id",
            "image_urls": [],
            "errors": [],
        }

        assert state["raw_input"] == "测试题目内容"
        assert state["user_id"] == 1


class TestAgentPrompts:
    """Test agent prompts"""

    def test_get_error_analysis_prompt(self):
        """Test getting subject-specific prompt"""
        from app.agent.prompts import get_error_analysis_prompt

        math_prompt = get_error_analysis_prompt("math")
        assert "数学" in math_prompt or "计算" in math_prompt

        physics_prompt = get_error_analysis_prompt("physics")
        assert "物理" in physics_prompt or "情境" in physics_prompt

        # Test fallback to general prompt
        other_prompt = get_error_analysis_prompt("unknown")
        assert other_prompt is not None


class TestAgentNodes:
    """Test individual agent nodes"""

    @pytest.mark.asyncio
    async def test_extract_info_node(self):
        """Test extract_info node"""
        from app.agent.nodes import extract_info
        from app.agent.graph import AgentState

        # Mock LLM service
        with patch("app.agent.nodes.get_llm_service") as mock_llm:
            mock_service = MagicMock()
            mock_service.generate_json = AsyncMock(
                return_value={
                    "title": "测试题目",
                    "content": "已知x+y=5，求x²+y²的最小值",
                    "subject": "math",
                    "difficulty": "medium",
                    "knowledge_points": ["二次函数", "最值问题"],
                }
            )
            mock_llm.return_value = mock_service

            state: AgentState = {
                "raw_input": "已知x+y=5，求x²+y²的最小值",
                "task_id": "test-task",
                "errors": [],
            }

            result = await extract_info(state)

            assert "structured_data" in result
            assert result["progress"] > 0

    @pytest.mark.asyncio
    async def test_generate_embedding_node(self):
        """Test generate_embedding node"""
        from app.agent.nodes import generate_embedding
        from app.agent.graph import AgentState

        # Mock embedding service
        with patch("app.agent.nodes.get_embedding_service") as mock_embed:
            mock_service = MagicMock()
            mock_service.embed_text = AsyncMock(return_value=[0.1] * 1536)
            mock_embed.return_value = mock_service

            state: AgentState = {
                "raw_input": "测试题目",
                "task_id": "test-task",
                "structured_data": {"content": "测试题目内容"},
                "knowledge_points": ["知识点1"],
                "errors": [],
            }

            result = await generate_embedding(state)

            assert "embedding" in result
            assert len(result["embedding"]) == 1536

    @pytest.mark.asyncio
    async def test_analyze_error_node(self):
        """Test analyze_error node"""
        from app.agent.nodes import analyze_error
        from app.agent.graph import AgentState

        # Mock LLM service
        with patch("app.agent.nodes.get_llm_service") as mock_llm:
            mock_service = MagicMock()
            mock_service.generate = AsyncMock(
                return_value="这是一道关于二次函数最值的问题..."
            )
            mock_llm.return_value = mock_service

            state: AgentState = {
                "raw_input": "测试题目",
                "task_id": "test-task",
                "structured_data": {
                    "content": "测试题目",
                    "student_answer": "错误答案",
                    "correct_answer": "正确答案",
                },
                "subject": "math",
                "knowledge_points": ["二次函数"],
                "errors": [],
            }

            result = await analyze_error(state)

            assert "error_analysis" in result
            assert len(result["error_analysis"]) > 0

    @pytest.mark.asyncio
    async def test_generate_suggestions_node(self):
        """Test generate_suggestions node"""
        from app.agent.nodes import generate_suggestions
        from app.agent.graph import AgentState

        # Mock LLM service
        with patch("app.agent.nodes.get_llm_service") as mock_llm:
            mock_service = MagicMock()
            mock_service.generate_json = AsyncMock(
                return_value=[
                    {
                        "content": "举一反三题目1",
                        "answer": "答案1",
                        "difficulty": "easy",
                        "knowledge_points": ["知识点"],
                    },
                    {
                        "content": "举一反三题目2",
                        "answer": "答案2",
                        "difficulty": "medium",
                        "knowledge_points": ["知识点"],
                    },
                ]
            )
            mock_llm.return_value = mock_service

            state: AgentState = {
                "raw_input": "测试题目",
                "task_id": "test-task",
                "structured_data": {"content": "测试题目"},
                "subject": "math",
                "knowledge_points": ["知识点"],
                "error_analysis": "错因分析内容",
                "errors": [],
            }

            result = await generate_suggestions(state)

            assert "suggested_questions" in result
            assert len(result["suggested_questions"]) == 2


class TestAgentGraph:
    """Test agent graph compilation"""

    def test_create_main_graph(self):
        """Test creating main agent graph"""
        from app.agent.graph import create_agent_graph

        graph = create_agent_graph()
        assert graph is not None

    def test_create_analysis_graph(self):
        """Test creating analysis-only graph"""
        from app.agent.graph import create_analysis_only_graph

        graph = create_analysis_only_graph()
        assert graph is not None

    def test_get_main_graph_singleton(self):
        """Test that get_main_graph returns singleton"""
        from app.agent.graph import get_main_graph

        graph1 = get_main_graph()
        graph2 = get_main_graph()
        assert graph1 is graph2

