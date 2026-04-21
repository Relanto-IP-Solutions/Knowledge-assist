"""Ingestion pipeline: consume RAG ingestion events, chunk, embed, and write to PostgreSQL.

Flow: Pub/Sub message → parse data_path/metadata → load content from GCS →
      chunk via rag_engine.ingestion (DocumentsChunker incl. _pre_xlsx_ via PreXlsxDocumentsChunker /
      SlackMessagesChunker / ZoomTranscriptsChunker) →
      embed (Vertex AI text embeddings API) → persist vectors in chunk_registry (pgvector) →
      publish completion to OUTPUT_TOPIC.

Vectors are stored in Cloud SQL (pgvector), not in Vertex AI Vector Search indexes.

Environment (e.g. Cloud Run / Cloud Function): OUTPUT_TOPIC, GCS bucket, DB connector
settings, and GCP credentials for embeddings.
"""

from __future__ import annotations

import hashlib
import os
import time
from datetime import UTC, datetime

from src.services.database_manager.opportunity_state import (
    refresh_opportunity_pipeline_state,
)
from src.services.database_manager.registry import RegistryClient
from src.services.pubsub.publisher import Publisher
from src.services.rag_engine.ingestion import (
    DocumentsChunker,
    SlackMessagesChunker,
    ZoomTranscriptsChunker,
)
from src.services.rag_engine.ingestion.document_datapoints import (
    build_document_datapoints_for_upsert,
    safe_string_for_datapoint_id,
)
from src.services.rag_engine.ingestion.gmail_messages import GmailMessagesChunker
from src.services.rag_engine.retrieval.embedding import embed_texts
from src.services.storage import Storage
from src.utils.logger import get_logger


logger = get_logger(__name__)


def _safe_string(value: str) -> str:
    """Normalize string for use in datapoint IDs (same rules as document datapoints)."""
    return safe_string_for_datapoint_id(value)


def _sha256_hex(content: bytes | str) -> str:
    """Return SHA-256 hash of content as hex string (for doc_hash and chunk_hash)."""
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def _get_ingestion_env() -> dict:
    """Read ingestion config from environment (Cloud Run / CLI)."""
    return {
        "OUTPUT_TOPIC": os.environ.get("OUTPUT_TOPIC", ""),
    }


class IngestionPipeline:
    """Orchestrates RAG ingestion: chunk, embed, write chunk_registry (pgvector), publish completion."""

    def __init__(
        self,
        storage: Storage | None = None,
        registry: RegistryClient | None = None,
    ) -> None:
        self._storage = storage or Storage()
        self._registry = registry or RegistryClient()
        self._documents_chunker = DocumentsChunker(chunk_size=1500, overlap=300)
        self._slack_chunker = SlackMessagesChunker(max_chars_per_chunk=4500)
        self._zoom_chunker = ZoomTranscriptsChunker(window_minutes=3, overlap_minutes=1)
        self._gmail_chunker = GmailMessagesChunker(
            window_size=3, window_overlap=1, max_chars_per_chunk=4000
        )

    def run_message(self, message: dict) -> str | None:
        """Process one RAG ingestion event (e.g. from Pub/Sub push).

        Expected message: source_type, data_path (gs://bucket/...), metadata (opportunity_id, etc.).
        Chunks via rag_engine.ingestion, embeds with Vertex AI, writes to chunk_registry,
        publishes completion to OUTPUT_TOPIC.

        Returns:
            Correlation string (e.g. source_type + chunks count) or None if skipped/failed.
        """
        source_type = message.get("source_type")
        data_path = message.get("data_path", "")
        metadata = message.get("metadata") or {}

        if not data_path or not data_path.startswith("gs://"):
            logger.warning(
                "Message missing or invalid data_path — data_path=%s", data_path
            )
            return None

        # Parse data_path: gs://bucket/opp_id/processed/source/object_name
        parts = data_path.replace("gs://", "").split("/")
        if len(parts) < 5:
            logger.warning("data_path has too few segments — data_path={}", data_path)
            return None
        opportunity_id = metadata.get("opportunity_id") or parts[1]
        source = parts[3] if len(parts) > 3 else ""
        object_name = "/".join(parts[4:]) if len(parts) > 4 else ""
        # Normalize source_type to match our chunkers
        if source_type not in (
            "documents",
            "slack_messages",
            "zoom_transcripts",
            "gmail_messages",
        ):
            logger.bind(opportunity_id=opportunity_id).debug(
                "Unsupported source_type — source_type=%s",
                source_type,
            )
            return None

        env = _get_ingestion_env()
        output_topic = env["OUTPUT_TOPIC"]

        channel = str(metadata.get("channel", ""))
        source_id = str(metadata.get("source_id", ""))
        document_id = str(metadata.get("document_id", ""))

        start_time = time.time()
        logger.bind(opportunity_id=opportunity_id).info(
            "Ingestion pipeline processing — source_type=%s",
            source_type,
        )

        try:
            # Registry/vector cleanup for removed documents is only via document_deleted (rag-ingestion),
            # not by listing processed/documents vs registry on ingest.

            content = self._storage.read(
                "processed", opportunity_id, source, object_name
            )

            # Document-level skip: if doc unchanged, skip chunking/embed/upsert (documents only)
            if source_type == "documents":
                registry_document_id = f"{opportunity_id}:documents:{object_name}"
                doc_hash = _sha256_hex(content)
                existing = self._registry.get_document(registry_document_id)
                if existing and (existing.get("doc_hash") or "").strip() == doc_hash:
                    logger.bind(opportunity_id=opportunity_id).info(
                        "Document unchanged (doc_hash match), skipping ingestion — document_id=%s",
                        registry_document_id,
                    )
                    return f"{source_type}:0"

            if source_type == "documents":
                chunk_texts = self._documents_chunker.extract_and_chunk(
                    content, object_name, opportunity_id
                )
                if not chunk_texts:
                    logger.bind(opportunity_id=opportunity_id).warning(
                        "No document chunks produced"
                    )
                    return None
                datapoints = build_document_datapoints_for_upsert(
                    chunk_texts,
                    opportunity_id,
                    channel,
                    source_id,
                    document_id,
                    object_name,
                    safe_string=_safe_string,
                )
            elif source_type == "slack_messages":
                raw_text = content.decode("utf-8")
                chunks = self._slack_chunker.chunk(raw_text, opportunity_id)
                if not chunks:
                    logger.bind(opportunity_id=opportunity_id).warning(
                        "No Slack chunks produced"
                    )
                    return None
                datapoints, _completion_attr = self._build_slack_datapoints(
                    chunks,
                    opportunity_id,
                    channel,
                    source_id,
                    document_id,
                    _safe_string,
                )
            elif source_type == "zoom_transcripts":
                raw_text = content.decode("utf-8")
                chunks = self._zoom_chunker.chunk(raw_text, opportunity_id)
                if not chunks:
                    logger.bind(opportunity_id=opportunity_id).warning(
                        "No Zoom chunks produced"
                    )
                    return None
                datapoints, _completion_attr = self._build_zoom_datapoints(
                    chunks,
                    opportunity_id,
                    channel,
                    source_id,
                    document_id,
                    _safe_string,
                )
            else:  # gmail_messages
                raw_text = content.decode("utf-8")
                # Extract thread_id from object_name (e.g., "{thread_id}/content.txt")
                thread_id = object_name.split("/")[0] if "/" in object_name else ""
                chunks = self._gmail_chunker.chunk(raw_text, opportunity_id, thread_id)
                if not chunks:
                    logger.bind(opportunity_id=opportunity_id).warning(
                        "No Gmail chunks produced"
                    )
                    return None
                datapoints, _completion_attr = self._build_gmail_datapoints(
                    chunks,
                    opportunity_id,
                    channel,
                    source_id,
                    document_id,
                    thread_id,
                    _safe_string,
                )

            # Embed, upsert, and optionally delete (chunk-level diff for documents)
            new_registry_chunks = [
                {
                    "chunk_id": dp.get("chunk_id") or dp.get("datapoint_id", ""),
                    "chunk_index": idx,
                    "chunk_hash": _sha256_hex(dp["text"]),
                    "datapoint_id": dp.get("datapoint_id", ""),
                }
                for idx, dp in enumerate(datapoints)
            ]

            if source_type == "documents":
                registry_document_id = f"{opportunity_id}:documents:{object_name}"
                gcs_path = f"{opportunity_id}/processed/{source}/{object_name}"
                doc_hash = _sha256_hex(content)
                existing_chunks = self._registry.get_chunks(registry_document_id)
                existing_map = {int(c["chunk_index"]): c for c in existing_chunks}

                to_upsert = [
                    idx
                    for idx in range(len(datapoints))
                    if idx not in existing_map
                    or (existing_map[idx].get("chunk_hash") or "").strip()
                    != new_registry_chunks[idx]["chunk_hash"]
                ]
                to_delete_ids = [
                    existing_map[i]["datapoint_id"]
                    for i in sorted(existing_map)
                    if i >= len(datapoints)
                ]

                # Note: stale chunks are automatically deleted by write_registry()
                # which does DELETE + INSERT for all chunks in pgvector
                if to_delete_ids:
                    logger.bind(opportunity_id=opportunity_id).info(
                        "Re-ingestion: %d stale chunk(s) will be removed — document_id=%s",
                        len(to_delete_ids),
                        registry_document_id,
                    )
                if to_upsert:
                    datapoints_subset = [datapoints[i] for i in to_upsert]
                    texts_subset = [dp["text"] for dp in datapoints_subset]
                    embeddings_subset = embed_texts(texts_subset)
                    # Attach text + embedding directly into each chunk dict for registry write
                    for idx, dp_idx in enumerate(to_upsert):
                        new_registry_chunks[dp_idx]["chunk_text"] = texts_subset[idx]
                        new_registry_chunks[dp_idx]["embedding"] = embeddings_subset[
                            idx
                        ]

                self._registry.write_registry(
                    document_id=registry_document_id,
                    opportunity_id=opportunity_id,
                    gcs_path=gcs_path,
                    doc_hash=doc_hash,
                    total_chunks=len(datapoints),
                    chunks=new_registry_chunks,
                )
                chunks_upserted = len(to_upsert)
            else:
                texts = [dp["text"] for dp in datapoints]
                embeddings = embed_texts(texts)
                for i, chunk in enumerate(new_registry_chunks):
                    chunk["chunk_text"] = texts[i]
                    chunk["embedding"] = embeddings[i]
                chunks_upserted = len(datapoints)

                registry_document_id = (
                    f"{opportunity_id}:{source_type}:{source_id or document_id}"
                )
                gcs_path = f"{opportunity_id}/{source}/{source_id or document_id}"
                doc_hash = _sha256_hex(content)
                self._registry.write_registry(
                    document_id=registry_document_id,
                    opportunity_id=opportunity_id,
                    gcs_path=gcs_path,
                    doc_hash=doc_hash,
                    total_chunks=len(datapoints),
                    chunks=new_registry_chunks,
                )

                registry_document_id = (
                    f"{opportunity_id}:{source_type}:{source_id or document_id}"
                )
                gcs_path = f"{opportunity_id}/{source}/{source_id or document_id}"
                doc_hash = _sha256_hex(content)
                self._registry.write_registry(
                    document_id=registry_document_id,
                    opportunity_id=opportunity_id,
                    gcs_path=gcs_path,
                    doc_hash=doc_hash,
                    total_chunks=len(datapoints),
                    chunks=new_registry_chunks,
                )

            logger.bind(opportunity_id=opportunity_id).info(
                "RAG ingest SUCCESS %s — chunks_upserted=%s source_id=%s",
                source_type,
                chunks_upserted,
                source_id,
            )
            logger.bind(opportunity_id=opportunity_id).info(
                "Document %s ingested successfully",
                object_name
                if source_type == "documents"
                else (source_id or object_name),
            )

            # Publish completion (payload: opportunity_id only)
            if output_topic:
                publisher = Publisher(topic=output_topic)
                completion_payload = {"opportunity_id": opportunity_id}
                publisher.publish(completion_payload, opportunity_id=opportunity_id)
                logger.bind(opportunity_id=opportunity_id).info(
                    "RAG ingest SUCCESS — published to output topic — payload=%s",
                    completion_payload,
                )

            elapsed = round(time.time() - start_time, 2)
            logger.bind(opportunity_id=opportunity_id).info(
                "RAG ingest SUCCESS completed — source_type=%s execution_seconds=%s published_to_output_topic",
                source_type,
                elapsed,
            )
            refresh_opportunity_pipeline_state(opportunity_id, "ingested")
            return f"{source_type}:{chunks_upserted}"

        except Exception:
            logger.bind(opportunity_id=opportunity_id).exception(
                "Ingestion pipeline failed — source_type=%s",
                source_type,
            )
            raise

    def delete_document_from_registry(
        self,
        opportunity_id: str,
        object_name: str,
    ) -> bool:
        """Remove one document from document_registry and chunk_registry.

        Used by event-driven deletion (rag-ingestion-queue, action_type=document_deleted).
        Idempotent: returns False if there is no document or chunk row for this id.

        Returns:
            True if rows were deleted, False if nothing matched.
        """
        document_id = f"{opportunity_id}:documents:{object_name}"
        has_doc = self._registry.get_document(document_id) is not None
        has_chunks = bool(self._registry.get_chunks(document_id))
        if not has_doc and not has_chunks:
            logger.bind(opportunity_id=opportunity_id).info(
                "Document deletion: not in RAG registry, skipping — document_id={}",
                document_id,
            )
            return False
        self._registry.delete_document(document_id)
        logger.bind(opportunity_id=opportunity_id).info(
            "Document deletion: removed from registry — document_id={}",
            document_id,
        )
        return True

    def _reconcile_orphan_documents(
        self,
        opportunity_id: str,
    ) -> None:
        """Remove registry rows for documents that are no longer in GCS processed/documents.

        Not called from ``run_message``. Production document removal uses ``document_deleted``
        only. Kept for manual use and ``scripts/tests_integration/smoke_reconciliation_retry.py``.

        Lists all objects under processed/documents for this opportunity (no lookback),
        compares with document_registry, and deletes orphans from chunk_registry and
        document_registry (pgvector-backed retrieval only).
        """
        all_object_names = self._storage.list_objects(
            "processed", opportunity_id, "documents"
        )
        current_object_names = [n for n in all_object_names if not n.endswith("/")]
        current_doc_ids = {
            f"{opportunity_id}:documents:{name}" for name in current_object_names
        }
        registry_doc_ids = self._registry.list_document_ids(
            opportunity_id, source_type="documents"
        )
        orphan_doc_ids = set(registry_doc_ids) - current_doc_ids
        if not orphan_doc_ids:
            return

        if not current_doc_ids and orphan_doc_ids:
            logger.bind(opportunity_id=opportunity_id).warning(
                "Reconciliation: no documents in GCS directory for opportunity — all {} document(s) in RAG registry will be deleted — opportunity_id={}",
                len(orphan_doc_ids),
                opportunity_id,
            )

        for orphan_document_id in orphan_doc_ids:
            prefix = f"{opportunity_id}:documents:"
            object_name = orphan_document_id.removeprefix(prefix)
            self.delete_document_from_registry(opportunity_id, object_name)

        logger.bind(opportunity_id=opportunity_id).info(
            "Reconciliation: removed {} orphan document(s) — opportunity_id={} document_ids={}",
            len(orphan_doc_ids),
            opportunity_id,
            sorted(orphan_doc_ids),
        )

    def _build_document_datapoints(
        self,
        chunk_texts: list[str],
        opportunity_id: str,
        channel: str,
        source_id: str,
        document_id: str,
        object_name: str,
        safe_string: callable,
    ) -> tuple[list[dict], str]:
        """Build datapoint dicts for documents (list of text chunks).

        Note: chunk_id is a stable, readable identifier (file-based, index-based).
        datapoint_id is the unique chunk_registry / retrieval key, prefixed with the
        (safe) document_id to avoid collisions across opportunities/documents.
        """
        return (
            build_document_datapoints_for_upsert(
                chunk_texts,
                opportunity_id,
                channel,
                source_id,
                document_id,
                object_name,
                safe_string=safe_string,
            ),
            "gdrive_messages_processed",
        )

    def _build_slack_datapoints(
        self,
        chunks: list[dict],
        opportunity_id: str,
        channel: str,
        source_id: str,
        document_id: str,
        safe_string: callable,
    ) -> tuple[list[dict], str]:
        """Build datapoint dicts for Slack (chunks have section, part, text, chunk_index)."""
        safe_opp = safe_string(opportunity_id)
        safe_src = safe_string(source_id)
        datapoints = [
            {
                "text": chunk["text"],
                "datapoint_id": f"{safe_opp}_slack_{safe_src}_{safe_string(chunk['section'])}_part_{chunk['part']}",
                "restricts": [
                    {"namespace": "opportunity_id", "allow_list": [opportunity_id]},
                    {"namespace": "channel", "allow_list": [channel]},
                    {"namespace": "source_id", "allow_list": [source_id]},
                    {"namespace": "document_id", "allow_list": [document_id]},
                ],
                "embedding_metadata": {
                    "text": chunk["text"],
                    "section": chunk["section"],
                    "section_part": chunk["part"],
                    "chunk_index": chunk["chunk_index"],
                    "chunking_strategy": "slack_section_semantic",
                    "ingested_at": datetime.now(UTC).isoformat(),
                    "opportunity_id": opportunity_id,
                },
            }
            for chunk in chunks
        ]
        return datapoints, "slack_messages_processed"

    def _build_zoom_datapoints(
        self,
        chunks: list[dict],
        opportunity_id: str,
        channel: str,
        source_id: str,
        document_id: str,
        safe_string: callable,
    ) -> tuple[list[dict], str]:
        """Build datapoint dicts for Zoom (chunks have text, start_time, end_time)."""
        safe_opp = safe_string(opportunity_id)
        safe_src = safe_string(source_id)
        datapoints = []
        for idx, chunk in enumerate(chunks):
            datapoints.append({
                "text": chunk["text"],
                "datapoint_id": f"{safe_opp}_zoom_{safe_src}_idx_{idx}",
                "restricts": [
                    {"namespace": "opportunity_id", "allow_list": [opportunity_id]},
                    {"namespace": "channel", "allow_list": [channel]},
                    {"namespace": "source_id", "allow_list": [source_id]},
                    {"namespace": "document_id", "allow_list": [document_id]},
                ],
                "embedding_metadata": {
                    "text": chunk["text"],
                    "chunk_index": idx,
                    "start_time_seconds": chunk["start_time"],
                    "end_time_seconds": chunk["end_time"],
                    "chunking_strategy": "3min_window_1min_overlap",
                    "opportunity_id": opportunity_id,
                },
            })
        return datapoints, "zoom_messages_processed"

    def _build_gmail_datapoints(
        self,
        chunks: list[dict],
        opportunity_id: str,
        channel: str,
        source_id: str,
        document_id: str,
        thread_id: str,
        safe_string: callable,
    ) -> tuple[list[dict], str]:
        """Build datapoint dicts for Gmail (chunks have text, thread_id, message_range, chunk_index)."""
        safe_opp = safe_string(opportunity_id)
        safe_thread = safe_string(thread_id)
        datapoints = []
        for chunk in chunks:
            chunk_idx = chunk.get("chunk_index", 0)
            message_range = chunk.get("message_range", "")
            message_count = chunk.get("message_count", 0)

            datapoints.append({
                "text": chunk["text"],
                "datapoint_id": f"{safe_opp}_gmail_{safe_thread}_chunk_{chunk_idx}",
                "restricts": [
                    {"namespace": "opportunity_id", "allow_list": [opportunity_id]},
                    {"namespace": "source_type", "allow_list": ["gmail"]},
                    {"namespace": "thread_id", "allow_list": [thread_id]},
                ],
                "embedding_metadata": {
                    "text": chunk["text"],
                    "chunk_index": chunk_idx,
                    "thread_id": thread_id,
                    "message_range": message_range,
                    "message_count": message_count,
                    "chunking_strategy": "3msg_window_1msg_overlap",
                    "ingested_at": datetime.now(UTC).isoformat(),
                    "opportunity_id": opportunity_id,
                },
            })
        return datapoints, "gmail_messages_processed"

    def run_for_opportunity(
        self,
        opportunity_id: str,
        since: datetime | None = None,
    ) -> list[str]:
        """Scan processed/ for one opportunity and ingest all (placeholder).

        Returns:
            List of correlation IDs (empty for now).
        """
        logger.bind(opportunity_id=opportunity_id).info(
            "IngestionPipeline.run_for_opportunity called (placeholder)"
        )
        return []
