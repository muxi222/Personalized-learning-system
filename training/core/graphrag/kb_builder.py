"""
GraphRAG KB builder (core).

This builder is intentionally "structure-first":
- Prefer structured DB fields (subject/chapter/knowledge_points/tags/upload_group_id/...)
- Avoid brittle NLP entity extraction in the first iteration
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from pathlib import Path
import json
import sqlite3

from .graph_store import GraphStore, GraphNode, GraphEdge


@dataclass
class QuestionRecord:
    id: int
    user_id: int
    subject: str
    content: str
    title: str = ""
    chapter: str = ""
    knowledge_points: List[str] = None  # type: ignore[assignment]
    tags: List[str] = None  # type: ignore[assignment]
    difficulty: str = ""
    error_analysis: str = ""
    explanation: str = ""
    upload_group_id: str = ""
    upload_index: Optional[int] = None

    def __post_init__(self):
        if self.knowledge_points is None:
            self.knowledge_points = []
        if self.tags is None:
            self.tags = []


def _json_list(val: Any) -> List[str]:
    if val is None:
        return []
    if isinstance(val, list):
        return [str(x) for x in val if str(x).strip()]
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return []
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                return [str(x) for x in parsed if str(x).strip()]
        except Exception:
            return [s]
    return []


def load_questions_from_sqlite(
    *,
    sqlite_path: str | Path,
    subjects: Sequence[str],
    limit: Optional[int] = None,
) -> List[QuestionRecord]:
    """
    Load question records from the app SQLite DB.

    We query the `questions` table directly (no ORM dependency in training scripts).
    """
    sqlite_path = Path(sqlite_path)
    if not sqlite_path.exists():
        raise FileNotFoundError(f"SQLite DB not found: {sqlite_path}")

    subj_vals: List[str] = []
    for s in subjects:
        s = str(s).strip()
        if not s:
            continue
        subj_vals.append(s)
        subj_vals.append(s.upper())
    # De-dup while keeping order
    seen = set()
    subj_vals = [x for x in subj_vals if not (x in seen or seen.add(x))]

    where = f"subject IN ({', '.join(['?'] * len(subj_vals))})" if subj_vals else "1=1"
    sql = f"""
    SELECT
      id,
      user_id,
      subject,
      content,
      COALESCE(title, '') AS title,
      COALESCE(chapter, '') AS chapter,
      COALESCE(knowledge_points, '[]') AS knowledge_points,
      COALESCE(tags, '[]') AS tags,
      COALESCE(difficulty, '') AS difficulty,
      COALESCE(error_analysis, '') AS error_analysis,
      COALESCE(explanation, '') AS explanation,
      COALESCE(upload_group_id, '') AS upload_group_id,
      upload_index
    FROM questions
    WHERE ({where})
    ORDER BY created_at DESC, id DESC
    """
    if limit:
        sql += f" LIMIT {int(limit)}"

    conn = sqlite3.connect(str(sqlite_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(sql, subj_vals).fetchall()
        out: List[QuestionRecord] = []
        for r in rows:
            out.append(
                QuestionRecord(
                    id=int(r["id"]),
                    user_id=int(r["user_id"]),
                    subject=str(r["subject"] or "other").lower(),
                    content=str(r["content"] or ""),
                    title=str(r["title"] or ""),
                    chapter=str(r["chapter"] or ""),
                    knowledge_points=_json_list(r["knowledge_points"]),
                    tags=_json_list(r["tags"]),
                    difficulty=str(r["difficulty"] or ""),
                    error_analysis=str(r["error_analysis"] or ""),
                    explanation=str(r["explanation"] or ""),
                    upload_group_id=str(r["upload_group_id"] or ""),
                    upload_index=(int(r["upload_index"]) if r["upload_index"] is not None else None),
                )
            )
        return out
    finally:
        conn.close()


def build_graph_for_questions(
    *,
    module_name: str,
    questions: Sequence[QuestionRecord],
) -> GraphStore:
    """
    Build a graph where:
    - Question nodes connect to knowledge point / tag / chapter / upload group nodes.
    """
    g = GraphStore(module_name=module_name)

    for q in questions:
        qn = GraphNode(
            id=f"q:{q.id}",
            type="question",
            label=(q.title or q.content[:30]).strip(),
            props={
                "question_id": q.id,
                "user_id": q.user_id,
                "subject": q.subject,
                "difficulty": q.difficulty,
                "chapter": q.chapter,
                "knowledge_points": q.knowledge_points,
                "tags": q.tags,
                "upload_group_id": q.upload_group_id,
                "upload_index": q.upload_index,
            },
        )
        g.add_node(qn)

        if q.chapter:
            ch_id = f"ch:{q.subject}:{q.chapter}"
            if ch_id not in g.nodes:
                g.add_node(GraphNode(id=ch_id, type="chapter", label=q.chapter, props={"subject": q.subject}))
            g.add_edge(GraphEdge(src=qn.id, dst=ch_id, type="IN_CHAPTER"))

        for kp in q.knowledge_points:
            kp_clean = str(kp).strip()
            if not kp_clean:
                continue
            kp_id = f"kp:{q.subject}:{kp_clean}"
            if kp_id not in g.nodes:
                g.add_node(GraphNode(id=kp_id, type="knowledge_point", label=kp_clean, props={"subject": q.subject}))
            g.add_edge(GraphEdge(src=qn.id, dst=kp_id, type="HAS_KP"))

        for t in q.tags:
            t_clean = str(t).strip()
            if not t_clean:
                continue
            tag_id = f"tag:{t_clean}"
            if tag_id not in g.nodes:
                g.add_node(GraphNode(id=tag_id, type="tag", label=t_clean))
            g.add_edge(GraphEdge(src=qn.id, dst=tag_id, type="HAS_TAG"))

        if q.upload_group_id:
            ug_id = f"upload:{q.upload_group_id}"
            if ug_id not in g.nodes:
                g.add_node(GraphNode(id=ug_id, type="upload_group", label=q.upload_group_id))
            g.add_edge(GraphEdge(src=qn.id, dst=ug_id, type="IN_UPLOAD_GROUP", props={"upload_index": q.upload_index}))

    return g


def build_kb_artifacts(
    *,
    module_name: str,
    sqlite_path: str | Path,
    subjects: Sequence[str],
    output_dir: str | Path,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Build only the *graph* artifacts (GraphRAG layer).

    The hybrid retriever index (FAISS/BM25) is built by `build_hybrid_index(...)`
    to keep dependencies optional (faiss/rank_bm25).
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    questions = load_questions_from_sqlite(sqlite_path=sqlite_path, subjects=subjects, limit=limit)
    graph = build_graph_for_questions(module_name=module_name, questions=questions)
    graph_path = output_dir / "graph.json"
    graph.save_json(graph_path)

    return {
        "module": module_name,
        "subjects": list(subjects),
        "sqlite_path": str(sqlite_path),
        "output_dir": str(output_dir),
        "graph_path": str(graph_path),
        "question_count": len(questions),
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
    }

