"""Vertex AI Discovery Engine reranking for retrieval candidates."""

from __future__ import annotations

from typing import Any

from configs.settings import get_settings
from src.services.rag_engine.retrieval.http_client import get_http_session
from src.utils.logger import get_logger
from src.utils.retry import retry_on_transient


logger = get_logger(__name__)

_reranker: Reranker | None = None


class Reranker:
    """Rerank retrieval candidates using Vertex AI Discovery Engine ranking API."""

    @retry_on_transient()
    def rank(
        self,
        query: str,
        candidates: list[dict[str, Any]],
        token: str,
        keep: int,
    ) -> list[dict[str, Any]]:
        """Rerank candidates using Vertex AI Discovery Engine ranking API.

        Retries on transient errors (429, 502, 503, timeouts, connection errors).
        """
        candidates = [c for c in candidates if (c.get("text") or "").strip()]
        if not candidates:
            logger.debug("vertex_rank: no valid candidates, returning []")
            return []
        logger.debug(
            "vertex_rank: query len=%d, candidates=%d, keep=%d",
            len(query),
            len(candidates),
            keep,
        )
        records = [
            {"id": str(c["datapoint_id"]), "content": c["text"]} for c in candidates
        ]
        settings = get_settings().retrieval
        project_id = settings.gcp_project_id or get_settings().ingestion.gcp_project_id
        endpoint = (
            f"https://{settings.rank_location}-discoveryengine.googleapis.com/v1/"
            f"projects/{project_id}/locations/{settings.rank_location}/"
            f"rankingConfigs/{settings.ranking_config_id}:rank"
        )
        payload = {
            "model": settings.rank_model,
            "query": query,
            "records": records,
            "topN": min(keep, len(records)),
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        resp = get_http_session().post(
            endpoint, headers=headers, json=payload, timeout=60
        )
        resp.raise_for_status()
        data = resp.json()
        score_by_id: dict[str, float] = {}
        for r in data.get("records", []) or []:
            rid = r.get("id")
            sc = r.get("score")
            if rid is not None and sc is not None:
                score_by_id[str(rid)] = float(sc)
        for c in candidates:
            c["rerank_score"] = score_by_id.get(str(c["datapoint_id"]), -1e9)
        ranked = sorted(candidates, key=lambda x: x["rerank_score"], reverse=True)
        result = ranked[:keep]
        logger.debug("vertex_rank: returned top {} of {}", len(result), len(ranked))
        return result


def get_reranker() -> Reranker:
    """Return the singleton Reranker instance."""
    global _reranker
    if _reranker is None:
        _reranker = Reranker()
    return _reranker


def vertex_rank(
    query: str,
    candidates: list[dict[str, Any]],
    token: str,
    keep: int,
) -> list[dict[str, Any]]:
    """Rerank candidates using Vertex AI Discovery Engine ranking API."""
    return get_reranker().rank(query, candidates, token, keep)
