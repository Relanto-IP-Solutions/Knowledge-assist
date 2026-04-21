"""Cloud Function: rag-orchestrator — HTTP trigger (Cloud Scheduler or manual).

Runs RagPipeline (retrieval + answer-generation) for one or more opportunities.

Trigger:
  HTTP POST. Body {"opportunity_id": "..."} for single-opp; empty {} for batch poll.

Modes:
  Single-opp: POST with opportunity_id returns answer-generation output.
  Batch: empty body pulls from rag-retrieval-initiation subscription, processes each.

Deployment:
  docs/runbooks/answer-generation-cloud-run.md

Env vars: GCP_PROJECT_ID, GCS_BUCKET_INGESTION, VERTEX_AI_LOCATION,
  ANSWER_GENERATION_URL, PUBSUB_SUBSCRIPTION_RETRIEVAL_INITIATION (batch),
  VECTOR_SOURCE_* (9 vars) or VECTOR_SOURCES, PYTHONPATH, FUNCTION_SOURCE.
"""

from __future__ import annotations

import json

import functions_framework
from google.cloud import pubsub_v1

from configs.settings import get_settings
from src.services.pipelines.rag_pipeline import RagPipeline
from src.utils.logger import get_logger


logger = get_logger(__name__)


def _parse_opportunity_id(msg_bytes: bytes) -> str | None:
    """Parse opportunity_id from Pub/Sub message (JSON or plain string)."""
    s = msg_bytes.decode("utf-8", errors="ignore").strip()
    if not s:
        return None
    if s.startswith("{"):
        try:
            obj = json.loads(s)
            oid = obj.get("opportunity_id")
            return str(oid).strip() if oid is not None else None
        except Exception:
            return None
    return s


@functions_framework.http
def handle_http(request):
    """HTTP entry point. Batch poll from Pub/Sub, or single-opp if body has opportunity_id."""
    # Single-opp mode: body has opportunity_id
    body = request.get_json(silent=True) or {}
    opportunity_id = (body.get("opportunity_id") or "").strip()
    if opportunity_id:
        try:
            pipeline = RagPipeline()
            result = pipeline.run_one(opportunity_id)
            return (
                json.dumps(result, indent=2, ensure_ascii=False),
                200,
                {"Content-Type": "application/json"},
            )
        except Exception as exc:
            logger.bind(opportunity_id=opportunity_id).error(
                "RAG pipeline failed: %s",
                exc,
                exc_info=True,
            )
            return (
                json.dumps({"error": str(exc)}),
                500,
                {"Content-Type": "application/json"},
            )

    # Batch polling mode: pull from Pub/Sub
    settings = get_settings().retrieval
    subscription_id = settings.pubsub_subscription_retrieval_initiation.strip()
    if not subscription_id:
        return (
            json.dumps({
                "error": "PUBSUB_SUBSCRIPTION_RETRIEVAL_INITIATION not set; cannot batch poll"
            }),
            400,
            {"Content-Type": "application/json"},
        )

    project_id = settings.gcp_project_id or get_settings().ingestion.gcp_project_id
    if not project_id:
        return (
            json.dumps({"error": "GCP_PROJECT_ID not set"}),
            500,
            {"Content-Type": "application/json"},
        )

    subscriber = pubsub_v1.SubscriberClient()
    sub_path = subscriber.subscription_path(project_id, subscription_id)
    pull_resp = subscriber.pull(
        request={
            "subscription": sub_path,
            "max_messages": settings.retrieval_batch_size,
        }
    )
    received = pull_resp.received_messages or []

    logger.info("Pulled {} messages", len(received))
    if not received:
        return ("No messages", 200)

    ack_ids_by_opp: dict[str, list[str]] = {}
    for rm in received:
        opp_id = _parse_opportunity_id(rm.message.data)
        if not opp_id:
            continue
        ack_ids_by_opp.setdefault(opp_id, []).append(rm.ack_id)

    success_ack_ids: list[str] = []
    failed_opp_ids: list[str] = []

    pipeline = RagPipeline()
    for opp_id, ack_ids in ack_ids_by_opp.items():
        try:
            pipeline.run_one(opp_id)
            success_ack_ids.extend(ack_ids)
        except Exception as exc:
            failed_opp_ids.append(opp_id)
            logger.exception("FAILED opp_id={} error={}", opp_id, exc)

    if success_ack_ids:
        subscriber.acknowledge(
            request={"subscription": sub_path, "ack_ids": success_ack_ids}
        )
        logger.info("ACKed {} messages", len(success_ack_ids))

    return (
        json.dumps({
            "status": "done",
            "pulled": len(received),
            "unique_opp_ids": len(ack_ids_by_opp),
            "failed_opp_ids": failed_opp_ids,
            "acked_messages": len(success_ack_ids),
        }),
        200,
        {"Content-Type": "application/json"},
    )
