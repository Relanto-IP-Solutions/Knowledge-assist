"""Re-ingestion registry: document_registry and chunk_registry writes.

Used by the ingestion pipeline after embedding chunks, to store them in PostgreSQL
(pgvector) for semantic retrieval.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from src.services.database_manager.connection import get_db_connection
from src.services.database_manager.operations import rows_to_dicts
from src.utils.logger import get_logger


logger = get_logger(__name__)


class RegistryClient:
    """Client for document_registry and chunk_registry operations."""

    def get_document(self, document_id: str) -> dict[str, Any] | None:
        """Return the document_registry row for document_id, or None if not found.

        Used for document-level skip: if doc_hash matches, ingestion is skipped.
        """
        con = get_db_connection()
        try:
            cur = con.cursor()
            cur.execute(
                "SELECT document_id, opportunity_id, source_type, gcs_path, doc_hash, total_chunks, created_at, updated_at "
                "FROM document_registry WHERE document_id = %s",
                (document_id,),
            )
            raw = cur.fetchall()
            rows = rows_to_dicts(cur, raw)
            return rows[0] if rows else None
        finally:
            con.close()

    def get_chunks(self, document_id: str) -> list[dict[str, Any]]:
        """Return all chunk_registry rows for document_id, ordered by chunk_index.

        Used for chunk-level diff: compare existing chunk_hash per index to decide
        which chunks to re-embed and which datapoint_ids to replace in chunk_registry.
        """
        con = get_db_connection()
        try:
            cur = con.cursor()
            cur.execute(
                "SELECT chunk_id, document_id, opportunity_id, chunk_index, chunk_hash, datapoint_id, created_at, updated_at "
                "FROM chunk_registry WHERE document_id = %s ORDER BY chunk_index",
                (document_id,),
            )
            raw = cur.fetchall()
            return rows_to_dicts(cur, raw)
        finally:
            con.close()

    def list_document_ids(
        self,
        opportunity_id: str,
        source_type: str = "documents",
    ) -> list[str]:
        """Return all document_id values in document_registry for the given opportunity and source type.

        Used for orphan reconciliation: compare with current GCS object list to find
        documents to remove from the RAG registry (PostgreSQL).
        """
        con = get_db_connection()
        try:
            cur = con.cursor()
            cur.execute(
                "SELECT document_id FROM document_registry WHERE opportunity_id = %s AND source_type = %s",
                (opportunity_id, source_type),
            )
            raw = cur.fetchall()
            rows = rows_to_dicts(cur, raw)
            return [r["document_id"] for r in rows]
        finally:
            con.close()

    def delete_document(self, document_id: str) -> None:
        """Remove a document and its chunks from document_registry and chunk_registry.

        Removes chunk rows then the document_registry row for this document_id.
        """
        con = get_db_connection()
        try:
            cur = con.cursor()
            cur.execute(
                "DELETE FROM chunk_registry WHERE document_id = %s", (document_id,)
            )
            cur.execute(
                "DELETE FROM document_registry WHERE document_id = %s", (document_id,)
            )
            con.commit()
            logger.info(
                "Deleted document from registry — document_id=%s",
                document_id,
            )
        except Exception:
            con.rollback()
            logger.exception(
                "Registry delete failed — document_id=%s",
                document_id,
            )
            raise
        finally:
            con.close()

    def write_registry(
        self,
        document_id: str,
        opportunity_id: str,
        gcs_path: str,
        doc_hash: str,
        total_chunks: int,
        chunks: list[dict[str, Any]],
        source_type: str = "documents",
    ) -> None:
        """Write or update document_registry and chunk_registry for a single document.

        Args:
            document_id: Logical document ID (e.g. "{opportunity_id}:documents:{object_name}").
            opportunity_id: Opportunity ID.
            gcs_path: Processed GCS path (e.g. "{opportunity_id}/processed/documents/{object_name}").
            doc_hash: SHA-256 hex of full processed file content.
            total_chunks: Number of chunks.
            chunks: List of dicts with keys: chunk_id, chunk_index, chunk_hash, datapoint_id,
                    chunk_text (str), embedding (list[float]).
        """
        now = datetime.now(UTC)
        con = get_db_connection()
        try:
            cur = con.cursor()
            # 1. Upsert the document-level record
            cur.execute(
                """
                INSERT INTO document_registry (
                    document_id, opportunity_id, source_type, gcs_path,
                    doc_hash, total_chunks, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (document_id) DO UPDATE SET
                    doc_hash = EXCLUDED.doc_hash,
                    total_chunks = EXCLUDED.total_chunks,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    document_id,
                    opportunity_id,
                    source_type,
                    gcs_path,
                    doc_hash,
                    total_chunks,
                    now,
                    now,
                ),
            )
            cur.execute(
                "DELETE FROM chunk_registry WHERE document_id = %s", (document_id,)
            )
            for c in chunks:
                embedding = c.get("embedding")
                # If pgvector adapter wasn't registered, convert list to string manually
                if isinstance(embedding, list):
                    embedding = "[" + ",".join(map(str, embedding)) + "]"

                cur.execute(
                    """
                    INSERT INTO chunk_registry (
                        chunk_id, document_id, opportunity_id, chunk_index,
                        chunk_hash, datapoint_id, created_at, updated_at,
                        chunk_text, embedding
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (document_id, chunk_index) DO UPDATE SET
                        chunk_id = EXCLUDED.chunk_id,
                        opportunity_id = EXCLUDED.opportunity_id,
                        chunk_hash = EXCLUDED.chunk_hash,
                        datapoint_id = EXCLUDED.datapoint_id,
                        chunk_text = EXCLUDED.chunk_text,
                        embedding = EXCLUDED.embedding,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (
                        c["chunk_id"],
                        document_id,
                        opportunity_id,
                        c["chunk_index"],
                        c["chunk_hash"],
                        c["datapoint_id"],
                        now,
                        now,
                        c.get("chunk_text"),
                        embedding,
                    ),
                )
            con.commit()
            logger.debug(
                "Registry updated — document_id=%s chunks=%s",
                document_id,
                total_chunks,
            )
        except Exception:
            con.rollback()
            logger.exception(
                "Registry write failed — document_id=%s",
                document_id,
            )
            raise
        finally:
            con.close()


def get_document_registry(document_id: str) -> dict[str, Any] | None:
    """Return the document_registry row for document_id, or None if not found."""
    return RegistryClient().get_document(document_id)


def get_chunk_registry(document_id: str) -> list[dict[str, Any]]:
    """Return all chunk_registry rows for document_id, ordered by chunk_index."""
    return RegistryClient().get_chunks(document_id)


def list_document_ids_for_opportunity(
    opportunity_id: str,
    source_type: str = "documents",
) -> list[str]:
    """Return all document_id values in document_registry for the given opportunity and source type."""
    return RegistryClient().list_document_ids(opportunity_id, source_type)


def delete_document_from_registry(document_id: str) -> None:
    """Remove a document and its chunks from document_registry and chunk_registry."""
    RegistryClient().delete_document(document_id)


def write_ingestion_registry(
    document_id: str,
    opportunity_id: str,
    gcs_path: str,
    doc_hash: str,
    total_chunks: int,
    chunks: list[dict[str, Any]],
    source_type: str = "documents",
) -> None:
    """Write or update document_registry and chunk_registry for a single document."""
    RegistryClient().write_registry(
        document_id,
        opportunity_id,
        gcs_path,
        doc_hash,
        total_chunks,
        chunks,
        source_type=source_type,
    )
