"""
GraphRAG Service (runtime)

Loads a lightweight knowledge graph built by training scripts:
- default path: `./data/training/<module>/graphrag/graph.json`

Used to:
- expand retrieval results via graph neighbors (knowledge points / tags / chapters)
- aggregate weak points / hot topics

This service is feature-gated by `GRAPHRAG_ENABLED` and is a no-op otherwise.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from ..base_config import get_base_settings
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Edge:
    src: str
    dst: str
    type: str


class GraphRAGService:
    def __init__(self):
        self._loaded = False
        self._nodes: Dict[str, Dict[str, Any]] = {}
        self._out: Dict[str, List[_Edge]] = {}
        self._in: Dict[str, List[_Edge]] = {}

    @property
    def enabled(self) -> bool:
        settings = get_base_settings()
        return bool(getattr(settings, "GRAPHRAG_ENABLED", False))

    @property
    def graph_path(self) -> str:
        settings = get_base_settings()
        return str(getattr(settings, "module_graphrag_graph_path", "./data/training/base/graphrag/graph.json"))

    async def initialize(self, *, graph_path: Optional[str] = None) -> bool:
        if self._loaded:
            return True
        if not self.enabled:
            return False

        path = Path(graph_path or self.graph_path)
        if not path.exists():
            logger.warning(f"GraphRAG graph not found: {path} (build it via training script)")
            return False

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._load_from_dict(data)
            self._loaded = True
            logger.info(f"GraphRAG loaded: nodes={len(self._nodes)} edges={sum(len(v) for v in self._out.values())} path={path}")
            return True
        except Exception as e:
            logger.error(f"Failed to load GraphRAG graph: {e}")
            return False

    def _load_from_dict(self, data: Dict[str, Any]) -> None:
        self._nodes = {str(n["id"]): n for n in data.get("nodes", []) if "id" in n}
        self._out = {}
        self._in = {}
        for e in data.get("edges", []):
            try:
                edge = _Edge(src=str(e["src"]), dst=str(e["dst"]), type=str(e.get("type", "")))
            except Exception:
                continue
            self._out.setdefault(edge.src, []).append(edge)
            self._in.setdefault(edge.dst, []).append(edge)

    @staticmethod
    def _norm_subject(subject: str) -> str:
        s = str(subject or "").strip()
        return s.lower() if s else "other"

    @staticmethod
    def _kp_node_id(subject: str, kp: str) -> str:
        return f"kp:{GraphRAGService._norm_subject(subject)}:{str(kp).strip()}"

    @staticmethod
    def _tag_node_id(tag: str) -> str:
        return f"tag:{str(tag).strip()}"

    def _question_id_from_node(self, node_id: str) -> Optional[int]:
        if not node_id.startswith("q:"):
            return None
        try:
            return int(node_id.split(":", 1)[1])
        except Exception:
            return None

    def _questions_in_edges(self, node_id: str, edge_type: str) -> List[int]:
        ids: List[int] = []
        for e in self._in.get(node_id, []):
            if e.type != edge_type:
                continue
            qid = self._question_id_from_node(e.src)
            if qid is not None:
                ids.append(qid)
        return ids

    def find_questions_by_knowledge_points(
        self,
        *,
        subject: str,
        knowledge_points: List[str],
        top_k: int = 20,
        exclude_question_ids: Optional[Set[int]] = None,
    ) -> List[int]:
        """
        Graph expansion:
        kp -> (HAS_KP in-edges) -> question
        """
        exclude = exclude_question_ids or set()
        subj = self._norm_subject(subject)
        out: List[int] = []
        seen: Set[int] = set()

        for kp in (knowledge_points or []):
            kp_clean = str(kp).strip()
            if not kp_clean:
                continue
            nid = f"kp:{subj}:{kp_clean}"
            if nid not in self._nodes:
                continue
            for qid in self._questions_in_edges(nid, "HAS_KP"):
                if qid in exclude or qid in seen:
                    continue
                out.append(qid)
                seen.add(qid)
                if len(out) >= top_k:
                    return out
        return out

    def find_questions_by_tags(
        self,
        *,
        tags: List[str],
        top_k: int = 20,
        exclude_question_ids: Optional[Set[int]] = None,
    ) -> List[int]:
        exclude = exclude_question_ids or set()
        out: List[int] = []
        seen: Set[int] = set()

        for t in (tags or []):
            t_clean = str(t).strip()
            if not t_clean:
                continue
            nid = self._tag_node_id(t_clean)
            if nid not in self._nodes:
                continue
            for qid in self._questions_in_edges(nid, "HAS_TAG"):
                if qid in exclude or qid in seen:
                    continue
                out.append(qid)
                seen.add(qid)
                if len(out) >= top_k:
                    return out
        return out


_svc: Optional[GraphRAGService] = None


@lru_cache()
def get_graphrag_service() -> GraphRAGService:
    global _svc
    if _svc is None:
        _svc = GraphRAGService()
    return _svc

