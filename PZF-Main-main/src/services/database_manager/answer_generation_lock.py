"""Serialize answer generation per ``opportunity_id`` across all app instances using PostgreSQL."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from src.services.database_manager.connection import get_db_connection
from src.utils.logger import get_logger

logger = get_logger(__name__)

LOCK_PREFIX = "rag_answer_gen:"


class AnswerGenerationAlreadyRunningError(Exception):
    """Another answer-generation run for this opportunity is in progress (any worker / Cloud Run instance)."""

    pass


@contextmanager
def hold_answer_generation_db_lock(opportunity_id: str) -> Iterator[None]:
    """Hold a session-level advisory lock for one opportunity for the duration of the pipeline.

    The first concurrent caller acquires the lock; others get
    :class:`AnswerGenerationAlreadyRunningError` immediately from ``pg_try_advisory_lock``.
    """
    oid = (opportunity_id or "").strip()
    if not oid:
        yield
        return

    key_text = f"{LOCK_PREFIX}{oid}"
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT pg_try_advisory_lock(hashtext(%s::text))",
            (key_text,),
        )
        row = cur.fetchone()
        ok = bool(row and row[0])
        conn.commit()
        if not ok:
            logger.bind(opportunity_id=oid).warning(
                "Answer generation rejected: advisory lock held by another run"
            )
            raise AnswerGenerationAlreadyRunningError(
                "Answer generation is already in progress for this opportunity; "
                "wait for it to finish."
            )
        try:
            yield
        finally:
            cur_u = conn.cursor()
            cur_u.execute(
                "SELECT pg_advisory_unlock(hashtext(%s::text))",
                (key_text,),
            )
            conn.commit()
    finally:
        conn.close()
