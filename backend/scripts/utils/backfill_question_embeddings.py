"""Backfill script: compute and store question embeddings in sase_questions.question_embedding.

Usage examples (from repo root):

  uv run python scripts/utils/backfill_question_embeddings.py
  uv run python scripts/utils/backfill_question_embeddings.py --limit 100

This uses the same Vertex AI embedding logic as the retrieval pipeline
(`text-embedding-004` with task_type="RETRIEVAL_QUERY").
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

# Load config then secrets so secret vars (DB, GCP) take precedence
for _ef in (
    _PROJECT_ROOT / "configs" / ".env",
    _PROJECT_ROOT / "configs" / "secrets" / ".env",
):
    if _ef.exists():
        load_dotenv(_ef, override=True)


def _to_pgvector_literal(vec: list[float]) -> str:
    """Convert list[float] to pgvector literal string, e.g. '[0.1,0.2,...]'."""
    # Keep reasonable precision; Vertex outputs ~1e-2 granularity for most values.
    return "[" + ",".join(f"{v:.8f}" for v in vec) + "]"


def backfill(limit: int | None = None) -> None:
    """Backfill question_embedding for rows where it is NULL."""
    from src.services.database_manager import get_db_connection, rows_to_dicts
    from src.services.rag_engine.retrieval.embedding import embed_question
    from src.utils.logger import get_logger

    logger = get_logger(__name__)

    con = get_db_connection()
    try:
        cur = con.cursor()
        sql = (
            "SELECT q_id, question "
            "FROM sase_questions "
            "WHERE question IS NOT NULL "
            "  AND TRIM(question) <> '' "
            "  AND question_embedding IS NULL "
            "ORDER BY q_id"
        )
        if limit is not None and limit > 0:
            sql += " LIMIT %s"
            cur.execute(sql, (limit,))
        else:
            cur.execute(sql)
        raw = cur.fetchall()
        rows = rows_to_dicts(cur, raw)

        total = len(rows)
        if not rows:
            print(
                "No questions found that need embeddings (question_embedding IS NULL)."
            )
            return

        print(f"Found {total} question(s) without embeddings. Backfilling...")

        updated = 0
        for idx, row in enumerate(rows, start=1):
            qid = row["q_id"]
            text = (row["question"] or "").strip()
            if not text:
                continue
            vec = embed_question(text)
            literal = _to_pgvector_literal(vec)
            cur.execute(
                "UPDATE sase_questions SET question_embedding = %s WHERE q_id = %s",
                (literal, qid),
            )
            updated += 1
            if idx % 10 == 0 or idx == total:
                con.commit()
                logger.info("Backfill progress: {}/{} rows updated", idx, total)

        con.commit()
        print(f"Backfill complete. Updated {updated} row(s).")
    finally:
        con.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill sase_questions.question_embedding using Vertex text-embedding-004."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of questions to backfill in this run (default: all).",
    )
    args = parser.parse_args()
    backfill(limit=args.limit)


if __name__ == "__main__":
    main()
