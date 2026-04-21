"""Database row operations and utilities."""

from __future__ import annotations

from typing import Any


def rows_to_dicts(cursor: Any, rows: list[Any]) -> list[dict[str, Any]]:
    """Convert DB rows to list of dicts for pg8000 (Cloud SQL connector)."""
    if not rows:
        return []
    if hasattr(rows[0], "keys"):  # already dict-like (e.g. RealDictRow)
        return [dict(r) for r in rows]
    desc = cursor.description
    if not desc:
        return []
    cols = [d[0] for d in desc]
    return [dict(zip(cols, row, strict=False)) for row in rows]
