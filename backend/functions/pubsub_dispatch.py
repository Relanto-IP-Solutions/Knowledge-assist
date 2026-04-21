"""Cloud Function: pubsub-dispatch — HTTP trigger (Cloud Scheduler + document_deleted).

Scans GCS processed/ tier and publishes eligible files to rag-ingestion-queue
(action_type=document_ingested).

document_deleted is published when gcs-file-processor POSTs after removing orphan
processed/documents files (raw delete flow).

Trigger:
  HTTP POST via Cloud Scheduler (cron) or gcs-file-processor (OIDC).

Deployment:
  docs/runbooks/ingestion-pipeline-deployment.md

Env vars: GCP_PROJECT_ID, GCS_BUCKET_INGESTION, PUBSUB_TOPIC_RAG_INGESTION,
  PYTHONPATH, FUNCTION_SOURCE.
"""

import contextlib
import json

import functions_framework

from configs.settings import get_settings
from src.services.pipelines.pubsub_pipeline import (
    PubsubPipeline,
    parse_document_deleted_pubsub_body,
)
from src.utils.logger import get_logger
from src.utils.opportunity_id import normalize_opportunity_oid


logger = get_logger(__name__)


def _bucket_from_gs_data_path(data_path: str) -> str | None:
    s = (data_path or "").strip()
    if not s.startswith("gs://"):
        return None
    return s[5:].split("/", 1)[0].strip() or None


@functions_framework.http
def handle_http(request):
    """HTTP — document_deleted POST (gcs-file-processor) or scheduler sweep."""
    body = None
    with contextlib.suppress(Exception):
        body = request.get_json(silent=True) if request.is_json else None
    if body is None and request.data:
        try:
            body = json.loads(request.get_data(as_text=True))
        except Exception:
            body = None

    if body and body.get("action_type") == "document_deleted":
        parsed = parse_document_deleted_pubsub_body(body)
        if parsed:
            opportunity_id, object_name = parsed
            bucket = _bucket_from_gs_data_path(str(body.get("data_path") or ""))
            if not bucket:
                bucket = (get_settings().ingestion.gcs_bucket_ingestion or "").strip()
            if not bucket:
                logger.warning(
                    "document_deleted POST: missing bucket in data_path and env"
                )
                return {
                    "action_type": "document_deleted",
                    "published": False,
                    "reason": "missing_bucket",
                }, 400
            try:
                pipeline = PubsubPipeline()
                message_ids = pipeline.run(
                    deletion_payloads=[body],
                    run_ingestion_scan=False,
                )
                return {
                    "action_type": "document_deleted",
                    "published": True,
                    "document_file": object_name,
                    "opportunity_id": opportunity_id,
                    "message_ids": message_ids,
                }, 200
            except Exception as e:
                logger.exception(
                    "document_deleted publish failed — opportunity_id={} object_name={}",
                    opportunity_id,
                    object_name,
                )
                return {
                    "action_type": "document_deleted",
                    "published": False,
                    "document_file": object_name,
                    "opportunity_id": opportunity_id,
                    "error": str(e),
                }, 500
        logger.warning(
            "document_deleted POST unparseable — keys={}",
            list(body.keys()) if isinstance(body, dict) else None,
        )
        return {
            "action_type": "document_deleted",
            "published": False,
            "reason": "unparseable",
        }, 400

    opportunity_id = request.args.get("opportunity_id") or None
    if opportunity_id:
        try:
            opportunity_id = normalize_opportunity_oid(opportunity_id)
        except ValueError as exc:
            return {"error": str(exc)}, 400
    extras = {"opportunity_id": opportunity_id} if opportunity_id else {}

    try:
        logger.bind(**extras).info("Pubsub dispatch started")
        lookback_minutes = int(request.args.get("lookback_minutes", 15))
        logger.bind(**extras).info("Pubsub dispatch running pipeline")
        pipeline = PubsubPipeline()
        message_ids = pipeline.run(
            opportunity_id=opportunity_id,
            lookback_minutes=lookback_minutes,
        )
        logger.bind(**extras).info("Pubsub dispatch complete")
        return {"published": len(message_ids), "message_ids": message_ids}, 200
    except Exception as exc:
        logger.bind(**extras).exception("Pubsub dispatch failed: {}", exc)
        return {"error": str(exc)}, 500
