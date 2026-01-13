"""
RPJ Retrieval MCP Server (TODO / stub)

Mirror of `backend/mcp_servers/tony/retrieval_server.py`.

TODO:
- Implement hybrid retrieval (FAISS+BM25) using RPJ module index paths:
  - data/faiss/rpj
  - data/bm25/rpj
- Optionally support GraphRAG expansion when GRAPHRAG_ENABLED=true and graph exists at:
  - data/training/rpj/graphrag/graph.json

Expected tools (design):
- search_questions(query_text, user_id, subject?, knowledge_points?, tags?, include_graphrag?, top_k, ...)
- get_questions(question_ids, user_id)
- get_task(task_id)  # optional (ops starter)
- health()
"""

# TODO: implement using mcp.server.fastmcp.FastMCP

