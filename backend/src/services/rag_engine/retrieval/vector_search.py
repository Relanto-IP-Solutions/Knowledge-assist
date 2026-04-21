"""pgvector-based nearest-neighbor retrieval (replaces Vertex AI Vector Search).

Queries the chunk_registry table in PostgreSQL using the <=> cosine distance
operator provided by the pgvector extension.

The output list format is identical to the previous Vertex AI implementation
so that the downstream reranker and LLM prompt builder require no changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.services.database_manager.connection import get_db_connection
from src.utils.logger import get_logger


logger = get_logger(__name__)


def _infer_source_type_from_datapoint_id(datapoint_id: str) -> str:
    """Infer source type from datapoint_id prefix set during ingestion."""
    if "_slack_" in datapoint_id:
        return "slack_messages"
    if "_zoom_" in datapoint_id:
        return "zoom_transcript"
    return "gdrive_doc"


def retrieve_topk_from_combined_source(
    query_embedding: list[float],
    opportunity_id: str,
    token: str,  # Kept for API compatibility — not used with pgvector
    top_k: int,
) -> list[dict[str, Any]]:
    """Query the chunk_registry using pgvector for semantic nearest-neighbor search.

    Replaces the Vertex AI findNeighbors HTTP call.
    Returns an empty list if no chunks are found for the opportunity.

    Returns:
        List of dicts with keys: source_name, source_type, source_rank,
        distance, datapoint_id, text, restricts.
    """
    logger.debug(
        "retrieve_topk_from_combined_source (pgvector): opportunity_id=%s top_k=%d",
        opportunity_id,
        top_k,
    )
    # If pgvector adapter wasn't registered, convert list to string manually
    pg_embedding = query_embedding
    if isinstance(pg_embedding, list):
        pg_embedding = "[" + ",".join(map(str, pg_embedding)) + "]"

    con = get_db_connection()
    try:
        cur = con.cursor()
        # Retrieve top_k * 3 candidates from all source types so per-source
        # capping logic (replicated from the old combined-source reader) still works.
        cur.execute(
            """
            SELECT
                cr.datapoint_id,
                cr.chunk_text,
                dr.gcs_path,
                COALESCE(dr.document_id, cr.document_id) AS logical_document_id,
                1 - (cr.embedding <=> %s::vector) AS similarity_score
            FROM chunk_registry cr
            LEFT JOIN document_registry dr ON dr.document_id = cr.document_id
            WHERE cr.opportunity_id = %s
              AND cr.embedding IS NOT NULL
            ORDER BY cr.embedding <=> %s::vector
            LIMIT %s
            """,
            (pg_embedding, opportunity_id, pg_embedding, top_k * 3),
        )
        rows = cur.fetchall()
    finally:
        con.close()

    if not rows:
        logger.warning(
            "retrieve_topk_from_combined_source: no chunks found for opportunity_id=%s",
            opportunity_id,
        )
        return []

    results: list[dict[str, Any]] = []
    per_source_count: dict[str, int] = {}

    for rank, row in enumerate(rows, start=1):
        datapoint_id, chunk_text, gcs_path, logical_document_id, similarity_score = row
        source_type = _infer_source_type_from_datapoint_id(datapoint_id or "")
        if per_source_count.get(source_type, 0) >= top_k:
            continue
        per_source_count[source_type] = per_source_count.get(source_type, 0) + 1
        gcs_path = (gcs_path or "").strip()
        doc_id = (logical_document_id or "").strip()
        # Match Vertex-style restricts so build_answer_items() fills source + document_id.
        basename = (
            Path(gcs_path).name
            if gcs_path
            else (doc_id.split(":")[-1] if doc_id else "unknown_source")
        )
        doc_path_for_api = gcs_path or doc_id
        results.append({
            "source_name": "combined",
            "source_type": source_type,
            "source_rank": rank,
            "distance": 1.0
            - float(similarity_score),  # Convert similarity back to distance
            "datapoint_id": datapoint_id,
            "text": (chunk_text or "").strip(),
            "restricts": {
                "opportunity_id": [opportunity_id],
                "source_id": [basename],
                "document_id": [doc_path_for_api] if doc_path_for_api else [],
            },
        })

    logger.debug(
        "retrieve_topk_from_combined_source: %d candidates returned "
        "(gdrive_doc=%d, slack_messages=%d, zoom_transcript=%d)",
        len(results),
        per_source_count.get("gdrive_doc", 0),
        per_source_count.get("slack_messages", 0),
        per_source_count.get("zoom_transcript", 0),
    )
    return results
