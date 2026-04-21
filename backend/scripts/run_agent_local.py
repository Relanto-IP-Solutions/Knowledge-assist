"""Run the agent pipeline locally using real vector retrieval.

By default uses real vectors: you pass an opportunity_id, the script runs
RetrievalPipeline (Vertex AI Vector Search) then the LangGraph agent, and prints
every question with its filled answer.

Usage
-----
  # Real vectors + agent; print all questions and answers (required: opportunity_id)
  uv run python -m scripts.run_agent_local <opportunity_id>

  # Same with explicit flag
  uv run python -m scripts.run_agent_local --opportunity-id <opportunity_id>

  # Write form_output and final_answers to data/output/
  uv run python -m scripts.run_agent_local <opportunity_id> --write-output

  # Mock context only (no GCP retrieval) — for testing without vector index
  uv run python -m scripts.run_agent_local --mock
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv


_PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Load .env files so Google libs get GOOGLE_APPLICATION_CREDENTIALS (configs/secrets/.env)
for _ef in (
    _PROJECT_ROOT / "configs" / ".env",
    _PROJECT_ROOT / "configs" / "secrets" / ".env",
):
    if _ef.exists():
        load_dotenv(_ef, override=False)
_DEFAULT_MOCK = _PROJECT_ROOT / "data" / "context" / "sase_mock_chunks.json"
_OUTPUT_DIR = _PROJECT_ROOT / "data" / "output"


def _load_mock_retrievals(path: Path) -> dict:
    """Load retrievals from a JSON file (e.g. sase_mock_chunks.json)."""
    raw = json.loads(path.read_text(encoding="utf-8"))
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
    return out


def _print_answers_json(payload: dict) -> None:
    """Print full payload (same format as GCS: opportunity_id, form_id, answers with conflicts)."""
    print()
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    print()
    answers = payload.get("answers", [])
    print(f" Total: {len(answers)} questions")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run agent pipeline with real vector retrieval; fill and print all questions.",
        epilog="Example: uv run python -m scripts.run_agent_local my-opp-123",
    )
    parser.add_argument(
        "opportunity_id",
        nargs="?",
        default=None,
        help="Opportunity ID to run retrieval and agent for (required unless --mock)",
    )
    parser.add_argument(
        "--opportunity-id",
        dest="opportunity_id_flag",
        metavar="ID",
        help="Alternative: set opportunity ID via flag",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use mock retrievals from data/context/sase_mock_chunks.json (no real vectors)",
    )
    parser.add_argument(
        "--retrievals",
        type=Path,
        default=_DEFAULT_MOCK,
        help="Path to retrievals JSON when using --mock",
    )
    parser.add_argument(
        "--write-output",
        action="store_true",
        help="Write form_output and final_answers to data/output/",
    )
    args = parser.parse_args()

    opportunity_id = args.opportunity_id or args.opportunity_id_flag
    if not args.mock and not opportunity_id:
        parser.error(
            "opportunity_id is required for real retrieval. "
            "Pass it as argument or use --opportunity-id=ID. Use --mock for mock-only run."
        )

    if args.mock:
        opportunity_id = opportunity_id or "local-test"
        if not args.retrievals.exists():
            print(f"Retrievals file not found: {args.retrievals}", file=sys.stderr)
            return 1
        retrievals = _load_mock_retrievals(args.retrievals)
        print(
            f"Using mock retrievals: {args.retrievals.name} — {len(retrievals)} questions"
        )
    else:
        try:
            from src.services.pipelines.retrieval_pipeline import RetrievalPipeline

            pipeline = RetrievalPipeline()
            result = pipeline.process_one_opportunity(opportunity_id)
            retrievals = result.get("retrievals", {})
            print(
                f"Retrieval done: {len(retrievals)} questions, {sum(len(v) for v in retrievals.values())} chunks"
            )
        except Exception as e:
            print(f"Retrieval failed: {e}", file=sys.stderr)
            return 1

    from src.services.agent.form_output import build_full_answers_payload
    from src.services.agent.graph import run as agent_run

    try:
        out = agent_run(opportunity_id, retrievals, use_async=True)
    except Exception as e:
        print(f"Agent pipeline failed: {e}", file=sys.stderr)
        raise

    final_answers = out.get("final_answers") or {}
    candidate_answers = out.get("candidate_answers") or []
    accumulated = out.get("accumulated_conflict_alternatives") or {}
    payload = build_full_answers_payload(
        opportunity_id, final_answers, candidate_answers, accumulated
    )
    _print_answers_json(payload)

    if args.write_output:
        _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        out_path = _OUTPUT_DIR / f"agent_{opportunity_id}.json"
        write_payload = {
            **payload,
            "final_answers": final_answers,
        }
        out_path.write_text(
            json.dumps(write_payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"Written: {out_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
