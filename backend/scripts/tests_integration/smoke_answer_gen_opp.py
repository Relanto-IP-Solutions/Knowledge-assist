"""Smoke test: Answer generation pipeline using real retrieval data.

Usage:
    uv run python -m scripts.tests_integration.smoke_answer_gen_opp oid99
    uv run python -m scripts.tests_integration.smoke_answer_gen_opp oid99 --no-cache
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from src.services.pipelines.agent_pipeline import (
    AnswerGenerationPipeline,
    _build_extract_payload,
)
from src.utils.logger import get_logger


logger = get_logger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_OUTPUT_DIR = _REPO_ROOT / "data" / "output"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run answer generation on real retrieval data for an opportunity."
    )
    parser.add_argument(
        "opportunity_id",
        help="Opportunity ID (must have retrieval output at data/output/smoke_retrieval_{opp_id}.json)",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Skip Vertex AI prompt caching.",
    )
    args = parser.parse_args()

    opp_id = args.opportunity_id
    retrieval_file = _OUTPUT_DIR / f"smoke_retrieval_{opp_id.replace('/', '_')}.json"

    if not retrieval_file.exists():
        print(f"ERROR: Retrieval file not found: {retrieval_file}")
        print(
            f"Run retrieval first: uv run python scripts/tests_integration/smoke_retrieval.py {opp_id}"
        )
        return

    print(f"Loading retrieval data from: {retrieval_file}")
    body = json.loads(retrieval_file.read_text(encoding="utf-8"))

    n_questions = len(body.get("retrievals", {}))
    n_chunks = sum(len(v) for v in body.get("retrievals", {}).values())
    print(f"  Questions: {n_questions}, Total chunks: {n_chunks}")

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("Starting answer generation pipeline (use_cache=%s)", not args.no_cache)
    pipeline = AnswerGenerationPipeline(use_cache=not args.no_cache)
    result = pipeline.run(body)

    answers_serialised = result.get("answers", {})
    meta = result.get("_meta", {})
    error_ids = meta.get("failed_question_ids", [])
    elapsed_s = meta.get("elapsed_seconds", 0)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = _OUTPUT_DIR / f"answer_gen_{opp_id.replace('/', '_')}_{timestamp}.json"
    out_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    logger.info(
        "Results written to %s (%d answers, %d errors, %.1fs)",
        out_path.name,
        len(answers_serialised),
        len(error_ids),
        elapsed_s,
    )
    if error_ids:
        logger.warning("Failed question IDs: %s", ", ".join(sorted(error_ids)))

    extract_payload = _build_extract_payload(opp_id, answers_serialised)
    extract_path = (
        _OUTPUT_DIR / f"extract_payload_{opp_id.replace('/', '_')}_{timestamp}.json"
    )
    extract_path.write_text(
        json.dumps(extract_payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print("\nAnswer generation complete:")
    print(f"  Answers: {len(answers_serialised)}")
    print(f"  Errors: {len(error_ids)}")
    print(f"  Time: {elapsed_s:.1f}s")
    print(f"  Output: {out_path}")
    print(f"  Extract payload: {extract_path}")


if __name__ == "__main__":
    main()
