"""Batch registry — single source of truth for all SASE opportunities Q&A batch definitions.

Batch definitions are loaded entirely from Cloud SQL PostgreSQL (the
``sase_batches`` table), so adding or re-ordering batches requires only a DB
change — no Python file needs editing.

Operational note: Batch definitions are loaded once on first access. Restart
the application after changing sase_batches or sase_questions in the database.

Each ``BatchDefinition`` captures every piece of per-batch configuration in
one place: the batch identifier and ordering, display label, LLM prompt
description (both read from the DB), the dynamically built Pydantic schema
class, and the optional mock context file for local testing.

Batch map (batch_order 1–6, loaded from sase_batches):
    1  sase_use_case_details        SASE Use Case Details             (OPP-001–OPP-009,  9 questions)
    2  sase_customer_tenant         SASE Customer Tenant              (OPP-010–OPP-026, 17 questions)
    3  sase_infrastructure_details  SASE Prisma Access Infra Details  (OPP-027–OPP-039, 13 questions)
    4  sase_mobile_user_details     SASE Mobile User Details          (OPP-040–OPP-047,  8 questions)
    5  sase_ztna_details            SASE ZTNA Details                 (OPP-048–OPP-054,  7 questions)
    6  sase_remote_network_svc_conn SASE Remote Network & Svc Conn   (OPP-055–OPP-058,  4 questions)
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel

from src.services.database_manager import get_db_connection, rows_to_dicts
from src.utils.logger import get_logger


logger = get_logger(__name__)


@dataclass(frozen=True)
class BatchDefinition:
    """All configuration needed to run a single SASE opportunity extraction batch."""

    batch_id: str
    """Text primary key from ``sase_batches`` (e.g. ``'sase_use_case_details'``)."""

    batch_order: int
    """Integer ordering of this batch (1–6); used for cache keys and sorting."""

    label: str
    """Human-readable label from ``sase_batches.batch_label``."""

    description: str
    """One-paragraph hint for the LLM describing what this batch covers.
    Read from ``sase_batches.description`` — not hardcoded."""

    schema_class: type[BaseModel]
    """Pydantic model for this batch — built dynamically from the DB via
    ``field_loader.build_batch_schema(batch_id)``."""

    section_level_prompt: str | None = None
    """Optional section/agent-level prompt from ``sase_batches.section_level_prompt``.
    Appended after the batch description in the system prompt when non-empty."""

    context_file: str | None = None
    """Filename (under ``data/context/``) containing mock RAG chunks for local testing.

    Only used when running without chunks (fallback path). In production the caller
    supplies a ``ChunksByQuestion`` dict and this field is ignored.
    """

    include_few_shot: bool = False
    """Whether to append few-shot extraction examples to the system prompt."""

    @property
    def number(self) -> int:
        """Alias for ``batch_order`` — kept for call-site backward compatibility."""
        return self.batch_order


def _connect():
    """Return a PostgreSQL connection for application tables."""
    return get_db_connection()


def _build_registry() -> list[BatchDefinition]:
    """Construct the batch list by reading ``sase_batches`` from the DB.

    Schema classes are built dynamically via ``field_loader.build_batch_schema``.
    No batch metadata is hardcoded here — all labels and descriptions come from
    the database.
    """
    from src.services.agent.field_loader import build_batch_schema

    con = _connect()
    try:
        cur = con.cursor()
        cur.execute(
            "SELECT batch_id, batch_label, description, batch_order, section_level_prompt "
            "FROM sase_batches "
            "ORDER BY batch_order"
        )
        raw = cur.fetchall()
        rows = rows_to_dicts(cur, raw)
    finally:
        con.close()

    if not rows:
        raise RuntimeError(
            "No rows found in sase_batches. Ensure the PostgreSQL SASE tables are populated."
        )

    logger.debug("Loaded {} batches from sase_batches", len(rows))
    return [
        BatchDefinition(
            batch_id=row["batch_id"],
            batch_order=row["batch_order"],
            label=row["batch_label"],
            description=row["description"] or "",
            section_level_prompt=row["section_level_prompt"] or None,
            schema_class=build_batch_schema(row["batch_id"]),
            context_file="sase_mock_chunks.json",
        )
        for row in rows
    ]


# Module-level registry — built once on first access.
_BATCHES: list[BatchDefinition] | None = None


def get_batches() -> list[BatchDefinition]:
    """Return the ordered list of all batch definitions (lazily initialised)."""
    global _BATCHES
    if _BATCHES is None:
        _BATCHES = _build_registry()
    return _BATCHES
