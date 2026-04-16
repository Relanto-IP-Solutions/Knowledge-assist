"""RAG pipeline: retrieval → answer-generation via HTTP.

Orchestrates RetrievalPipeline and calls the answer-generation Cloud Run service.
Used by the rag-orchestrator Cloud Function.
"""

from __future__ import annotations

import google.auth.transport.requests
import google.oauth2.id_token

from configs.settings import get_settings
from src.services.pipelines.retrieval_pipeline import RetrievalPipeline
from src.services.rag_engine.retrieval.http_client import get_http_session
from src.utils.logger import get_logger

logger = get_logger(__name__)

ANSWER_GEN_TIMEOUT = 540


def _call_answer_generation(url: str, body: dict) -> dict:
    """POST retrieval body to answer-generation Cloud Run with OIDC auth.

    Intentionally **not** wrapped with ``retry_on_transient``: a retry after the
    server has already completed a long-running generation would run the pipeline
    again and insert a second full answer version set for the same opportunity.
    Transient failures should be retried by the caller after inspecting the result,
    or fixed by increasing ``ANSWER_GEN_TIMEOUT``.
    """
    request = google.auth.transport.requests.Request()
    id_token = google.oauth2.id_token.fetch_id_token(request, url)
    headers = {
        "Authorization": f"Bearer {id_token}",
        "Content-Type": "application/json",
    }
    resp = get_http_session().post(
        url, headers=headers, json=body, timeout=ANSWER_GEN_TIMEOUT
    )
    if not resp.ok:
        try:
            err_body = resp.json()
            err_msg = err_body.get("error", err_body.get("detail", str(err_body)))
        except Exception:
            err_msg = resp.text or resp.reason
        logger.bind(opportunity_id=body.get("opportunity_id")).error(
            "answer-generation returned %s: %s",
            resp.status_code,
            err_msg,
            exc_info=True,
        )
        resp.raise_for_status()
    return resp.json()


class RagPipeline:
    """Orchestrates retrieval and answer-generation for one opportunity."""

    def run_one(self, opportunity_id: str) -> dict:
        """Run retrieval, then call answer-generation if URL is configured.

        Returns:
            Answer-generation response if ANSWER_GENERATION_URL is set,
            otherwise retrieval output only (for local testing).
        """
        retrieval_pipeline = RetrievalPipeline()
        result = retrieval_pipeline.process_one_opportunity(opportunity_id)

        answer_gen_url = (get_settings().retrieval.answer_generation_url or "").strip()
        if not answer_gen_url:
            logger.bind(opportunity_id=opportunity_id).debug(
                "ANSWER_GENERATION_URL not set; returning retrieval only"
            )
            return result

        logger.bind(opportunity_id=opportunity_id).info(
            "Calling answer-generation for opportunity_id={}",
            opportunity_id,
        )
        return _call_answer_generation(answer_gen_url, result)
