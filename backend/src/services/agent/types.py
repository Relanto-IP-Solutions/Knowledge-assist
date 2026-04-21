"""Pipeline I/O contracts for the SASE opportunities Q&A agent.

These types define the data flowing into and out of the orchestrator:
  - RetrievedChunk   — one chunk returned by the vector-DB retrieval function
  - ChunksByQuestion — mapping of api_name → chunks; the retrieval contract
  - OpportunityQuestion — a single question the pipeline must answer
  - AnswerResult     — the answer (with conflict metadata) for one question
  - AnswerBatch      — the full set of answers returned to the API caller
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from src.services.agent.field_loader import AnswerBasisItem, ConflictDetail


# Re-export for backward compatibility
AnswerSource = AnswerBasisItem


class RetrievedChunk(BaseModel):
    """One chunk returned by the vector-DB cloud function for a single field.

    The cloud function returns a ``ChunksByQuestion`` dict where each key is a
    question field name (e.g. ``q1_products_covered``) and each value is a list of
    ``RetrievedChunk`` objects ordered by descending similarity score.
    """

    text: str = Field(description="Chunk text content.")
    source: str = Field(
        description="Document or call identifier (e.g. filename, Zoom URL)."
    )
    source_type: str = Field(
        description="Media type, e.g. 'pdf', 'zoom_transcript', 'slack'."
    )
    similarity_score: float = Field(
        default=0.0,
        description="Cosine similarity score from the vector retrieval step.",
    )
    rerank_score: float | None = Field(
        default=None,
        description="Relevance score from Vertex AI reranker.",
    )
    document_id: str | None = Field(
        default=None,
        description="Full GCS path or document identifier from retrieval (e.g. gs://bucket/...).",
    )
    chunk_id: str | None = Field(
        default=None,
        description="Chunk identifier from retrieval (e.g. meeting-1_txt_2).",
    )


ChunksByQuestion = dict[str, list[RetrievedChunk]]
"""Mapping of SASE opportunity ``q_id`` → retrieved chunks for that field.

Keys are the canonical question identifiers from ``sase_questions.q_id``
(e.g. ``"OPP-001"``, ``"OPP-002"``).
Produced by the vector-DB cloud function and consumed by the agent pipeline.
"""


class OpportunityQuestion(BaseModel):
    """A single opportunity question to be answered from context documents."""

    question_id: str
    text: str
    answer_type: str = ""


# Backward-compatible alias (older code may still import this name).
DORQuestion = OpportunityQuestion


class AnswerResult(BaseModel):
    """The agent's answer for a single opportunity question."""

    question_id: str
    question_text: str
    answer: Any | None = None
    conflict: bool = False
    conflict_reason: str | None = Field(
        default=None,
        description="One-sentence explanation of why the conflict was flagged; null when conflict=false.",
    )
    conflict_details: list[ConflictDetail] = Field(default_factory=list)
    answer_basis: list[AnswerBasisItem] = Field(
        default_factory=list,
        description="Source excerpts that directly produced the extracted answer.",
    )
    sources: list[str] = Field(default_factory=list)
    error: str | None = None


class AnswerBatch(BaseModel):
    """Full response for a complete opportunity question set."""

    answers: list[AnswerResult] = Field(default_factory=list)
