"""
training.core.graphrag

Lightweight "GraphRAG" implementation for this repo:
- Build a knowledge graph from structured DB fields (knowledge_points/tags/chapter/etc.)
- Build a hybrid retriever index (FAISS + BM25) compatible with backend runtime
- Query: vector/BM25 retrieve seed question nodes, then expand via graph neighbors

Note:
This is intentionally dependency-light and uses file-based artifacts under `data/`.
"""

