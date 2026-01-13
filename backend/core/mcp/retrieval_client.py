"""
Retrieval MCP Client (Phase 1)

This wraps MCP calls to the retrieval server and provides:
- typed-ish helper methods
- latency/success metrics hooks (wired via metrics_service when available)

Transport:
- Streamable HTTP (recommended for long-lived services)
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client


@dataclass(frozen=True)
class RetrievalSearchResult:
    question_id: int
    score: float
    source: str
    metadata: Dict[str, Any]
    document: str


class RetrievalMcpClient:
    def __init__(self, *, url: str):
        self._url = url

    async def search_questions(
        self,
        *,
        query_text: str,
        user_id: int,
        subject: Optional[str] = None,
        knowledge_points: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        top_k: int = 5,
        exclude_question_ids: Optional[List[int]] = None,
        include_graphrag: bool = False,
        graphrag_k: int = 20,
        vector_weight: Optional[float] = None,
        bm25_weight: Optional[float] = None,
        similarity_threshold: Optional[float] = None,
        telemetry: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Call MCP tool: search_questions

        Returns dict:
        - results: List[RetrievalSearchResult as dict]
        - debug: dict
        - error: optional str
        """
        t0 = time.perf_counter()
        ok = False
        err: Optional[str] = None
        payload: Dict[str, Any] = {
            "query_text": query_text,
            "user_id": int(user_id),
            "subject": subject,
            "knowledge_points": list(knowledge_points or []),
            "tags": list(tags or []),
            "top_k": int(top_k),
            "exclude_question_ids": exclude_question_ids or [],
            "include_graphrag": bool(include_graphrag),
            "graphrag_k": int(graphrag_k),
            "vector_weight": vector_weight,
            "bm25_weight": bm25_weight,
            "similarity_threshold": similarity_threshold,
        }
        try:
            async with streamable_http_client(self._url) as (read, write, _get_session_id):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    res = await session.call_tool("search_questions", payload)
                    # FastMCP returns json_response=True, so content is JSON-serializable
                    out = res.content[0].text if res.content else "{}"
                    # But content is in MCP TextContent. Try to parse best-effort.
                    import json

                    data = json.loads(out) if isinstance(out, str) else (out or {})
                    ok = True
                    return data
        except Exception as e:
            err = str(e)
            return {"results": [], "error": err, "debug": {"t_total_ms": (time.perf_counter() - t0) * 1000.0}}
        finally:
            # Best-effort telemetry hook; implemented for tony via metrics_service.
            try:
                if telemetry and isinstance(telemetry, dict):
                    telemetry["ok"] = ok
                    telemetry["error"] = err
                    telemetry["t_ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
                    telemetry["tool"] = "retrieval.search_questions"
                    from backend.core.services.metrics_service import get_metrics_service

                    await get_metrics_service().log_tool_call(**telemetry)
            except Exception:
                # Never break main logic due to telemetry.
                pass

    async def get_questions(
        self,
        *,
        question_ids: List[int],
        user_id: int,
        telemetry: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Call MCP tool: get_questions."""
        t0 = time.perf_counter()
        ok = False
        err: Optional[str] = None
        try:
            async with streamable_http_client(self._url) as (read, write, _get_session_id):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    res = await session.call_tool(
                        "get_questions",
                        {"question_ids": [int(x) for x in question_ids], "user_id": int(user_id)},
                    )
                    import json

                    out = res.content[0].text if res.content else "[]"
                    data = json.loads(out) if isinstance(out, str) else (out or [])
                    ok = True
                    return data
        except Exception as e:
            err = str(e)
            return []
        finally:
            try:
                if telemetry and isinstance(telemetry, dict):
                    telemetry["ok"] = ok
                    telemetry["error"] = err
                    telemetry["t_ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
                    telemetry["tool"] = "retrieval.get_questions"
                    from backend.core.services.metrics_service import get_metrics_service

                    await get_metrics_service().log_tool_call(**telemetry)
            except Exception:
                pass


