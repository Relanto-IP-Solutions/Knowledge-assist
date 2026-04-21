"""Smoke test: answer generation for a subset of questions (fewer LLM batch calls).

Filters ``retrievals`` to the given ``q_id`` list and skips worker batches that
have no chunks after partitioning (``_smoke_skip_empty_batches``). This reduces
Vertex calls versus running all 6 batches with full retrieval.

Usage
-----
  uv run python -m scripts.tests_integration.smoke_answer_gen_subset oid0003 --qids QID-001,QID-002,QID-005

  uv run python -m scripts.tests_integration.smoke_answer_gen_subset oid0003 --qids QID-001 --no-cache

Requires
--------
  ``data/output/smoke_retrieval_{opp}.json`` and DB/env like ``smoke_answer_gen_opp``.

Body keys (internal, set by this script):
  ``_filter_question_ids`` — list of q_id strings to keep in retrievals.
  ``_smoke_skip_empty_batches`` — true: do not call the LLM for batches with zero chunks.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_OUTPUT_DIR = _REPO_ROOT / "data" / "output"

for _ef in (
    _REPO_ROOT / "configs" / ".env",
    _REPO_ROOT / "configs" / "secrets" / ".env",
):
    if _ef.exists():
        try:
            from dotenv import load_dotenv

            load_dotenv(_ef, override=True)
        except ImportError:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run answer generation for selected question ids only (smoke)."
    )
    parser.add_argument("opportunity_id", help="Opportunity id (e.g. oid0003)")
    parser.add_argument(
        "--qids",
        required=True,
        help="Comma-separated question ids (e.g. QID-001,QID-002,QID-003)",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Skip Vertex prompt caching.",
    )
    args = parser.parse_args()

    opp_id = args.opportunity_id
    wanted = [x.strip() for x in args.qids.split(",") if x.strip()]
    if not wanted:
        raise SystemExit("Provide at least one q_id in --qids")

    retrieval_file = _OUTPUT_DIR / f"smoke_retrieval_{opp_id.replace('/', '_')}.json"
    if not retrieval_file.exists():
        print(f"ERROR: Retrieval file not found: {retrieval_file}")
        print(
            f"Run: uv run python scripts/tests_integration/smoke_retrieval.py {opp_id}"
        )
        raise SystemExit(1)

    body = json.loads(retrieval_file.read_text(encoding="utf-8"))
    body["_filter_question_ids"] = wanted
    body["_smoke_skip_empty_batches"] = True

    from src.services.pipelines.agent_pipeline import AnswerGenerationPipeline

    print(f"Filtered to {len(wanted)} question(s): {wanted}")
    print(
        "skip_empty_batches=True (batches with no chunks for this filter are skipped)"
    )

    pipeline = AnswerGenerationPipeline(use_cache=not args.no_cache)
    result = pipeline.run(body)

    meta = result.get("_meta", {})
    answers = result.get("answers", {})
    err_ids = meta.get("failed_question_ids", [])

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = _OUTPUT_DIR / f"answer_gen_subset_{opp_id.replace('/', '_')}_{ts}.json"
    out_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(
        f"\nDone: {len(answers)} answer entries, errors={err_ids}, time={meta.get('elapsed_seconds')}s"
    )
    print(f"Wrote: {out_path}")


if __name__ == "__main__":
    main()
