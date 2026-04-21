"""LangGraph state schema for agent form-filling pipeline.

State flows through: run_all_workers → validate → detect_conflicts
→ [recall_workers → run_all_workers | select_final] → form_output → END.
"""

from __future__ import annotations

from typing import Any, TypedDict

from src.services.agent.types import ChunksByQuestion


class CandidateSource(TypedDict, total=False):
    """One source supporting a candidate answer."""

    source: str
    chunk_id: str | None
    retrieval_score: float
    rerank_score: float | None
    excerpt: str | None
    source_type: str | None
    source_file: str | None


class CandidateAnswer(TypedDict, total=False):
    """One worker's candidate answer for a question."""

    question_id: str
    agent_id: str
    candidate_answer: Any
    confidence: float
    sources: list[CandidateSource]
    conflict: bool
    conflict_reason: str | None
    conflict_details: list[dict]
    answer_basis: list[dict]


class FormAnswer(TypedDict):
    """Single entry in final form answers array (BRD §18)."""

    question_id: str
    answer: Any


class AgentState(TypedDict, total=False):
    """State for the LangGraph agent pipeline.

    All keys optional in TypedDict to allow partial updates per node.
    """

    opportunity_id: str
    retrievals: ChunksByQuestion
    candidate_answers: list[CandidateAnswer]
    conflicts: dict[str, str]
    accumulated_conflict_alternatives: dict[str, list[dict[str, Any]]]
    recall_round: int
    recall_context: dict[str, Any] | None
    final_answers: dict[str, dict[str, Any]]
    form_output: dict[str, Any]
    validation_errors: dict[str, str]
    skip_empty_batches: bool


# Alias for backward compatibility
AgentV2State = AgentState
