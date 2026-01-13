"""
TONY Ops MCP Server (Phase 2 skeleton)

This is a minimal starting point for ops-mcp:
- query task status
- future: summarize failures, tail task events, replay dry-runs, etc.
"""

from __future__ import annotations

from typing import Any, Dict

from mcp.server.fastmcp import FastMCP


mcp = FastMCP(
    name="learning-assistant-tony-ops",
    instructions="Ops/observability tools for the TONY module.",
    host="127.0.0.1",
    port=7020,
    streamable_http_path="/mcp",
    json_response=True,
    log_level="INFO",
)


@mcp.tool()
async def get_task(task_id: str) -> Dict[str, Any]:
    from backend.core.db.session import async_session_maker
    from backend.core.crud.crud_task import get_task_by_task_id

    async with async_session_maker() as session:
        task = await get_task_by_task_id(session, task_id)
        if not task:
            return {"error": "Task not found", "task_id": task_id}
        return {
            "task_id": task.task_id,
            "status": task.status.value if getattr(task, "status", None) else None,
            "progress": float(task.progress or 0.0),
            "current_step": task.current_step,
            "error_message": task.error_message,
            "result": task.result,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        }


@mcp.tool()
async def health() -> Dict[str, Any]:
    return {"module": "tony", "server": "ops", "ok": True}


def main() -> None:
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()

"""Phase 2 ops-mcp (skeleton)."""

"""
TONY Ops MCP Server (Phase 2 skeleton)

Roadmap Phase 2: ops-mcp
- unify task observability and diagnostics for agents
- expose tools for querying tasks, summarizing failures, etc.

This file is intentionally minimal for now; extend as needed.
"""

from __future__ import annotations

from typing import Any, Dict

from mcp.server.fastmcp import FastMCP


mcp = FastMCP(
    name="learning-assistant-tony-ops",
    instructions="Ops/observability tools for the TONY module.",
    host="127.0.0.1",
    port=7020,
    streamable_http_path="/mcp",
    json_response=True,
    log_level="INFO",
)


@mcp.tool()
async def get_task(task_id: str) -> Dict[str, Any]:
    """
    Get a task snapshot by task_id.

    Maps to:
    - backend.core.db.models.AgentTask
    - backend.core.crud.crud_task.get_task_by_task_id
    """
    from backend.core.db.session import async_session_maker
    from backend.core.crud.crud_task import get_task_by_task_id

    async with async_session_maker() as session:
        task = await get_task_by_task_id(session, task_id)
        if not task:
            return {"error": "Task not found", "task_id": task_id}
        result = task.result if isinstance(task.result, dict) else task.result
        return {
            "task_id": task.task_id,
            "status": task.status.value if getattr(task, "status", None) else None,
            "progress": float(task.progress or 0.0),
            "current_step": task.current_step,
            "error_message": task.error_message,
            "result": result,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        }


@mcp.tool()
async def health() -> Dict[str, Any]:
    return {"module": "tony", "server": "ops", "ok": True}


def main() -> None:
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()

