"""
DEFAULT module MCP servers (TODO).

Default module is cross-subject aggregation. MCP servers here are intended to expose
cross-subject tools (e.g., global search, analytics, routing) without leaking per-module ports.

TODO:
- Implement retrieval-mcp for cross-subject search (fan-out / merge across module indices)
- Implement ops-mcp for cross-module task aggregation and diagnostics
"""

