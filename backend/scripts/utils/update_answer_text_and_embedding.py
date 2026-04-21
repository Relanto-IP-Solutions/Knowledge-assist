"""One-off utility: update an answer's text + embedding in Postgres.

Updates:
- answers.answer_text
- answers.answer_embedding (pgvector)
- answer_versions.answer_text for the matching version (keeps history consistent)

Usage (PowerShell):
  uv run python scripts/utils/update_answer_text_and_embedding.py `
    --opportunity-id oid0009 `
    --question-id QID-033 `
    --current-version 71 `
    --new-text "..."

Add --dry-run to preview without writing.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from datetime import UTC, datetime

# Ensure repo root is on sys.path so `import src...` works when running as a script.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.services.database_manager.connection import get_db_connection
from src.services.rag_engine.retrieval.embedding import embed_texts
from src.utils.logger import get_logger


logger = get_logger(__name__)


def _pgvector_param(val):
    # Same fallback pattern as RegistryClient/chunk_registry writes.
    if isinstance(val, list):
        return "[" + ",".join(map(str, val)) + "]"
    return val


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--opportunity-id", required=True)
    ap.add_argument("--question-id", default="QID-033")
    ap.add_argument("--current-version", type=int, default=71)
    ap.add_argument("--new-text", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    opp_id = str(args.opportunity_id).strip()
    qid = str(args.question_id).strip()
    cur_ver = int(args.current_version)
    new_text = str(args.new_text)
    now = datetime.now(UTC)

    if not opp_id or not qid:
        raise SystemExit("opportunity-id and question-id must be non-empty")

    # Compute embedding once (text-embedding-004 => 768 dims)
    vecs = embed_texts([new_text])
    embedding = vecs[0] if vecs else None

    con = get_db_connection()
    try:
        cur = con.cursor()

        # Find target answer rows.
        cur.execute(
            """
            SELECT answer_id, answer_text
            FROM answers
            WHERE opportunity_id = %s
              AND question_id = %s
              AND current_version = %s
            ORDER BY updated_at DESC, created_at DESC
            """,
            (opp_id, qid, cur_ver),
        )
        rows = cur.fetchall()
        if not rows:
            logger.error(
                "No answers rows found for opportunity_id={} question_id={} current_version={}",
                opp_id,
                qid,
                cur_ver,
            )
            con.rollback()
            return 2

        answer_ids = [r[0] for r in rows]
        logger.info(
            "Matched {} answers row(s) for opportunity_id={} question_id={} current_version={}",
            len(answer_ids),
            opp_id,
            qid,
            cur_ver,
        )

        if args.dry_run:
            logger.info("Dry-run mode: would update answer_ids={}", answer_ids)
            con.rollback()
            return 0

        # Update answers table.
        cur.execute(
            """
            UPDATE answers
            SET answer_text = %s,
                answer_embedding = %s,
                updated_at = %s
            WHERE opportunity_id = %s
              AND question_id = %s
              AND current_version = %s
            """,
            (new_text, _pgvector_param(embedding), now, opp_id, qid, cur_ver),
        )
        answers_updated = cur.rowcount

        # Update answer_versions rows for the same version number (keep history coherent).
        cur.execute(
            """
            UPDATE answer_versions
            SET answer_text = %s
            WHERE opportunity_id = %s
              AND question_id = %s
              AND answer_id = ANY(%s::text[])
              AND version = %s
            """,
            (new_text, opp_id, qid, answer_ids, cur_ver),
        )
        versions_updated = cur.rowcount

        con.commit()
        logger.info(
            "Update committed | answers_updated={} answer_versions_updated={}",
            answers_updated,
            versions_updated,
        )
        return 0
    except Exception:
        con.rollback()
        logger.exception("Update failed; rolled back")
        raise
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())

