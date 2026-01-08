from __future__ import annotations

from typing import Any, Dict, Iterable, Iterator, Optional
from pathlib import Path
import json


def write_jsonl(path: str | Path, rows: Iterable[Dict[str, Any]]) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            n += 1
    return n


def iter_jsonl(path: str | Path) -> Iterator[Dict[str, Any]]:
    path = Path(path)
    if not path.exists():
        return
    with open(path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            s = line.strip()
            if not s:
                continue
            try:
                obj = json.loads(s)
            except Exception as e:
                raise ValueError(f"Invalid JSONL at {path}:{i}: {e}") from e
            if isinstance(obj, dict):
                yield obj


def read_jsonl(path: str | Path) -> list[Dict[str, Any]]:
    return list(iter_jsonl(path))


def safe_text(s: Any, *, max_len: Optional[int] = None) -> str:
    if s is None:
        return ""
    out = str(s).strip()
    if max_len is not None and max_len > 0:
        out = out[:max_len]
    return out

