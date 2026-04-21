"""PostgreSQL-backed SASE field definition loader.

Data flow
---------
Cloud SQL PostgreSQL (sase_batches, sase_questions, sase_picklist_options)
    sase_batches       → batch metadata (batch_id, batch_order, label, description)
    sase_questions     → FieldDefinition  (one per question; keyed by q_id / api_name)
    sase_picklist_options → options list  (joined onto each FieldDefinition)

``FieldDefinition`` objects are the single runtime representation of every
question.  ``prompt_builder.py`` calls ``load_batch_fields(batch_id)`` to get a
typed list and renders the field table for the system prompt by calling methods
on each object.

Public API
----------
load_batch_fields(batch_id: str) -> list[FieldDefinition]
    Return Pydantic-validated field definitions for the given batch.

build_fields_table(batch_id: str) -> str
    Convenience wrapper — returns a markdown table string for ``batch_id``.

get_field_count(batch_id: str) -> int
    Number of questions in a batch.

get_question_range(batch_id: str) -> tuple[str, str]
    (first_q_id, last_q_id) for the batch — e.g. ('OPP-001', 'OPP-009').
"""

from __future__ import annotations

import re
import types
import typing
from functools import cache, lru_cache
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field, create_model, field_validator, model_validator

from src.services.database_manager import get_db_connection, rows_to_dicts


class FieldDefinition(BaseModel):
    """Complete definition of one SASE opportunity question field, hydrated from PostgreSQL.

    Attributes
    ----------
    q_id:            Primary identifier in the form ``OPP-NNN`` (e.g. ``OPP-001``).
    api_name:        Snake-case Salesforce API name used as the JSON key in LLM
                     output (e.g. ``sase_sd_use_case``).
    question:        Human-readable question text.
    batch_id:        Text FK referencing ``sase_batches.batch_id``
                     (e.g. ``sase_use_case_details``).
    batch_order:     Integer ordering of the batch (1–6).
    answer_type:     Normalised type token — ``'text'``, ``'integer'``, ``'date'``,
                     ``'picklist'``, ``'multi-select'``, or ``'picklist-search'``.
    requirement_type: ``'Required'``, ``'Conditionally Required'``, or ``'Optional'``.
    section_prefix:  Hierarchical section number (e.g. ``'2.1'``); ``None`` for
                     top-level questions.
    seq_in_section:  Question sequence within its section; ``None`` when absent.
    options:         Ordered list of valid answer strings for picklist/multi-select
                     fields; empty for free-text, integer, date, and boolean fields.
    question_prompt:  Optional per-question extraction hint from DB (e.g. prefer
                     most recent source). Included in field payload when non-empty.
    """

    q_id: str
    api_name: str
    question: str = ""
    batch_id: str
    batch_order: int
    answer_type: str = "text"
    requirement_type: str = "Optional"
    section_prefix: str | None = None
    seq_in_section: int | None = None
    options: list[str] = Field(default_factory=list)
    question_prompt: str | None = None

    # ------------------------------------------------------------------
    # Derived properties
    # ------------------------------------------------------------------

    @property
    def field_key(self) -> str:
        """Python/JSON-safe field key derived from ``q_id``.

        Hyphens are replaced with underscores so the value is a valid Python
        identifier and LLM JSON key (e.g. ``OPP-001`` → ``OPP_001``).
        """
        return self.q_id.replace("-", "_")

    @property
    def question_number(self) -> int:
        """Integer derived from ``q_id`` (e.g. ``OPP-007`` → ``7``)."""
        parts = self.q_id.split("-", 1)
        return int(parts[1]) if len(parts) == 2 and parts[1].isdigit() else 0

    @property
    def question_label(self) -> str:
        """Short label in the form ``'OPP-001 — Question text'``."""
        return f"{self.q_id} — {self.question}" if self.question else self.q_id

    @property
    def short_question(self) -> str:
        """Question text; first sentence only when multi-sentence."""
        return self.question.split(".")[0].strip() if self.question else ""

    @property
    def formatted_options(self) -> str:
        """Backtick-quoted comma list for picklist/multi-select fields; ``'—'`` otherwise."""
        if self.answer_type in ("text", "integer", "date", "array"):
            return "—"
        return ", ".join(f"`{v}`" for v in self.options) if self.options else "—"

    def to_table_row(self) -> str:
        """Render this field as one markdown table row for the LLM system prompt."""
        return (
            f"| `{self.field_key}` "
            f"| {self.q_id} "
            f"| {self.short_question} "
            f"| {self.answer_type} "
            f"| {self.formatted_options} |"
        )

    def to_prompt_dict(self) -> dict:
        """Serialise to a minimal dict for JSON injection into the system prompt.

        ``field_name`` is the ``field_key`` (e.g. ``OPP_001``) — the exact key
        the LLM must use in its JSON output. When set, ``prompt`` is the
        question-level extraction hint from the DB.
        """
        out: dict = {
            "field_name": self.field_key,
            "q_id": self.q_id,
            "question": self.question,
            "answer_type": self.answer_type,
            "options": self.options,
        }
        if self.question_prompt and self.question_prompt.strip():
            out["prompt"] = self.question_prompt.strip()
        return out


# ---------------------------------------------------------------------------
# PostgreSQL access
# ---------------------------------------------------------------------------


def _connect():
    """Return a PostgreSQL connection for application tables."""
    return get_db_connection()


@cache
def _load_all_picklist_options() -> dict[str, list[str]]:
    """Return ``{api_name: [option, ...]}`` for every picklist field in the DB."""
    con = _connect()
    try:
        cur = con.cursor()
        cur.execute(
            "SELECT q.api_name, p.option_value "
            "FROM sase_picklist_options p "
            "JOIN sase_questions q ON q.q_id = p.q_id "
            "ORDER BY q.api_name, p.sort_order"
        )
        raw = cur.fetchall()
        rows = rows_to_dicts(cur, raw)
        result: dict[str, list[str]] = {}
        for row in rows:
            result.setdefault(row["api_name"], []).append(row["option_value"])
        return result
    finally:
        con.close()


@cache
def load_batch_fields(batch_id: str) -> list[FieldDefinition]:
    """Load field definitions for ``batch_id`` from PostgreSQL and return as Pydantic objects.

    Each ``FieldDefinition`` is fully populated including its ``options`` list
    (joined from the ``sase_picklist_options`` table). Results are cached per
    process; restart the application after changing sase_questions or
    sase_picklist_options in the database.

    Args:
        batch_id: Text batch identifier (e.g. ``'sase_use_case_details'``).

    Returns:
        Ordered list of ``FieldDefinition`` instances for the batch.

    Raises:
        ValueError: If no rows are found for the given batch_id.
    """
    con = _connect()
    try:
        cur = con.cursor()
        cur.execute(
            "SELECT q.q_id, q.api_name, q.question, q.batch, q.answer_type, "
            "       q.requirement_type, q.section_prefix, q.seq_in_section, "
            "       q.question_prompt, b.batch_order "
            "FROM sase_questions q "
            "JOIN sase_batches b ON b.batch_id = q.batch "
            "WHERE q.batch = %s "
            "ORDER BY q.q_id",
            (batch_id,),
        )
        raw_rows = cur.fetchall()
        raw_rows = rows_to_dicts(cur, raw_rows)
    finally:
        con.close()

    if not raw_rows:
        raise ValueError(
            f"No sase_questions found for batch_id='{batch_id}'. "
            "Ensure the PostgreSQL SASE tables are populated."
        )

    options_map = _load_all_picklist_options()

    return [
        FieldDefinition(
            q_id=row["q_id"],
            api_name=row["api_name"],
            question=row["question"] or "",
            batch_id=row["batch"],
            batch_order=row["batch_order"],
            answer_type=row["answer_type"] or "text",
            requirement_type=row["requirement_type"] or "Optional",
            section_prefix=row["section_prefix"],
            seq_in_section=row["seq_in_section"],
            options=options_map.get(row["api_name"], []),
            question_prompt=row["question_prompt"] or None,
        )
        for row in raw_rows
    ]


# ---------------------------------------------------------------------------
# Per-field response models (shared with dynamic schema builder)
# ---------------------------------------------------------------------------

_T = TypeVar("_T")


# ---------------------------------------------------------------------------
# Enum normalisation helper
# ---------------------------------------------------------------------------


def _normalize_to_literal(value: str, literal_type: Any) -> str:
    """Fuzzy-match ``value`` to the nearest allowed ``Literal`` string.

    Tried in priority order:

    1. Exact match — fast path, returned immediately.
    2. Case-insensitive exact match.
    3. An allowed option that *starts with* ``value``
       (e.g. ``'VMware vSphere'`` → ``'VMware vSphere/ESXi'``).
    4. An allowed option that ``value`` *starts with*
       (uncommon abbreviation in the other direction).
    5. ``value`` is a *substring* of an allowed option
       (e.g. ``'Azure'`` → ``'Microsoft Azure'``, ``'AWS'`` → ``'Amazon AWS'``).

    Returns the original ``value`` unchanged when no match is found so that
    Pydantic still reports the validation error with the raw LLM output.
    """
    allowed = typing.get_args(literal_type)
    if not allowed:
        return value
    if value in allowed:
        return value  # fast path
    lower = value.lower()
    for opt in allowed:
        if opt.lower() == lower:
            return opt
    for opt in allowed:
        if opt.lower().startswith(lower):
            return opt
    for opt in allowed:
        if lower.startswith(opt.lower()):
            return opt
    for opt in allowed:
        if lower in opt.lower():
            return opt
    return value


class AnswerBasisItem(BaseModel):
    """One source excerpt that directly produced the extracted answer.

    The orchestrator enriches these with confidence_score, chunk_id, source_file
    from retrieval chunk metadata when available.
    """

    source: str = Field(
        description="Document or source name (e.g. filename, Zoom URL)."
    )
    excerpt: str | None = Field(
        default=None,
        description="Verbatim excerpt from the source that produced the answer.",
    )
    source_type: str | None = Field(
        default=None,
        description="Media type from context header, e.g. 'pdf', 'zoom_transcript', 'slack'.",
    )
    confidence_score: float | None = Field(
        default=None, description="Retrieval or rerank score when enriched."
    )
    chunk_id: str | None = Field(
        default=None, description="Chunk identifier from retrieval."
    )
    source_file: str | None = Field(
        default=None, description="Full path or document ID from retrieval."
    )
    rerank_score: float | None = Field(
        default=None, description="Relevance score from reranker."
    )

    @field_validator("confidence_score", mode="before")
    @classmethod
    def _coerce_confidence(cls, v: Any) -> float | None:
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None


class ConflictDetail(BaseModel):
    """One conflicting value found across different source documents."""

    value: str = Field(
        description="The conflicting extracted value (always a string; serialise lists as comma-separated)."
    )
    source: str = Field(
        description="Document or source name where this value was found."
    )
    excerpt: str | None = Field(
        default=None,
        description="Verbatim excerpt from the source containing the value.",
    )
    source_type: str | None = Field(
        default=None,
        description="Media type from context header, e.g. 'pdf', 'zoom_transcript'.",
    )
    confidence_score: float | None = Field(
        default=None, description="Confidence when enriched."
    )
    chunk_id: str | None = Field(
        default=None, description="Chunk identifier from retrieval."
    )
    source_file: str | None = Field(
        default=None, description="Full path or document ID from retrieval."
    )
    rerank_score: float | None = Field(
        default=None, description="Relevance score from reranker."
    )

    @field_validator("confidence_score", mode="before")
    @classmethod
    def _coerce_confidence(cls, v: Any) -> float | None:
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    @field_validator("value", mode="before")
    @classmethod
    def _coerce_value_to_str(cls, v: Any) -> str:
        if v is None:
            return ""
        return v if isinstance(v, str) else str(v)


FieldAnswerT = TypeVar("FieldAnswerT")


class FieldAnswer(BaseModel, Generic[FieldAnswerT]):
    """Generic extraction result for one SASE opportunity field.

    Parameterise with an answer type to get typed validation:

        FieldAnswer[str]                          — free text / date
        FieldAnswer[int]                          — integer
        FieldAnswer[Literal["Yes", "No"]]         — single-select picklist
        FieldAnswer[list[Literal["A", "B"]]]      — multi-select picklist
    """

    answer: FieldAnswerT | None = Field(
        default=None,
        description="Extracted answer, or null if not present in the provided context.",
    )
    conflict: bool = Field(
        default=False,
        description="True if contradictory values were found across different sources.",
    )
    conflict_reason: str | None = Field(
        default=None,
        description="One-sentence explanation of why the conflict was flagged; null when conflict=false.",
    )
    conflict_details: list[ConflictDetail] = Field(
        default_factory=list,
        description="Conflicting values and their origins; populated only when conflict=true.",
    )
    answer_basis: list[AnswerBasisItem] = Field(
        default_factory=list,
        description=(
            "Specific source(s) and verbatim excerpt(s) that directly produced the final answer. "
            "Include source_type when available from the context header. Populated only when answer is not null."
        ),
    )
    sources: list[str] = Field(
        default_factory=list,
        description="Names of all documents/sources consulted for this field.",
    )

    @model_validator(mode="before")
    @classmethod
    def _coerce_answer_to_declared_type(cls, data: Any) -> Any:
        """Normalise the LLM answer to match the declared type _T.

        - Multi-select (T = list[Literal[...]]): bare string → one-element
          list; each element is fuzzy-matched to its nearest canonical option.
        - Single-select (T = Literal[...]): near-matches (abbreviations, wrong
          case) are normalised via ``_normalize_to_literal`` before Pydantic
          validates them, preventing spurious literal_error failures on the
          fallback (no constrained decoding) path.
        - Integer (T = int): string → first integer found, or null.
        - Scalar non-enum: list → first element.
        """
        if not isinstance(data, dict):
            return data
        answer = data.get("answer")
        meta = getattr(cls, "__pydantic_generic_metadata__", None)
        if not (meta and meta.get("args")):
            return data
        inner = meta["args"][0]

        if typing.get_origin(inner) is list:
            if isinstance(answer, str):
                answer = [answer]
            if isinstance(answer, list):
                args = typing.get_args(inner)
                item_type = args[0] if args else None
                if item_type is not None and typing.get_origin(item_type) is Literal:
                    answer = [
                        _normalize_to_literal(v, item_type) if isinstance(v, str) else v
                        for v in answer
                    ]
            return {**data, "answer": answer}

        elif inner is int or (
            # Allow "integer" fields to accept decimals (LLMs often emit 99.95 as a JSON number)
            # when the underlying question is really a numeric/percentage field.
            typing.get_origin(inner) in (typing.Union, types.UnionType)
            and set(typing.get_args(inner)) == {int, float}
        ):
            if isinstance(answer, str):
                # Prefer parsing a full decimal number first (e.g. "99.95", "1,234.50")
                num = re.search(r"-?\d[\d,]*(?:\.\d+)?", answer)
                if num:
                    token = num.group(0).replace(",", "")
                    try:
                        value = float(token)
                        value_int = int(value)
                        return {
                            **data,
                            "answer": value_int if value.is_integer() else value,
                        }
                    except ValueError:
                        pass
                return {**data, "answer": None}
            if isinstance(answer, (int, float)):
                if isinstance(answer, float):
                    return {**data, "answer": int(answer) if answer.is_integer() else answer}
                return data
            if isinstance(answer, list) and answer:
                return {**data, "answer": answer[0]}

        else:
            if isinstance(answer, list) and answer:
                answer = answer[0]
            if isinstance(answer, str) and typing.get_origin(inner) is Literal:
                answer = _normalize_to_literal(answer, inner)
            return {**data, "answer": answer}

        return data

    @field_validator("conflict_details", "sources", "answer_basis", mode="before")
    @classmethod
    def _coerce_null_to_empty_list(cls, v: Any) -> list[Any]:
        return [] if v is None else v


def _answer_field_type(field_def: FieldDefinition) -> Any:
    """Derive a Python type annotation for a field's answer from its DB definition.

    answer_type      | options present? | result
    -----------------|-----------------|----------------------------------------------
    picklist         | yes             | Literal[("Opt1", "Opt2", ...)]
    picklist-search  | yes             | Literal[("Opt1", "Opt2", ...)]
    multi-select     | yes             | list[Literal[("Opt1", "Opt2", ...)]]
    integer          | —               | int
    text/date/array/other | —          | str
    """
    if field_def.answer_type == "integer":
        # In practice, "integer" fields sometimes contain decimals (e.g. percentages like 99.95).
        # Accepting float avoids hard failures while still keeping picklists strict.
        return int | float
    if field_def.options:
        lit = Literal[tuple(field_def.options)]  # type: ignore[misc]
        if field_def.answer_type == "multi-select":
            return list[lit]  # type: ignore[valid-type]
        return lit
    return str


@cache
def build_batch_schema(batch_id: str) -> type[BaseModel]:
    """Dynamically build the Pydantic extraction schema for ``batch_id`` from the DB.

    Each field in the batch becomes a ``FieldAnswer[T]`` typed attribute where
    ``T`` is derived from the field's ``answer_type`` and ``options`` stored in
    SQLite.  This is the single authoritative schema for both Vertex AI
    constrained decoding and post-hoc Pydantic validation.

    The result is cached (``lru_cache``) so the DB is only queried once per
    batch per process lifetime.

    Args:
        batch_id: Text batch identifier (e.g. ``'sase_use_case_details'``).

    Returns:
        A dynamically created Pydantic ``BaseModel`` subclass whose fields
        mirror the SASE questions for that batch.
    """
    fields = load_batch_fields(batch_id)
    field_specs: dict[str, Any] = {}
    for f in fields:
        inner_type = _answer_field_type(f)
        parameterised = FieldAnswer[inner_type]  # type: ignore[valid-type]
        field_specs[f.field_key] = (
            parameterised,
            Field(default_factory=parameterised, description=f.question),
        )

    schema_name = "".join(part.capitalize() for part in batch_id.split("_")) + "Schema"
    schema_cls = create_model(
        schema_name,
        __doc__=(
            f"Dynamically generated extraction schema for batch '{batch_id}' "
            f"({fields[0].q_id}–{fields[-1].q_id}). "
            "Built from PostgreSQL SASE tables at runtime."
        ),
        **field_specs,
    )
    return schema_cls


# ---------------------------------------------------------------------------
# Convenience wrappers
# ---------------------------------------------------------------------------


def build_fields_table(batch_id: str) -> str:
    """Build a markdown field table for ``batch_id`` using ``FieldDefinition`` objects.

    Produces:
        | JSON key | Q ID | Question | Type | Valid options |

    Args:
        batch_id: Text batch identifier.

    Returns:
        Multi-line markdown table string ready for embedding in a system prompt.
    """
    fields = load_batch_fields(batch_id)
    header = "| JSON key | Q ID | Question | Type | Valid options |"
    sep = "|---|---|---|---|---|"
    rows = [header, sep] + [f.to_table_row() for f in fields]
    return "\n".join(rows)


def get_field_count(batch_id: str) -> int:
    """Return the number of questions defined for ``batch_id``."""
    return len(load_batch_fields(batch_id))


def get_question_range(batch_id: str) -> tuple[str, str]:
    """Return ``(first_q_id, last_q_id)`` for ``batch_id``."""
    fields = load_batch_fields(batch_id)
    return fields[0].q_id, fields[-1].q_id


@lru_cache(maxsize=1)
def get_field_def_by_question_id() -> dict[str, FieldDefinition]:
    """Return {q_id: FieldDefinition} for all questions across all batches.

    Built by iterating batches and loading fields per batch. Cache invalidates
    only on process restart (restart required after DB changes per operational notes).
    """
    from src.services.agent.batch_registry import get_batches

    result: dict[str, FieldDefinition] = {}
    for batch in get_batches():
        for f in load_batch_fields(batch.batch_id):
            result[f.q_id] = f
    return result
