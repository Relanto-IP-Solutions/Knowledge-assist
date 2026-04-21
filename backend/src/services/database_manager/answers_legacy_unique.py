"""Remove legacy one-row-per-question uniqueness on ``public.answers``.

Canonical DDL in ``scripts/setup/create_pg_tables.py`` defines only
``PRIMARY KEY (opportunity_id, answer_id)`` — multiple ``answer_id`` rows per
``(opportunity_id, question_id)`` are intended for versioned / per-run answers.

Some databases still have ``UNIQUE (opportunity_id, question_id)`` (often named
``uq_answers_opp_question``). That name does not appear in this repository's
table-creation history; it was likely added manually, via Cloud SQL console, or
by an external migration. It forces UPDATE-in-place instead of INSERT with a new
``answer_id``.

This module drops matching constraints and standalone unique indexes idempotently,
always targeting schema ``public``.
"""

from __future__ import annotations

import re
from typing import Any

from src.utils.logger import get_logger

logger = get_logger(__name__)

_SAFE_PG_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_KNOWN_UNIQUE_CONSTRAINT_NAMES = (
    "uq_answers_opp_question",
    "answers_opportunity_id_question_id_key",
)


def drop_legacy_unique_one_row_per_question_on_answers(cur: Any) -> None:
    """Drop UNIQUE (opportunity_id, question_id) on ``public.answers`` if present."""
    for name in _KNOWN_UNIQUE_CONSTRAINT_NAMES:
        if not _SAFE_PG_IDENTIFIER.match(name):
            continue
        cur.execute(
            f'ALTER TABLE public.answers DROP CONSTRAINT IF EXISTS "{name}"'
        )

    cur.execute(
        """
        SELECT c.conname::text
        FROM pg_constraint c
        JOIN pg_class t ON t.oid = c.conrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        WHERE n.nspname = 'public'
          AND t.relname = 'answers'
          AND c.contype = 'u'
          AND (
            SELECT COUNT(*)
            FROM unnest(c.conkey) AS u(attnum)
            JOIN pg_attribute a
              ON a.attrelid = c.conrelid AND a.attnum = u.attnum AND a.attnum > 0
          ) = 2
          AND (
            SELECT COUNT(*)
            FROM unnest(c.conkey) AS u(attnum)
            JOIN pg_attribute a
              ON a.attrelid = c.conrelid AND a.attnum = u.attnum AND a.attnum > 0
              AND a.attname::text IN ('opportunity_id', 'question_id')
          ) = 2
        """
    )
    for (name,) in cur.fetchall():
        if not name or not _SAFE_PG_IDENTIFIER.match(name):
            logger.warning(
                "Skipping DROP CONSTRAINT: unexpected name on public.answers | conname={}",
                name,
            )
            continue
        cur.execute(
            f'ALTER TABLE public.answers DROP CONSTRAINT IF EXISTS "{name}"'
        )
        logger.info(
            "Dropped UNIQUE(opportunity_id, question_id) on public.answers | constraint={}",
            name,
        )

    cur.execute(
        """
        SELECT ic.relname::text
        FROM pg_index ix
        JOIN pg_class t ON t.oid = ix.indrelid
        JOIN pg_class ic ON ic.oid = ix.indexrelid
        JOIN pg_namespace tn ON tn.oid = t.relnamespace
        WHERE tn.nspname = 'public'
          AND t.relname = 'answers'
          AND ix.indisunique
          AND ix.indpred IS NULL
          AND (
            SELECT COUNT(*)
            FROM unnest(ix.indkey::smallint[]) AS q(attnum)
            JOIN pg_attribute a ON a.attrelid = ix.indrelid AND a.attnum = q.attnum AND a.attnum > 0
          ) = 2
          AND (
            SELECT COUNT(*)
            FROM unnest(ix.indkey::smallint[]) AS q(attnum)
            JOIN pg_attribute a ON a.attrelid = ix.indrelid AND a.attnum = q.attnum AND a.attnum > 0
              AND a.attname::text IN ('opportunity_id', 'question_id')
          ) = 2
        """
    )
    for (idx_name,) in cur.fetchall():
        if not idx_name or not _SAFE_PG_IDENTIFIER.match(idx_name):
            logger.warning(
                "Skipping DROP INDEX: unexpected name on public.answers | index={}",
                idx_name,
            )
            continue
        cur.execute(f'DROP INDEX IF EXISTS public."{idx_name}"')
        logger.info(
            "Dropped unique index on (opportunity_id, question_id) | index={}",
            idx_name,
        )
