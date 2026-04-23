"""Cloud Function / Cloud Run: answer-generation — HTTP trigger.

Runs AnswerGenerationPipeline: retrievals → LangGraph agent → form JSON → GCS.

Trigger:
  HTTP POST. Body: {"opportunity_id": "...", "retrievals": {q_id: [chunks]}}.

Deployment:
  docs/runbooks/answer-generation-cloud-run.md (Cloud Run preferred)

Env vars: GCP_PROJECT_ID, GCS_BUCKET_INGESTION, VERTEX_AI_LOCATION, LLM_MODEL_NAME,
  CLOUDSQL_INSTANCE_CONNECTION_NAME, PG_USER, PG_PASSWORD, PG_DATABASE.
"""

from __future__ import annotations

import json

import functions_framework

from src.services.pipelines.agent_pipeline import (
    AnswerGenerationAlreadyRunningError,
    AnswerGenerationPipeline,
    OpportunityLockedError,
)
from src.utils.logger import get_logger


logger = get_logger(__name__)


@functions_framework.http
def handle_http(request):
    """HTTP entry point — delegates to AnswerGenerationPipeline."""
    extras: dict = {}

    try:
        if request.method != "POST":
            return (
                json.dumps({"error": "Method not allowed"}),
                405,
                {"Content-Type": "application/json"},
            )

        body = request.get_json(silent=True) or {}
        opportunity_id = body.get("opportunity_id") or ""
        extras = {"opportunity_id": opportunity_id} if opportunity_id else {}

        pipeline = AnswerGenerationPipeline(use_cache=True)
        result = pipeline.run(body)

        return (
            json.dumps(result, indent=2, ensure_ascii=False),
            200,
            {"Content-Type": "application/json"},
        )

    except AnswerGenerationAlreadyRunningError as exc:
        logger.bind(**extras).warning("Answer generation rejected (already running): {}", exc)
        return (
            json.dumps({"error": str(exc)}),
            409,
            {"Content-Type": "application/json"},
        )
    except OpportunityLockedError as exc:
        logger.bind(**extras).warning("Answer generation rejected (opportunity locked): {}", exc)
        return (
            json.dumps({"error": str(exc)}),
            409,
            {"Content-Type": "application/json"},
        )
    except ValueError as exc:
        logger.bind(**extras).warning("Answer generation invalid request: {}", exc)
        return (
            json.dumps({"error": str(exc)}),
            400,
            {"Content-Type": "application/json"},
        )
    except Exception as exc:
        logger.bind(**extras).exception("Answer generation failed: {}", exc)
        return (
            json.dumps({"error": str(exc)}),
            500,
            {"Content-Type": "application/json"},
        )
