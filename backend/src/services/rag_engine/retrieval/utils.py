"""Retrieval helpers and output shaping."""

from __future__ import annotations

from typing import Any

from src.utils.logger import get_logger


logger = get_logger(__name__)


def restricts_to_dict(restricts: Any) -> dict[str, list[str]]:
    """Normalize restricts into {namespace: [values]}.

    Vector Search full datapoint returns restricts like:
      [{"namespace":"source_id","allowList":["..."]}, ...]
    Ingestion used allow_list, so some payloads can show allow_list.
    """
    out: dict[str, list[str]] = {}
    if not restricts:
        return out
    for r in restricts:
        ns = r.get("namespace")
        allow = r.get("allowList") or r.get("allow_list") or []
        if ns:
            out[ns] = [str(x) for x in allow]
    return out


def first_or_none(vals: list[str] | None) -> str | None:
    if not vals:
        return None
    v = vals[0]
    return str(v) if v is not None else None


def distance_to_similarity(distance: float | None) -> float | None:
    """Convert Vector Search distance to a similarity score.

    Empirically, the index returns distances >= 0 where:
      - smaller distance  → more similar
      - larger distance   → less similar

    We map: similarity = 1.0 - distance
    so that higher similarity means a better match. Scores can be negative
    when distance > 1.0.
    """
    if distance is None:
        return None
    try:
        d = float(distance)
    except (TypeError, ValueError):
        return None
    return 1.0 - d


def filter_candidates_by_similarity(
    candidates: list[dict[str, Any]],
    min_similarity: float,
) -> list[dict[str, Any]]:
    """Keep only candidates whose similarity (from distance) is >= min_similarity.

    Used before reranker to avoid sending low-similarity chunks. With default
    min_similarity=0.0 this returns all candidates unchanged.
    """
    if min_similarity <= 0.0:
        return candidates
    result = []
    for c in candidates:
        sim = distance_to_similarity(c.get("distance"))
        if (sim if sim is not None else 0.0) >= min_similarity:
            result.append(c)
    return result


def infer_source_type(source_name: str) -> str:
    if source_name == "zoom":
        return "zoom_transcript"
    if source_name == "drive":
        return "gdrive_doc"
    if source_name == "onedrive":
        return "onedrive_doc"
    if source_name == "slack":
        return "slack_messages"
    return source_name


def build_answer_items(topk: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map reranked candidates to answer format for answer-generation pipeline."""
    logger.debug("build_answer_items: input topk len={}", len(topk))
    items: list[dict[str, Any]] = []
    for c in topk:
        restricts_map: dict[str, list[str]] = c.get("restricts") or {}
        source_id = first_or_none(restricts_map.get("source_id")) or "unknown_source"
        document_id = first_or_none(restricts_map.get("document_id"))
        chunk_id = c.get("datapoint_id")
        sim = distance_to_similarity(c.get("distance"))
        items.append({
            "text": c.get("text") or "",
            "source": source_id,
            "source_type": c.get("source_type") or "unknown",
            "similarity_score": sim if sim is not None else 0.0,
            "document_id": document_id,
            "chunk_id": chunk_id,
            "rerank_score": c.get("rerank_score"),
        })
    result = [it for it in items if (it.get("text") or "").strip()]
    logger.debug(
        "build_answer_items: output len=%d (after dropping empty text)", len(result)
    )
    return result
