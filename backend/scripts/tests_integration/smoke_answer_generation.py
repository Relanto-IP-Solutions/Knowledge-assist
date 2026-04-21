"""Smoke script — run SASE opportunity extraction pipeline with mock context.

Executes the LangGraph agent pipeline using mock chunks from
data/context/sase_mock_chunks.json. Writes the merged answer set to data/output/.

Usage
-----
    uv run python -m scripts.tests_integration.smoke_answer_generation
    uv run python -m scripts.tests_integration.smoke_answer_generation --no-cache

Output
------
    data/output/oid_<opportunity_id>_results_{timestamp}.json (same pattern as GCS; see pipeline)
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from src.services.pipelines.agent_pipeline import (
    AnswerGenerationPipeline,
    _build_extract_payload,
    _gcs_response_filenames,
)
from src.utils.logger import get_logger


logger = get_logger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MOCK_RETRIEVALS = _REPO_ROOT / "data" / "context" / "sase_mock_chunks.json"
_OUTPUT_DIR = _REPO_ROOT / "data" / "output"


def _load_mock_body() -> dict:
    """Load mock retrieval body from sase_mock_chunks.json."""
    raw = json.loads(_MOCK_RETRIEVALS.read_text(encoding="utf-8"))
    out: dict = {}
    for q_id, chunks in raw.items():
        out[q_id] = []
        for c in chunks:
            out[q_id].append({
                "text": c.get("text", ""),
                "source": c.get("source", "unknown"),
                "source_type": c.get("source_type", "unknown"),
                "similarity_score": float(c.get("similarity_score", 0.0)),
                "document_id": c.get("document_id"),
                "chunk_id": c.get("chunk_id"),
            })
    return {"opportunity_id": "smoke-test", "retrievals": out}


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Run the opportunity extraction pipeline (smoke test with mock context)."
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Skip Vertex AI prompt caching and send full prompts for all batches.",
    )
    args = parser.parse_args()

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    logger.info(
        "Starting opportunity extraction pipeline (use_cache=%s)", not args.no_cache
    )
    body = _load_mock_body()
    pipeline = AnswerGenerationPipeline(use_cache=not args.no_cache)
    result = pipeline.run(body)

    answers_serialised = result.get("answers", {})
    meta = result.get("_meta", {})
    error_ids = meta.get("failed_question_ids", [])
    elapsed_s = meta.get("elapsed_seconds", 0)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    opp_id = str(body.get("opportunity_id") or "unknown")
    _, results_name = _gcs_response_filenames(opp_id, timestamp)
    out_path = _OUTPUT_DIR / results_name
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

    extract_payload = _build_extract_payload("smoke-test", answers_serialised)
    logger.info(
        "Extract API request payload (POST /api/ai/extract): %s",
        json.dumps(extract_payload, indent=2, ensure_ascii=False),
    )

    print(f"Written: {out_path}")


if __name__ == "__main__":
    main()
