"""
Graph store (file-based) for GraphRAG.

We keep the format simple (JSON) so it can be inspected/edited by students.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
import json
from pathlib import Path
from datetime import datetime, timezone


@dataclass(frozen=True)
class GraphNode:
    id: str
    type: str
    label: str = ""
    props: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GraphEdge:
    src: str
    dst: str
    type: str
    props: Dict[str, Any] = field(default_factory=dict)


class GraphStore:
    """
    In-memory graph with JSON persistence.

    Provides quick adjacency lookups for GraphRAG expansion.
    """

    def __init__(self, *, module_name: str):
        self.module_name = module_name
        self.nodes: Dict[str, GraphNode] = {}
        self.edges: List[GraphEdge] = []
        self._out: Dict[str, List[GraphEdge]] = {}
        self._in: Dict[str, List[GraphEdge]] = {}

    def add_node(self, node: GraphNode) -> None:
        self.nodes[node.id] = node

    def add_edge(self, edge: GraphEdge) -> None:
        self.edges.append(edge)
        self._out.setdefault(edge.src, []).append(edge)
        self._in.setdefault(edge.dst, []).append(edge)

    def out_edges(self, node_id: str, *, edge_type: Optional[str] = None) -> List[GraphEdge]:
        edges = self._out.get(node_id, [])
        if edge_type is None:
            return list(edges)
        return [e for e in edges if e.type == edge_type]

    def in_edges(self, node_id: str, *, edge_type: Optional[str] = None) -> List[GraphEdge]:
        edges = self._in.get(node_id, [])
        if edge_type is None:
            return list(edges)
        return [e for e in edges if e.type == edge_type]

    def neighbors(
        self,
        node_id: str,
        *,
        out_edge_type: Optional[str] = None,
        in_edge_type: Optional[str] = None,
    ) -> Set[str]:
        out_n = {e.dst for e in self.out_edges(node_id, edge_type=out_edge_type)}
        in_n = {e.src for e in self.in_edges(node_id, edge_type=in_edge_type)}
        return out_n | in_n

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": 1,
            "module": self.module_name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "nodes": [
                {"id": n.id, "type": n.type, "label": n.label, "props": n.props}
                for n in self.nodes.values()
            ],
            "edges": [
                {"src": e.src, "dst": e.dst, "type": e.type, "props": e.props}
                for e in self.edges
            ],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GraphStore":
        module = data.get("module") or "unknown"
        gs = cls(module_name=module)
        for nd in data.get("nodes", []):
            gs.add_node(
                GraphNode(
                    id=str(nd["id"]),
                    type=str(nd.get("type", "")),
                    label=str(nd.get("label", "")),
                    props=dict(nd.get("props", {}) or {}),
                )
            )
        for ed in data.get("edges", []):
            gs.add_edge(
                GraphEdge(
                    src=str(ed["src"]),
                    dst=str(ed["dst"]),
                    type=str(ed.get("type", "")),
                    props=dict(ed.get("props", {}) or {}),
                )
            )
        return gs

    def save_json(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load_json(cls, path: str | Path) -> "GraphStore":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)

