"""
DEFAULT Ops MCP Server (TODO / stub)

Intended responsibilities (cross-subject ops):
- get_task(task_id): aggregate/locate task across modules (shared DB table agent_tasks)
- tail_task_events(task_id): stream updates (SSE-like) for observability dashboards
- summarize_failure(task_id): structured failure reasons and next actions

Expected tools (design):
- get_task(task_id)
- health()
"""

# TODO: implement using mcp.server.fastmcp.FastMCP

