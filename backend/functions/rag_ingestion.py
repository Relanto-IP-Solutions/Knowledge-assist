"""Cloud Function: rag-ingestion — Pub/Sub trigger (rag-ingestion-queue only).

Ingestion messages (action_type=document_ingested or legacy): chunk, embed,
write embeddings to PostgreSQL (chunk_registry / pgvector), publish completion.

Deletion messages (action_type=document_deleted): remove the document and its
chunks from document_registry and chunk_registry only. RAG retrieval uses
pgvector in Cloud SQL, not Vertex AI Vector Search indexes.

Trigger:
  Pub/Sub push (one message per file or per deletion).

Deployment:
  docs/runbooks/ingestion-pipeline-deployment.md

Env vars: OUTPUT_TOPIC, GCP_PROJECT_ID, GCS_BUCKET_INGESTION, PYTHONPATH,
  FUNCTION_SOURCE, and DB settings (e.g. CLOUDSQL_INSTANCE_CONNECTION_NAME, PG_*).
  Vertex AI embedding / Gemini keys as required by the shared ingestion code.
"""

import base64
import json

import functions_framework

from src.services.pipelines.ingestion_pipeline import IngestionPipeline
from src.services.pipelines.pubsub_pipeline import parse_document_deleted_pubsub_body
from src.utils.logger import get_logger


logger = get_logger(__name__)


def _handle_document_deleted(body: dict) -> bool:
    """Handle document_deleted message. Returns True if handled, False if not a deletion message."""
    if (
        body.get("action_type") != "document_deleted"
        and body.get("event") != "document_deleted"
    ):
        return False

    parsed = parse_document_deleted_pubsub_body(body)
    if not parsed:
        logger.bind(
            opportunity_id=(body.get("metadata") or {}).get("opportunity_id")
        ).error(
            "document_deleted message could not be parsed — body keys=%s",
            list(body.keys()),
        )
        return True

    opportunity_id, object_name = parsed

    try:
        pipeline = IngestionPipeline()
        deleted = pipeline.delete_document_from_registry(opportunity_id, object_name)
        if deleted:
            logger.bind(opportunity_id=opportunity_id).info(
                "Document deletion completed — opportunity_id=%s object_name=%s",
                opportunity_id,
                object_name,
            )
        else:
            logger.bind(opportunity_id=opportunity_id).debug(
                "Document deletion skipped (not in RAG registry) — opportunity_id=%s object_name=%s",
                opportunity_id,
                object_name,
            )
    except Exception as e:
        logger.bind(opportunity_id=opportunity_id).exception(
            "Document deletion failed — opportunity_id=%s object_name=%s error=%s",
            opportunity_id,
            object_name,
            e,
        )
        raise
    return True


@functions_framework.cloud_event
def handle_pubsub(cloud_event):
    """Pub/Sub push — rag-ingestion-queue only.

    document_deleted: parse data_path + metadata → delete from document_registry / chunk_registry.
    Otherwise: IngestionPipeline.run_message().
    """
    data = getattr(cloud_event, "data", None) or cloud_event.get("data", {}) or {}
    message = data.get("message") or {}
    raw = message.get("data")
    if not raw:
        logger.warning("Pub/Sub message missing data")
        return

    try:
        body = json.loads(base64.b64decode(raw).decode("utf-8"))
    except Exception as e:
        logger.exception("Failed to decode Pub/Sub message body: {}", e)
        return

    if _handle_document_deleted(body):
        return

    opportunity_id = (body.get("metadata") or {}).get("opportunity_id", "")

    pipeline = IngestionPipeline()
    result = pipeline.run_message(body)
    if result:
        logger.bind(opportunity_id=opportunity_id).info(
            "RAG ingestion completed — result={}",
            result,
        )
    else:
        logger.bind(opportunity_id=opportunity_id).warning(
            "RAG ingestion returned no result"
        )
