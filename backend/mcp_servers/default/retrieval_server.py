"""
DEFAULT Retrieval MCP Server (TODO / stub)

This is a placeholder to mirror Tony's retrieval-mcp structure.

Intended responsibilities (cross-subject):
- search_questions across ALL modules (or via default module routing), then merge/rerank
- explain retrieval with evidence (per-module source + scores)
- fetch question details by id (must route to correct module or use shared DB)

Expected tools (design):
- search_questions(query_text, user_id, subject?, knowledge_points?, tags?, include_graphrag?, top_k, ...)
- get_questions(question_ids, user_id)
- health()

Implementation notes:
- Indices are per module: data/faiss/<module>, data/bm25/<module>
- Default module currently proxies HTTP, but MCP should unify the tool interface.
"""

# TODO: implement using mcp.server.fastmcp.FastMCP

