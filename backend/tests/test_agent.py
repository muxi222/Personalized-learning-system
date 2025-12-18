"""
Agent Tests - 测试 LangGraph Agent 模块

测试覆盖:
- Agent 状态定义
- Prompt 模板
- Agent 工作流
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock


class TestAgentState:
    """Test agent state definition"""

    def test_agent_state_creation(self):
        """Test creating agent state"""
        from app.agents.state import AgentState

        state: AgentState = {
            "raw_input": "测试题目内容",
            "user_id": 1,
            "task_id": "test-task-id",
            "image_urls": [],
            "errors": [],
        }

        assert state["raw_input"] == "测试题目内容"
        assert state["user_id"] == 1

    def test_question_intake_state(self):
        """Test QuestionIntakeState"""
        from app.agents.state import QuestionIntakeState

        state: QuestionIntakeState = {
            "raw_input": "测试题目",
            "user_id": 1,
            "task_id": "test-task",
            "errors": [],
            "parse_attempts": 0,
            "parse_success": False,
        }

        assert state["parse_attempts"] == 0
        assert state["parse_success"] is False


class TestAgentPrompts:
    """Test agent prompts"""

    def test_get_error_analysis_prompt(self):
        """Test getting subject-specific prompt"""
        from app.agents.prompts import get_error_analysis_prompt

        math_prompt = get_error_analysis_prompt("math")
        assert "数学" in math_prompt or "计算" in math_prompt

        physics_prompt = get_error_analysis_prompt("physics")
        assert "物理" in physics_prompt or "情境" in physics_prompt

        # Test fallback to general prompt
        other_prompt = get_error_analysis_prompt("unknown")
        assert other_prompt is not None

    def test_get_subject_name_cn(self):
        """Test getting Chinese subject name"""
        from app.agents.prompts import get_subject_name_cn

        assert get_subject_name_cn("math") == "数学"
        assert get_subject_name_cn("physics") == "物理"
        assert get_subject_name_cn("english") == "英语"
        assert get_subject_name_cn("unknown") == "综合"


class TestQuestionIntakeAgent:
    """Test QuestionIntakeAgent"""

    def test_create_intake_graph(self):
        """Test creating intake graph"""
        from app.agents.question_intake_agent import create_intake_graph

        graph = create_intake_graph()
        assert graph is not None

    @pytest.mark.asyncio
    async def test_intake_agent_process(self):
        """Test QuestionIntakeAgent process method"""
        from app.agents.question_intake_agent import QuestionIntakeAgent

        agent = QuestionIntakeAgent()
        assert agent.graph is not None


class TestSimilarQuestionAgent:
    """Test SimilarQuestionAgent"""

    def test_create_similar_question_graph(self):
        """Test creating similar question graph"""
        from app.agents.similar_question_agent import create_similar_question_graph

        graph = create_similar_question_graph()
        assert graph is not None


class TestOCRAgent:
    """Test OCRAgent"""

    def test_create_ocr_graph(self):
        """Test creating OCR agent graph"""
        from app.agents.ocr_agent import create_ocr_agent_graph

        graph = create_ocr_agent_graph()
        assert graph is not None

    def test_get_ocr_graph_singleton(self):
        """Test that get_ocr_graph returns singleton"""
        from app.agents.ocr_agent import get_ocr_graph

        graph1 = get_ocr_graph()
        graph2 = get_ocr_graph()
        assert graph1 is graph2


class TestAgentTasks:
    """Test Celery tasks"""

    def test_tasks_import(self):
        """Test that tasks can be imported"""
        from app.agents.tasks import (
            process_question_task,
            find_similar_questions_task,
            ocr_exam_task,
            reanalyze_question_task,
        )

        assert process_question_task is not None
        assert find_similar_questions_task is not None
        assert ocr_exam_task is not None
        assert reanalyze_question_task is not None
