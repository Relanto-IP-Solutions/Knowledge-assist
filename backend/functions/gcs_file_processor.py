"""Cloud Function: gcs-file-processor — HTTP trigger (Cloud Scheduler).

Scans GCS raw/ for files in the last N minutes, preprocesses by source type,
writes to processed/ tier. After orphan processed/documents deletes, notifies
pubsub-dispatch (OIDC POST) so rag-ingestion-queue receives action_type=document_deleted.

Trigger:
  HTTP POST via Cloud Scheduler (cron, every 15 min).

Deployment:
  docs/runbooks/ingestion-pipeline-deployment.md

Env vars: GCP_PROJECT_ID, GCS_BUCKET_INGESTION, PUBSUB_DISPATCH_URL (required),
  PYTHONPATH, FUNCTION_SOURCE.
"""

from datetime import UTC, datetime, timedelta

import functions_framework

from configs.settings import get_settings
from src.services.pipelines.gcs_pipeline import GcsPipeline
from src.services.pipelines.pubsub_pipeline import PubsubPipeline
from src.utils.logger import get_logger
from src.utils.opportunity_id import normalize_opportunity_oid


logger = get_logger(__name__)

_SCHEDULER_WINDOW_MINUTES = 15


@functions_framework.http
def handle(request):
    """HTTP entry point called by Cloud Scheduler.

    Query parameters:
        opportunity_id   (optional): scope the scan to a single opportunity.
        lookback_minutes (optional): override the default 15-minute window.
                                     Pass 0 to process all files regardless of age.

    Returns:
        HTTP 200: synced, uris, deleted, deleted_uris, document_deletion_notifies (if any).
        HTTP 500: {"error": "<message>"} (e.g. missing PUBSUB_DISPATCH_URL).
    """
    opportunity_id = request.args.get("opportunity_id") or None
    if opportunity_id:
        try:
            opportunity_id = normalize_opportunity_oid(opportunity_id)
        except ValueError as exc:
            return {"error": str(exc)}, 400
    extras = {"opportunity_id": opportunity_id} if opportunity_id else {}

    try:
        logger.info("GCS file processor started", extra=extras)
        dispatch_url = (get_settings().ingestion.pubsub_dispatch_url or "").strip()
        if not dispatch_url:
            msg = "PUBSUB_DISPATCH_URL is required"
            logger.error(msg, extra=extras)
            return {"error": msg}, 500

        lookback_minutes = int(
            request.args.get("lookback_minutes", _SCHEDULER_WINDOW_MINUTES)
        )
        since = (
            datetime.now(UTC) - timedelta(minutes=lookback_minutes)
            if lookback_minutes > 0
            else None
        )
        logger.info("GCS file processor running pipeline", extra=extras)
        pipeline = GcsPipeline()
        written_uris, deleted_uris = pipeline.run(
            opportunity_id=opportunity_id, since=since
        )

        notifies: list[dict] = []
        if deleted_uris:
            notifies = PubsubPipeline().publish_deletions_via_dispatch(
                dispatch_url, deleted_uris
            )
            for n in notifies:
                if n.get("ok"):
                    logger.info(
                        "document_deleted notify OK — gs_uri=%s",
                        n.get("gs_uri"),
                        extra=extras,
                    )
                else:
                    logger.warning(
                        "document_deleted notify failed — gs_uri=%s error=%s",
                        n.get("gs_uri"),
                        n.get("message") or n.get("error"),
                        extra=extras,
                    )

        logger.info("GCS file processor complete", extra=extras)
        out = {
            "synced": len(written_uris),
            "uris": written_uris,
            "deleted": len(deleted_uris),
            "deleted_uris": deleted_uris,
        }
        if notifies:
            out["document_deletion_notifies"] = notifies
        return out, 200
    except Exception as exc:
        logger.error(
            "GCS file processor failed: %s",
            exc,
            exc_info=True,
            extra=extras,
        )
        return {"error": str(exc)}, 500
