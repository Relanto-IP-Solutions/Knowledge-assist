"""LangGraph StateGraph for agent: run_all_workers → validate → detect_conflicts → … → form_output → END.

DB persistence for RAG answers is performed once per HTTP/pipeline run by
``persist_rag_answers_from_agent_output`` in :mod:`src.services.pipelines.agent_pipeline`,
not inside the ``form_output`` node.
"""

from __future__ import annotations

import asyncio
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from configs.settings import get_settings
from src.services.agent.form_output import (
    answer_dedupe_key,
    build_full_answers_payload,
    extract_conflict_alternatives,
    norm_val_str,
    prefer_answer_display,
    write_form_output_gcs,
)
from src.services.agent.state import AgentState
from src.services.agent.supervisor import (
    build_recall_context,
    detect_conflicts as detect_conflicts_fn,
    select_final_answers,
    validate_candidates,
)
from src.services.agent.types import ChunksByQuestion, RetrievedChunk
from src.services.agent.workers import partition_by_batch, run_all_workers
from src.services.database_manager.rag_data_service import RagDataService
from src.utils.logger import get_logger


logger = get_logger(__name__)

_agent_graph: AgentGraph | None = None


def _parse_retrievals(retrievals: dict[str, Any]) -> ChunksByQuestion:
    """Convert retrieval output (list of dicts per q_id) to ChunksByQuestion."""
    result: ChunksByQuestion = {}
    for q_id, chunk_list in (retrievals or {}).items():
        if not isinstance(chunk_list, list):
            result[q_id] = []
            continue
        result[q_id] = [RetrievedChunk.model_validate(c) for c in chunk_list]
    return result


async def _run_all_workers_node(state: AgentState) -> dict[str, Any]:
    """LangGraph node: run all 6 workers in parallel and set candidate_answers."""
    opportunity_id = state.get("opportunity_id") or ""
    retrievals = state.get("retrievals") or {}
    recall_context = state.get("recall_context")
    partitioned = partition_by_batch(retrievals)
    use_cache = get_settings().agent.use_cache
    skip_empty = bool(state.get("skip_empty_batches"))
    candidates = await run_all_workers(
        partitioned,
        use_cache=use_cache,
        recall_context=recall_context,
        skip_empty_batches=skip_empty,
    )
    logger.bind(opportunity_id=opportunity_id).info(
        "run_all_workers completed: {} candidates",
        len(candidates),
    )
    return {
        "candidate_answers": candidates,
        "recall_context": None,
    }


def _validate_node(state: AgentState) -> dict[str, Any]:
    """LangGraph node: validate candidates; set validation_errors."""
    errors = validate_candidates(state)
    return {"validation_errors": errors}


def _detect_conflicts_node(state: AgentState) -> dict[str, Any]:
    """LangGraph node: detect conflicts; set conflicts dict."""
    conflicts = detect_conflicts_fn(state)
    return {"conflicts": conflicts}


def _route_after_conflicts(
    state: AgentState,
) -> Literal["recall_workers", "select_final"]:
    """Route: recall if we have conflicts and recall_round < max, else select_final."""
    conflicts = state.get("conflicts") or {}
    recall_round = state.get("recall_round") or 0
    max_recall = get_settings().agent.max_recall_rounds
    if conflicts and recall_round < max_recall:
        return "recall_workers"
    return "select_final"


def _recall_workers_node(state: AgentState) -> dict[str, Any]:
    """LangGraph node: set recall_context, increment recall_round, accumulate pre-recall conflicts."""
    ctx = build_recall_context(state)
    recall_round = (state.get("recall_round") or 0) + 1
    conflicts = state.get("conflicts") or {}
    candidate_answers = state.get("candidate_answers") or []
    accumulated = dict(state.get("accumulated_conflict_alternatives") or {})

    if conflicts and candidate_answers:
        this_round = extract_conflict_alternatives(candidate_answers, set(conflicts))
        for qid, entries in this_round.items():
            existing = list(accumulated.get(qid, []))
            seen = {norm_val_str(e.get("answer_value")) for e in existing}
            for ent in entries:
                v_str = norm_val_str(ent.get("answer_value"))
                if v_str and v_str not in seen:
                    seen.add(v_str)
                    existing.append(ent)
            accumulated[qid] = existing

    return {
        "accumulated_conflict_alternatives": accumulated,
        "recall_context": ctx,
        "recall_round": recall_round,
    }


def _select_final_node(state: AgentState) -> dict[str, Any]:
    """LangGraph node: select final answer per question; set final_answers."""
    final = select_final_answers(state)
    return {"final_answers": final}


def _form_output_node(state: AgentState) -> dict[str, Any]:
    """LangGraph node: build full answers payload and write to GCS."""
    opportunity_id = state.get("opportunity_id") or ""
    final_answers = state.get("final_answers") or {}
    candidate_answers = state.get("candidate_answers") or []
    accumulated = state.get("accumulated_conflict_alternatives") or {}
    form_output = build_full_answers_payload(
        opportunity_id, final_answers, candidate_answers, accumulated
    )
    write_form_output_gcs(opportunity_id, form_output)

    return {"form_output": form_output}


def persist_rag_answers_from_agent_output(
    opportunity_id: str,
    agent_output: dict[str, Any],
    retrievals: dict[str, Any],
    pipeline_version_id: str,
) -> None:
    """Persist form_output from a completed agent run.

    Call exactly once per :class:`~src.services.pipelines.agent_pipeline.AnswerGenerationPipeline`
    invocation so the DB does not get duplicate versions if the graph ``form_output`` step were
    ever executed more than once.
    """
    oid = (opportunity_id or "").strip()
    if not oid:
        return
    form_output = agent_output.get("form_output")
    if form_output is None:
        return
    _persist_rag_answers_to_db(oid, form_output, retrievals, pipeline_version_id)


def _citation_for_persistence(citation: dict[str, Any]) -> dict[str, Any]:
    """Map form_output citation shape to DB citation shape."""
    return {
        "source_type": citation.get("source_type", "unknown"),
        "source_file": citation.get("source_file")
        or citation.get("source_document")
        or "",
        "source_name": citation.get("source_name") or citation.get("source_document"),
        "context": citation.get("context"),
        "page_number": citation.get("page_number"),
        "timestamp_str": citation.get("timestamp_str") or citation.get("timestamp"),
        "speaker": citation.get("speaker"),
        "chunk_id": citation.get("chunk_id") or "",
        "quote": citation.get("source_chunk") or citation.get("excerpt") or "",
        "relevance_score": citation.get("confidence_score")
        or citation.get("similarity_score")
        or 0.0,
    }


def _build_answers_list_for_persistence(
    payload: dict[str, Any],
) -> tuple[list[dict[str, Any]], bool, int]:
    """Convert one form_output answer payload into DB answer candidates."""
    answers_list: list[dict[str, Any]] = []
    dedupe_key_to_index: dict[str, int] = {}

    def add_answer(
        value: Any,
        *,
        confidence_score: float,
        reasoning: str,
        citations: list[dict[str, Any]],
    ) -> None:
        key = answer_dedupe_key(value)
        if not key:
            return
        display = str(value).strip()
        if key in dedupe_key_to_index:
            idx = dedupe_key_to_index[key]
            prev = answers_list[idx]["answer_text"]
            prev_s = "" if prev is None else str(prev).strip()
            answers_list[idx]["answer_text"] = prefer_answer_display(display, prev_s)
            return
        dedupe_key_to_index[key] = len(answers_list)
        answers_list.append({
            "answer_text": display,
            "confidence_score": confidence_score,
            "reasoning": reasoning,
            "citations": [_citation_for_persistence(c) for c in citations],
        })

    answer_value = payload.get("answer_value")
    has_direct_answer = answer_value is not None and str(answer_value).strip() != ""

    if has_direct_answer:
        add_answer(
            answer_value,
            confidence_score=payload.get("confidence_score") or 0.0,
            reasoning="FINAL_ANSWER",
            citations=payload.get("citations") or [],
        )

    for conflict_entry in payload.get("conflicts") or []:
        conflict_value = conflict_entry.get("answer_value")
        if conflict_value is None or str(conflict_value).strip() == "":
            continue
        add_answer(
            conflict_value,
            confidence_score=conflict_entry.get("confidence_score") or 0.0,
            reasoning="CONFLICT_ALT",
            citations=conflict_entry.get("citations") or [],
        )

    question_has_conflicts = len(answers_list) > 1

    if not answers_list and not has_direct_answer:
        answers_list.append({
            "answer_text": None,
            "confidence_score": 0.0,
            "reasoning": "NO_ANSWER_GENERATED",
            "citations": [],
        })

    explicit_conflict_count = len(answers_list) if question_has_conflicts else 0
    return answers_list, question_has_conflicts, explicit_conflict_count


def _persist_rag_answers_to_db(
    opportunity_id: str,
    form_output: dict[str, Any],
    retrievals: dict[str, Any],
    pipeline_version_id: str,
) -> None:
    """Persist final answer-generation payload to the database.

    Rules:
      - If ``answer_value`` exists for a question, insert it as one candidate.
      - If ``conflicts`` has N distinct entries, insert those as additional candidates.
      - Conflict groups are then created from active answers for that question.
    """
    answers_by_question: dict[str, dict[str, Any]] = {}
    for entry in (form_output or {}).get("answers", []):
        qid = entry.get("question_id")
        if qid:
            answers_by_question[qid] = entry

    logger.info(
        "Persisting RAG answers to DB | opportunity_id={} questions_in_payload={}",
        opportunity_id,
        len(answers_by_question),
    )

    svc = RagDataService()

    # Update opportunity status/metrics for an already seeded opportunity row.
    # Do not attempt init here because this runtime path may not have a numeric owner_id.
    try:
        # Calculate doc_count from retrievals
        unique_docs = set()
        for chunk_list in retrievals.values():
            for chunk in chunk_list:
                if hasattr(chunk, "get"):
                    doc_id = chunk.get("document_id") or chunk.get("source")
                else:
                    doc_id = getattr(chunk, "document_id", None) or getattr(
                        chunk, "source", None
                    )
                if doc_id:
                    unique_docs.add(doc_id)

        doc_count = len(unique_docs)

        svc.update_opportunity_status(
            opportunity_id=opportunity_id,
            status="IN_PROGRESS",
            doc_count=doc_count,
            processed_count=doc_count,  # assuming processed if we have chunks
        )
    except Exception:
        logger.warning(
            "Opportunity status update failed (continuing) | opportunity_id={}",
            opportunity_id,
        )

    # One version number for the whole batch so answers.current_version matches across
    # all questions from this pipeline run (not per-question MAX(version)+1).
    run_version: int | None = None
    try:
        run_version = svc.allocate_next_opportunity_run_version(opportunity_id)
    except Exception:
        logger.exception(
            "allocate_next_opportunity_run_version failed; using per-question version increments | opportunity_id={}",
            opportunity_id,
        )

    # Best-effort: drop uq_answers_opp_question once per batch (needs ALTER). If the DB user
    # cannot ALTER, save_rag_answers still falls back to UPDATE-in-place per question.
    try:
        svc.ensure_answers_allows_multiple_rows_per_question()
    except Exception:
        logger.warning(
            "ensure_answers_allows_multiple_rows_per_question failed (continuing; per-question fallback may apply) | opportunity_id={}",
            opportunity_id,
        )

    persisted_ok = 0
    persist_failed = 0
    for question_id, payload in answers_by_question.items():
        (
            answers_list,
            question_has_conflicts,
            explicit_conflict_count,
        ) = _build_answers_list_for_persistence(payload)

        try:
            total_citations = sum(len(a.get("citations") or []) for a in answers_list)
            logger.info(
                "Prepared answer payload for DB | opportunity_id={} question_id={} answers={} citations={}",
                opportunity_id,
                question_id,
                len(answers_list),
                total_citations,
            )
            svc.save_rag_answers(
                opportunity_id=opportunity_id,
                question_id=question_id,
                question_text=question_id,  # question_id as placeholder; real text from sase_questions
                answers_list=answers_list,
                version_id=pipeline_version_id,
                has_conflicts=question_has_conflicts,
                conflict_count=explicit_conflict_count if question_has_conflicts else 0,
                run_version=run_version,
                insert_new_answer_row=True,
            )
            persisted_ok += 1
        except Exception:
            # Non-fatal: log and continue — don't block form_output on DB errors
            persist_failed += 1
            logger.exception(
                "Failed to persist RAG answers to DB — question_id={} opportunity_id={}",
                question_id,
                opportunity_id,
            )

    logger.info(
        "Finished persisting RAG answers | opportunity_id={} ok={} failed={} payload_questions={}",
        opportunity_id,
        persisted_ok,
        persist_failed,
        len(answers_by_question),
    )


class AgentGraph:
    """LangGraph StateGraph for the opportunities Q&A agent pipeline."""

    def __init__(self) -> None:
        self._compiled_graph: Any = None

    def build(self) -> Any:
        """Build and return the compiled StateGraph."""
        builder = StateGraph(AgentState)

        builder.add_node("run_all_workers", _run_all_workers_node)
        builder.add_node("validate", _validate_node)
        builder.add_node("detect_conflicts", _detect_conflicts_node)
        builder.add_node("recall_workers", _recall_workers_node)
        builder.add_node("select_final", _select_final_node)
        builder.add_node("form_output", _form_output_node)

        builder.add_edge(START, "run_all_workers")
        builder.add_edge("run_all_workers", "validate")
        builder.add_edge("validate", "detect_conflicts")
        builder.add_conditional_edges("detect_conflicts", _route_after_conflicts)
        builder.add_edge("recall_workers", "run_all_workers")
        builder.add_edge("select_final", "form_output")
        builder.add_edge("form_output", END)

        return builder.compile()

    def get_graph(self) -> Any:
        """Return the compiled agent graph (singleton)."""
        if self._compiled_graph is None:
            self._compiled_graph = self.build()
        return self._compiled_graph

    def run(
        self,
        opportunity_id: str,
        retrievals: dict[str, Any],
        *,
        use_async: bool = True,
        skip_empty_batches: bool = False,
    ) -> dict[str, Any]:
        """Run the agent pipeline for one opportunity (sync entry point)."""
        logger.bind(opportunity_id=opportunity_id).info("Starting agent pipeline")
        chunks = _parse_retrievals(retrievals)
        initial: AgentState = {
            "opportunity_id": opportunity_id,
            "retrievals": chunks,
            "candidate_answers": [],
            "conflicts": {},
            "accumulated_conflict_alternatives": {},
            "recall_round": 0,
            "recall_context": None,
            "skip_empty_batches": skip_empty_batches,
        }
        graph = self.get_graph()
        if use_async:
            final = asyncio.run(graph.ainvoke(initial))
        else:
            final = graph.invoke(initial)
        logger.bind(
            opportunity_id=opportunity_id,
            final_answers_count=len(final.get("final_answers") or {}),
        ).info("Agent pipeline completed")
        return dict(final)

    async def run_async(
        self,
        opportunity_id: str,
        retrievals: dict[str, Any],
        *,
        skip_empty_batches: bool = False,
    ) -> dict[str, Any]:
        """Run the agent pipeline (async entry point)."""
        logger.bind(opportunity_id=opportunity_id).info("Starting agent pipeline")
        chunks = _parse_retrievals(retrievals)
        initial: AgentState = {
            "opportunity_id": opportunity_id,
            "retrievals": chunks,
            "candidate_answers": [],
            "conflicts": {},
            "accumulated_conflict_alternatives": {},
            "recall_round": 0,
            "recall_context": None,
            "skip_empty_batches": skip_empty_batches,
        }
        graph = self.get_graph()
        final = await graph.ainvoke(initial)
        logger.bind(
            opportunity_id=opportunity_id,
            final_answers_count=len(final.get("final_answers") or {}),
        ).info("Agent pipeline completed")
        return dict(final)


def get_agent_graph() -> AgentGraph:
    """Return the singleton AgentGraph instance."""
    global _agent_graph
    if _agent_graph is None:
        _agent_graph = AgentGraph()
    return _agent_graph


def build_graph() -> Any:
    """Build and return the compiled StateGraph."""
    return get_agent_graph().build()


def get_graph() -> Any:
    """Return the compiled agent graph (singleton)."""
    return get_agent_graph().get_graph()


def run(
    opportunity_id: str,
    retrievals: dict[str, Any],
    *,
    use_async: bool = True,
    skip_empty_batches: bool = False,
) -> dict[str, Any]:
    """Run the agent pipeline for one opportunity."""
    return get_agent_graph().run(
        opportunity_id,
        retrievals,
        use_async=use_async,
        skip_empty_batches=skip_empty_batches,
    )


async def run_async(
    opportunity_id: str,
    retrievals: dict[str, Any],
    *,
    skip_empty_batches: bool = False,
) -> dict[str, Any]:
    """Run the agent pipeline (async)."""
    return await get_agent_graph().run_async(
        opportunity_id, retrievals, skip_empty_batches=skip_empty_batches
    )
