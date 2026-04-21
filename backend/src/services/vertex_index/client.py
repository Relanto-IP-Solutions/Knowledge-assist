"""Vertex AI Vector Search index client. Upsert and remove datapoints with retry on transient errors."""

from __future__ import annotations

from google.cloud import aiplatform_v1
from google.cloud.aiplatform_v1.types import (
    IndexDatapoint,
    RemoveDatapointsRequest,
    UpsertDatapointsRequest,
)

from src.utils.logger import get_logger
from src.utils.retry import retry_on_transient


logger = get_logger(__name__)

# Vertex AI Vector Search allows max 1000 datapoints per upsert request; use smaller batches for stability.
MAX_UPSERT_BATCH = 500


class VertexIndexClient:
    """Client for upserting datapoints to a Vertex AI Vector Search index."""

    @retry_on_transient()
    def upsert_datapoints(
        self,
        index_resource_name: str,
        datapoints: list[dict],
        embeddings: list[list[float]],
        api_endpoint: str,
    ) -> None:
        """Upsert datapoints to the index. Retries on transient GCP errors.

        Args:
            index_resource_name: Full index resource name (e.g. projects/.../indexes/...).
            datapoints: List of dicts with keys datapoint_id, restricts, embedding_metadata.
            embeddings: List of embedding vectors (one per datapoint); same order as datapoints.
            api_endpoint: Vertex AI API endpoint (e.g. us-central1-aiplatform.googleapis.com).
        """
        index_datapoints = []
        for i, dp in enumerate(datapoints):
            index_datapoints.append(
                IndexDatapoint(
                    datapoint_id=dp["datapoint_id"],
                    feature_vector=embeddings[i] if i < len(embeddings) else [],
                    restricts=dp["restricts"],
                    embedding_metadata=dp.get("embedding_metadata") or {},
                )
            )
        client = aiplatform_v1.IndexServiceClient(
            client_options={"api_endpoint": api_endpoint}
        )
        total = len(index_datapoints)
        for start in range(0, total, MAX_UPSERT_BATCH):
            batch = index_datapoints[start : start + MAX_UPSERT_BATCH]
            client.upsert_datapoints(
                request=UpsertDatapointsRequest(
                    index=index_resource_name,
                    datapoints=batch,
                )
            )
            if total > MAX_UPSERT_BATCH:
                logger.info(
                    "Upserted batch %d–%d of %d datapoints to index",
                    start + 1,
                    start + len(batch),
                    total,
                )
            else:
                logger.debug(
                    "Upserted %d datapoints to index",
                    len(batch),
                )

    @retry_on_transient()
    def delete_datapoints(
        self,
        index_resource_name: str,
        datapoint_ids: list[str],
        api_endpoint: str,
    ) -> None:
        """Remove datapoints from the index by ID. Retries on transient GCP errors.

        Args:
            index_resource_name: Full index resource name (e.g. projects/.../indexes/...).
            datapoint_ids: List of datapoint IDs to remove.
            api_endpoint: Vertex AI API endpoint (e.g. us-central1-aiplatform.googleapis.com).
        """
        if not datapoint_ids:
            return
        client = aiplatform_v1.IndexServiceClient(
            client_options={"api_endpoint": api_endpoint}
        )
        sample = datapoint_ids[:5] if len(datapoint_ids) > 5 else datapoint_ids
        suffix = ", ..." if len(datapoint_ids) > 5 else ""
        logger.info(
            "Vertex Vector Search: removing %d datapoint(s) — sample=%s%s",
            len(datapoint_ids),
            sample,
            suffix,
        )
        client.remove_datapoints(
            request=RemoveDatapointsRequest(
                index=index_resource_name,
                datapoint_ids=datapoint_ids,
            )
        )
        logger.info(
            "Vertex Vector Search: removed %d datapoint(s) from index",
            len(datapoint_ids),
        )
