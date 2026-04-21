"""Document vector upsert payloads (restricts + embedding_metadata) for RAG."""

from __future__ import annotations


def safe_string_for_datapoint_id(value: str) -> str:
    """Normalize string for use in datapoint IDs (no spaces, parens, etc.)."""
    s = (
        str(value)
        .replace(" ", "_")
        .replace("(", "")
        .replace(")", "")
        .replace(".", "_")
        .replace("-", "_")
    )
    return s


def build_document_datapoints_for_upsert(
    chunk_texts: list[str],
    opportunity_id: str,
    channel: str,
    source_id: str,
    document_id: str,
    object_name: str,
    safe_string: callable | None = None,
) -> list[dict]:
    """Build datapoint dicts for documents (Vertex: text, datapoint_id, restricts, embedding_metadata)."""
    safe = safe_string or safe_string_for_datapoint_id
    effective_doc_id = document_id or f"{opportunity_id}:documents:{object_name}"
    safe_doc_id = safe(effective_doc_id)
    safe_id = safe(source_id)
    datapoints = []
    for idx, text in enumerate(chunk_texts):
        chunk_id = f"{safe_id}_{idx}"
        datapoints.append({
            "text": text,
            "chunk_id": chunk_id,
            "datapoint_id": f"{safe_doc_id}__{idx}",
            "restricts": [
                {"namespace": "opportunity_id", "allow_list": [opportunity_id]},
                {"namespace": "channel", "allow_list": [channel]},
                {"namespace": "source_id", "allow_list": [source_id]},
                {"namespace": "document_id", "allow_list": [effective_doc_id]},
            ],
            "embedding_metadata": {
                "text": text,
                "chunk_index": idx,
                "opportunity_id": opportunity_id,
            },
        })
    return datapoints
