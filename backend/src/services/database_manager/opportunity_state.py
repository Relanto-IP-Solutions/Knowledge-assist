"""Update ``opportunities`` pipeline columns (status, counts, last_extraction_at) from GCS + pipelines."""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from typing import Literal

from src.services.database_manager.connection import get_db_connection
from src.services.storage.service import Storage
from src.utils.logger import get_logger


logger = get_logger(__name__)
STATUS_CREATED = "created"
STATUS_DISCOVERED = "discovered"
STATUS_SYNCED = "synced"
STATUS_INGESTED = "ingested"
STATUS_EXTRACTED = "extracted"
STATUS_ERROR = "error"

Phase = Literal["sync", "ingested", "extracted"]


def gcs_raw_and_processed_counts(opportunity_id: str) -> tuple[int, int]:
    """Count objects under ``{opportunity_id}/raw/`` and ``{opportunity_id}/processed/``."""
    oid = opportunity_id.strip()
    storage = Storage()
    raw_n = storage.count_blobs_under_prefix(f"{oid}/raw/")
    proc_n = storage.count_blobs_under_prefix(f"{oid}/processed/")
    return raw_n, proc_n


def refresh_opportunity_pipeline_state(
    opportunity_id: str,
    phase: Phase,
) -> None:
    """Recount GCS tiers and set ``status`` / ``last_extraction_at`` for one opportunity.

    Safe to call from Cloud Functions (uses ``get_db_connection()``); failures are logged and ignored.
    """
    oid = (opportunity_id or "").strip()
    if not oid:
        return

    try:
        raw_n, proc_n = gcs_raw_and_processed_counts(oid)
    except Exception as e:
        logger.warning(
            "opportunity_state: GCS recount failed for opportunity_id=%s: %s",
            oid,
            e,
            exc_info=True,
        )
        return

    if phase == "sync":
        status = STATUS_SYNCED
    elif phase == "ingested":
        status = STATUS_INGESTED
    else:
        status = STATUS_EXTRACTED

    con = get_db_connection()
    try:
        cur = con.cursor()
        if phase == "extracted":
            cur.execute(
                """
                UPDATE opportunities
                SET total_documents = %s,
                    processed_documents = %s,
                    status = %s,
                    last_extraction_at = %s,
                    updated_at = NOW()
                WHERE opportunity_id = %s
                """,
                (
                    raw_n,
                    proc_n,
                    status,
                    datetime.now(UTC),
                    oid,
                ),
            )
        else:
            cur.execute(
                """
                UPDATE opportunities
                SET total_documents = %s,
                    processed_documents = %s,
                    status = %s,
                    updated_at = NOW()
                WHERE opportunity_id = %s
                """,
                (raw_n, proc_n, status, oid),
            )
        con.commit()
    except Exception as e:
        logger.warning(
            "opportunity_state: UPDATE opportunities failed for opportunity_id=%s: %s",
            oid,
            e,
            exc_info=True,
        )
        with contextlib.suppress(Exception):
            con.rollback()
    finally:
        con.close()
