"""Answer generation pipeline: retrieval output → LangGraph agent → AnswerBatch.

Accepts the retrieval cloud function output format (opportunity_id, retrievals),
runs the LangGraph agent pipeline, and returns the merged answer set as a dict
suitable for JSON serialization.

Input format (retrieval CF output):
  {
    "opportunity_id": "oid1023",
    "retrievals": {
      "QID-001": [{"text": "...", "source": "...", "source_type": "...", "similarity_score": 0.9, ...}],
      ...
    }
  }

Output format:
  {"_meta": {...}, "answers": {"QID-001": {...}, ...}}

GCS (under ``{opportunity_id}/responses/``) names files with the opportunity id:
``oid_<sanitized_opportunity_id>_extract_api_payload_<timestamp>.json`` and
``oid_<sanitized_opportunity_id>_results_<timestamp>.json``. Legacy blobs may use
``dor_*`` or ``opp_*`` prefixes; use ``Storage.list_response_objects`` /
``read_response_object`` when listing.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

from src.services.agent.batch_registry import get_batches
from src.services.agent.confidence import compute_question_confidence
from src.services.agent.field_loader import load_batch_fields
from src.services.agent.form_output import build_full_answers_payload
from src.services.agent.graph import (
    persist_rag_answers_from_agent_output,
    run as agent_run,
    run_async as agent_run_async,
)
from src.services.agent.types import RetrievedChunk
from src.services.database_manager.answer_generation_lock import (
    AnswerGenerationAlreadyRunningError,
    hold_answer_generation_db_lock,
)
from src.services.database_manager.connection import get_db_connection
from src.services.database_manager.opportunity_state import (
    refresh_opportunity_pipeline_state,
)
from src.services.database_manager.rag_data_service import RagDataService
from src.services.storage.service import Storage
from src.utils.logger import get_logger


logger = get_logger(__name__)


class OpportunityLockedError(Exception):
    """Raised when answer-generation is requested for a locked opportunity."""


def _assert_opportunity_is_active(opportunity_id: str) -> None:
    oid = (opportunity_id or "").strip()
    if not oid:
        raise ValueError("opportunity_id is required")

    # One-shot retry on transient DB network errors: Cloud SQL can drop an idle
    # pooled socket between pre-ping and the real query, producing an
    # ``InterfaceError: network error`` / ``BrokenPipeError`` on the first execute.
    last_exc: Exception | None = None
    for attempt in range(2):
        con = get_db_connection()
        try:
            cur = con.cursor()
            cur.execute(
                """
                SELECT is_active
                FROM opportunities
                WHERE opportunity_id = %s
                LIMIT 1
                """,
                (oid,),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError("Opportunity not found")
            if not bool(row[0]):
                raise OpportunityLockedError("Opportunity is locked")
            return
        except (ValueError, OpportunityLockedError):
            raise
        except Exception as exc:
            if not _is_transient_db_network_error(exc) or attempt == 1:
                raise
            last_exc = exc
            logger.warning(
                "Transient DB network error on is_active check for {}; retrying once: {}",
                oid,
                exc,
            )
        finally:
            try:
                con.close()
            except Exception:
                pass
    if last_exc is not None:
        raise last_exc


def _is_transient_db_network_error(exc: BaseException) -> bool:
    """True if ``exc`` looks like a transient Postgres connection drop we can safely retry."""
    if isinstance(exc, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError)):
        return True
    try:
        from pg8000.exceptions import InterfaceError as _PgInterfaceError

        if isinstance(exc, _PgInterfaceError):
            return True
    except Exception:
        pass
    msg = str(exc).lower()
    return "network error" in msg or "broken pipe" in msg or "connection reset" in msg


def _gcs_response_oid_segment(opportunity_id: str) -> str:
    """Sanitize opportunity_id for a safe GCS object name segment."""
    s = (opportunity_id or "").strip()
    if not s:
        return "unknown"
    for a, b in (("/", "_"), ("\\", "_"), ("\n", "_"), ("\r", "_"), ("\t", "_")):
        s = s.replace(a, b)
    s = "_".join(s.split())
    return s or "unknown"


def _gcs_response_filenames(opportunity_id: str, ts: str) -> tuple[str, str]:
    """Return (extract_payload_filename, results_filename) under responses/."""
    seg = _gcs_response_oid_segment(opportunity_id)
    return (
        f"oid_{seg}_extract_api_payload_{ts}.json",
        f"oid_{seg}_results_{ts}.json",
    )


def _citation_from_basis(ab: dict) -> dict:
    """Build a single citation dict for the extract API from answer_basis/conflict_detail."""
    source_file = ab.get("source_file")
    source_doc = Path(source_file).name if source_file else ab.get("source", "unknown")
    return {
        "source_document": source_doc,
        "source_chunk": ab.get("excerpt") or "",
        "chunk_id": ab.get("chunk_id") or "",
        "source_type": ab.get("source_type") or "unknown",
        "source_file": source_file or "",
        # similarity_score comes from per-chunk confidence_score in answer_basis
        "similarity_score": ab.get("confidence_score"),
        "rerank_score": ab.get("rerank_score"),
    }


def _citation_from_form_output(c: dict) -> dict:
    """Convert form_output citation to answer_basis format."""
    return {
        "source": c.get("source_document", "unknown"),
        "excerpt": c.get("source_chunk", ""),
        "source_type": c.get("source_type", "unknown"),
        "chunk_id": c.get("chunk_id", ""),
        "source_file": c.get("source_file", ""),
        # similarity_score comes from confidence_score in form_output citations
        "similarity_score": c.get("confidence_score"),
        "rerank_score": c.get("rerank_score"),
    }


def _build_extract_payload(
    opportunity_id: str, answers_serialised: dict[str, dict]
) -> dict:
    """Build the POST /api/ai/extract request payload from pipeline answers."""
    answers_list: list[dict] = []
    for q_id, ans in answers_serialised.items():
        if ans.get("error"):
            answers_list.append({
                "question_id": q_id,
                "answer_value": None,
                "confidence_score": 0.0,
                "citations": [],
                "conflicts": [],
            })
            continue

        if ans.get("conflict"):
            conflict_details = ans.get("conflict_details", [])
            conflicts = [
                {
                    "answer_value": cd.get("value", ""),
                    "confidence_score": cd.get("confidence_score") or 0.0,
                    "citations": [_citation_from_basis(cd)],
                }
                for cd in conflict_details
            ]
            answers_list.append({
                "question_id": q_id,
                "answer_value": None,
                "confidence_score": 0.0,
                "citations": [],
                "conflicts": conflicts,
            })
        else:
            answer_basis = ans.get("answer_basis", [])
            citations = [_citation_from_basis(ab) for ab in answer_basis]
            confidence = compute_question_confidence(answer_basis)
            answers_list.append({
                "question_id": q_id,
                "answer_value": ans.get("answer"),
                "confidence_score": confidence,
                "citations": citations,
                "conflicts": [],
            })

    return {
        "opportunity_id": opportunity_id or "unknown",
        "answers": answers_list,
    }


def _parse_retrievals(raw: dict) -> dict[str, list[RetrievedChunk]]:
    """Parse retrieval CF output into ChunksByQuestion."""
    chunks_raw = raw.get("retrievals")
    if chunks_raw is None:
        raise ValueError(
            "request body must include 'retrievals' (retrieval CF output format)"
        )
    if not isinstance(chunks_raw, dict):
        raise ValueError(
            "retrievals must be a JSON object keyed by q_id (e.g. OPP-001)"
        )

    result: dict[str, list[RetrievedChunk]] = {}
    for q_id, chunk_list in chunks_raw.items():
        if not isinstance(chunk_list, list):
            raise ValueError(f"retrievals[{q_id!r}] must be a list of chunk objects")
        result[q_id] = [RetrievedChunk.model_validate(c) for c in chunk_list]
    return result


def _get_question_text_map() -> dict[str, str]:
    """Build q_id -> question text lookup from all batches."""
    result: dict[str, str] = {}
    for b in get_batches():
        for f in load_batch_fields(b.batch_id):
            result[f.q_id] = f.question or f.q_id
    return result


def _agent_output_to_answers_serialised(
    opportunity_id: str,
    agent_output: dict,
) -> dict[str, dict]:
    """Transform LangGraph agent output to answers_serialised format for API compatibility."""
    final_answers = agent_output.get("final_answers") or {}
    candidate_answers = agent_output.get("candidate_answers") or []
    accumulated = agent_output.get("accumulated_conflict_alternatives") or {}

    form_payload = build_full_answers_payload(
        opportunity_id, final_answers, candidate_answers, accumulated
    )
    form_answers = form_payload.get("answers", [])

    question_text_map = _get_question_text_map()
    answers_serialised: dict[str, dict] = {}

    for item in form_answers:
        q_id = item.get("question_id", "")
        if not q_id:
            continue
        answer_value = item.get("answer_value")
        citations = item.get("citations", [])
        conflicts_list = item.get("conflicts", [])

        answer_basis = [_citation_from_form_output(c) for c in citations]
        has_conflict = len(conflicts_list) > 0

        entry: dict = {
            "question": question_text_map.get(q_id, q_id),
            "answer": answer_value,
            "conflict": has_conflict,
        }
        if has_conflict:
            conflict_details = []
            for c in conflicts_list:
                first_citation = (c.get("citations") or [{}])[0]
                conflict_details.append({
                    "value": c.get("answer_value", ""),
                    "source": first_citation.get("source_document", ""),
                    "excerpt": first_citation.get("source_chunk", ""),
                    "source_type": first_citation.get("source_type", ""),
                    "confidence_score": c.get("confidence_score"),
                    "source_file": first_citation.get("source_file"),
                    "chunk_id": first_citation.get("chunk_id"),
                    "rerank_score": first_citation.get("rerank_score"),
                })
            entry["conflict_details"] = conflict_details
        if answer_basis:
            entry["answer_basis"] = answer_basis
        answers_serialised[q_id] = entry

    return answers_serialised


class AnswerGenerationPipeline:
    """Orchestrates opportunities Q&A: retrieval output → LangGraph agent → AnswerBatch."""

    def __init__(self, use_cache: bool = True) -> None:
        self._use_cache = use_cache

    def run(self, body: dict) -> dict:
        """Run the answer generation pipeline on retrieval output.

        Args:
            body: Retrieval CF output dict with ``opportunity_id`` and ``retrievals``.
            Optional smoke/testing keys (not used by Cloud Run contract):
            ``_filter_question_ids`` — list of ``q_id`` strings; only those keys are
            kept from ``retrievals``. Optional ``_smoke_skip_empty_batches`` — if
            true, worker batches with no chunks after partitioning are not sent to
            the LLM.

        Returns:
            Dict with ``_meta`` and ``answers``, ready for JSON serialization.

        Raises:
            ValueError: If body is invalid (missing retrievals, wrong shape).
        """
        opportunity_id = body.get("opportunity_id") or ""
        extras = {"opportunity_id": opportunity_id} if opportunity_id else {}
        lx = logger.bind(**extras)

        _assert_opportunity_is_active(opportunity_id)

        with hold_answer_generation_db_lock(opportunity_id):
            lx.info("Answer generation pipeline started")
            if opportunity_id:
                try:
                    RagDataService().update_opportunity_status(
                        opportunity_id=opportunity_id,
                        status="IN_PROGRESS",
                    )
                except Exception:
                    lx.exception("Failed to mark opportunity in progress")

            retrievals = dict(body.get("retrievals") or {})
            q_filter = body.get("_filter_question_ids")
            if q_filter:
                wanted = {str(x).strip() for x in q_filter if str(x).strip()}
                retrievals = {k: v for k, v in retrievals.items() if k in wanted}
            skip_empty = bool(body.get("_smoke_skip_empty_batches"))

            chunks = _parse_retrievals({
                "opportunity_id": opportunity_id,
                "retrievals": retrievals,
            })
            if not chunks:
                lx.warning("Pipeline: retrievals empty — will run with empty context")

            start = datetime.now()
            try:
                agent_output = agent_run(
                    opportunity_id,
                    retrievals,
                    use_async=True,
                    skip_empty_batches=skip_empty,
                )
                pipeline_version_id = str(uuid.uuid4())
                persist_rag_answers_from_agent_output(
                    opportunity_id,
                    agent_output,
                    retrievals,
                    pipeline_version_id,
                )
                elapsed_s = (datetime.now() - start).total_seconds()

                answers_serialised = _agent_output_to_answers_serialised(
                    opportunity_id, agent_output
                )

                error_ids = [qid for qid, v in answers_serialised.items() if v.get("error")]
                meta = {
                    "opportunity_id": opportunity_id,
                    "timestamp": start.isoformat(timespec="seconds"),
                    "elapsed_seconds": round(elapsed_s, 1),
                    "total_answers": len(answers_serialised),
                    "error_count": len(error_ids),
                    "failed_question_ids": sorted(error_ids),
                }

                lx.info(
                    "Answer generation pipeline completed: {} answers, {} errors, {:.1f}s",
                    len(answers_serialised),
                    len(error_ids),
                    elapsed_s,
                )
                if error_ids:
                    lx.warning("Failed question IDs: {}", ", ".join(sorted(error_ids)))

                extract_payload = _build_extract_payload(opportunity_id, answers_serialised)
                file_ts = start.strftime("%Y%m%d_%H%M%S")
                extract_fn, results_fn = _gcs_response_filenames(opportunity_id, file_ts)
                filename = extract_fn
                content = json.dumps(extract_payload, indent=2, ensure_ascii=False)
                uri = Storage().write_response(opportunity_id, filename, content)
                lx.info("Wrote extract API request payload to GCS: {}", uri)

                result = {"_meta": meta, "answers": answers_serialised}

                if opportunity_id:
                    refresh_opportunity_pipeline_state(opportunity_id, "extracted")

                if opportunity_id:
                    try:
                        RagDataService().update_opportunity_status(
                            opportunity_id=opportunity_id,
                            status="COMPLETED",
                        )
                    except Exception:
                        lx.exception("Failed to mark opportunity completed")
                if opportunity_id:
                    try:
                        filename = results_fn
                        content = json.dumps(result, indent=2, ensure_ascii=False)
                        uri = Storage().write_response(opportunity_id, filename, content)
                        lx.info("Wrote answer results to GCS: {}", uri)
                    except Exception as e:
                        lx.warning("GCS write of answer results failed (continuing): {}", e)

                return result
            except Exception:
                if opportunity_id:
                    try:
                        RagDataService().update_opportunity_status(
                            opportunity_id=opportunity_id,
                            status="FAILED",
                        )
                    except Exception:
                        lx.exception("Failed to mark opportunity failed")
                raise

    async def run_async(self, body: dict) -> dict:
        """Async version for use from FastAPI (avoids asyncio.run in event loop)."""
        opportunity_id = body.get("opportunity_id") or ""
        extras = {"opportunity_id": opportunity_id} if opportunity_id else {}
        lx = logger.bind(**extras)

        _assert_opportunity_is_active(opportunity_id)

        with hold_answer_generation_db_lock(opportunity_id):
            lx.info("Answer generation pipeline started")
            if opportunity_id:
                try:
                    RagDataService().update_opportunity_status(
                        opportunity_id=opportunity_id,
                        status="IN_PROGRESS",
                    )
                except Exception:
                    lx.exception("Failed to mark opportunity in progress")

            retrievals = dict(body.get("retrievals") or {})
            q_filter = body.get("_filter_question_ids")
            if q_filter:
                wanted = {str(x).strip() for x in q_filter if str(x).strip()}
                retrievals = {k: v for k, v in retrievals.items() if k in wanted}
            skip_empty = bool(body.get("_smoke_skip_empty_batches"))

            chunks = _parse_retrievals({
                "opportunity_id": opportunity_id,
                "retrievals": retrievals,
            })
            if not chunks:
                lx.warning("Pipeline: retrievals empty — will run with empty context")

            start = datetime.now()
            try:
                agent_output = await agent_run_async(
                    opportunity_id,
                    retrievals,
                    skip_empty_batches=skip_empty,
                )
                pipeline_version_id = str(uuid.uuid4())
                persist_rag_answers_from_agent_output(
                    opportunity_id,
                    agent_output,
                    retrievals,
                    pipeline_version_id,
                )
                elapsed_s = (datetime.now() - start).total_seconds()

                answers_serialised = _agent_output_to_answers_serialised(
                    opportunity_id, agent_output
                )

                error_ids = [qid for qid, v in answers_serialised.items() if v.get("error")]
                meta = {
                    "opportunity_id": opportunity_id,
                    "timestamp": start.isoformat(timespec="seconds"),
                    "elapsed_seconds": round(elapsed_s, 1),
                    "total_answers": len(answers_serialised),
                    "error_count": len(error_ids),
                    "failed_question_ids": sorted(error_ids),
                }

                lx.info(
                    "Answer generation pipeline completed: {} answers, {} errors, {:.1f}s",
                    len(answers_serialised),
                    len(error_ids),
                    elapsed_s,
                )
                if error_ids:
                    lx.warning("Failed question IDs: {}", ", ".join(sorted(error_ids)))

                extract_payload = _build_extract_payload(opportunity_id, answers_serialised)
                file_ts = start.strftime("%Y%m%d_%H%M%S")
                extract_fn, results_fn = _gcs_response_filenames(opportunity_id, file_ts)
                filename = extract_fn
                content = json.dumps(extract_payload, indent=2, ensure_ascii=False)
                uri = Storage().write_response(opportunity_id, filename, content)
                lx.info("Wrote extract API request payload to GCS: {}", uri)

                result = {"_meta": meta, "answers": answers_serialised}

                if opportunity_id:
                    refresh_opportunity_pipeline_state(opportunity_id, "extracted")

                if opportunity_id:
                    try:
                        RagDataService().update_opportunity_status(
                            opportunity_id=opportunity_id,
                            status="COMPLETED",
                        )
                    except Exception:
                        lx.exception("Failed to mark opportunity completed")
                if opportunity_id:
                    try:
                        filename = results_fn
                        content = json.dumps(result, indent=2, ensure_ascii=False)
                        uri = Storage().write_response(opportunity_id, filename, content)
                        lx.info("Wrote answer results to GCS: {}", uri)
                    except Exception as e:
                        lx.warning("GCS write of answer results failed (continuing): {}", e)

                return result
            except Exception:
                if opportunity_id:
                    try:
                        RagDataService().update_opportunity_status(
                            opportunity_id=opportunity_id,
                            status="FAILED",
                        )
                    except Exception:
                        lx.exception("Failed to mark opportunity failed")
                raise
