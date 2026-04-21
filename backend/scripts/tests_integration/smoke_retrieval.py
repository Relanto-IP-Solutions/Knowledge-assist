"""Smoke-check for retrieval pipeline: embed → Vector Search → rerank.

Run with:
  uv run python scripts/tests_integration/smoke_retrieval.py [opportunity_id]
  uv run python scripts/tests_integration/smoke_retrieval.py [opportunity_id] --no-db   # skip DB; use default questions
  uv run python scripts/tests_integration/smoke_retrieval.py --dry-run   # verify setup (needs DB for question count)

Requires (full run):
- configs/secrets/.env: GOOGLE_APPLICATION_CREDENTIALS (path to service account JSON)
- configs/.env or configs/secrets/.env: GCP_PROJECT_ID, Vector Search source env vars
- Vector Search combined index (VECTOR_SOURCE_COMBINED_*) or per-source indexes
  (VECTOR_SOURCE_DRIVE/ZOOM/SLACK_*) with data for the opportunity_id
- DB (CLOUDSQL_* or PG_*) unless --no-db is used
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

# Load .env files so Google libs get GOOGLE_APPLICATION_CREDENTIALS and GCP_PROJECT_ID
for _ef in (
    _PROJECT_ROOT / "configs" / ".env",
    _PROJECT_ROOT / "configs" / "secrets" / ".env",
):
    if _ef.exists():
        load_dotenv(_ef, override=False)


def dry_run(no_db: bool = False) -> None:
    """Verify sources (and optionally questions) load without calling Vertex AI."""
    from src.services.rag_engine.retrieval import get_combined_source, get_sources

    if no_db:
        questions = DEFAULT_SMOKE_QUESTIONS
        print(f"  Questions: {len(questions)} (default, no DB)")
    else:
        from src.services.rag_engine.retrieval import load_questions_for_retrieval

        questions = load_questions_for_retrieval()
        print(f"  Questions: {len(questions)} (e.g. {list(questions.keys())[:3]})")
    combined = get_combined_source()
    if combined is not None:
        print("  Sources: [combined]")
    else:
        sources = get_sources()
        print(f"  Sources: {[s.name for s in sources]}")
    print("  Dry run OK")


# Default questions when running with --no-db (no database required)
DEFAULT_SMOKE_QUESTIONS = {
    "Q1": "What is the main topic or summary of the content?",
    "Q2": "What are the key points or findings?",
}


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    flags = [a for a in sys.argv[1:] if a.startswith("-")]
    dry_run_mode = "--dry-run" in flags
    no_db = "--no-db" in flags

    opp_id = (args[0] if args else None) or os.environ.get("OPPORTUNITY_ID", "oid1023")
    print(f"Retrieval smoke — opportunity_id={opp_id}")

    if dry_run_mode:
        print("Dry run (no API calls)...")
        dry_run(no_db=no_db)
        return

    print("Running RetrievalPipeline.process_one_opportunity()...")
    if no_db:
        print("  (--no-db: using default questions, no database)")

    from src.services.pipelines.retrieval_pipeline import RetrievalPipeline

    pipeline = RetrievalPipeline()
    questions_override = DEFAULT_SMOKE_QUESTIONS if no_db else None
    result = pipeline.process_one_opportunity(
        opp_id, questions_override=questions_override
    )

    n_questions = len(result.get("retrievals", {}))
    n_chunks = sum(len(v) for v in (result.get("retrievals") or {}).values())
    print(f"  Questions: {n_questions}, Total chunks: {n_chunks}")

    out_dir = Path(__file__).resolve().parents[2] / "data" / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"smoke_retrieval_{opp_id.replace('/', '_')}.json"
    out_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"  Output: {out_path}")

    print("Retrieval smoke OK")


if __name__ == "__main__":
    main()
