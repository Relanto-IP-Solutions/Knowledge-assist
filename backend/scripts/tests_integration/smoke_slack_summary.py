"""Smoke script: end-to-end Slack summary generation from a local JSON file.

Runs the full pipeline — text reconstruction + Vertex AI LLM summarisation —
without touching GCS.  Useful for verifying the preprocessing and LLM layers
before wiring them into the full gcs_pipeline.

Usage
-----
    # First run (no prior analysis):
    uv run python scripts/tests_integration/smoke_slack_summary.py \\
        --file path/to/channel.json \\
        --channel general \\
        --opportunity-id oid1234

    # Incremental run (provide a previous analysis JSON to simulate update):
    uv run python scripts/tests_integration/smoke_slack_summary.py \\
        --file path/to/channel.json \\
        --channel general \\
        --opportunity-id oid1234 \\
        --previous-analysis path/to/previous_analysis.json

    # Save the output to a file:
    uv run python scripts/tests_integration/smoke_slack_summary.py \\
        --file path/to/channel.json \\
        --channel general \\
        --opportunity-id oid1234 \\
        --output path/to/output.json

    # Limit to messages after a specific timestamp (incremental slice):
    uv run python scripts/tests_integration/smoke_slack_summary.py \\
        --file path/to/channel.json \\
        --channel general \\
        --opportunity-id oid1234 \\
        --since-ts 1715856000.0

Requirements
------------
- configs/.env with GCP_PROJECT_ID, VERTEX_AI_LOCATION, LLM_MODEL_NAME.
- A valid GCP service account with Vertex AI access.
"""

import argparse
import json
import sys
from pathlib import Path


sys.path.insert(0, Path(Path(Path(__file__).resolve()).parent).parent)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Smoke-test Slack end-to-end summary generation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--file",
        "-f",
        required=True,
        type=Path,
        metavar="PATH",
        help="Path to the raw Slack JSON or NDJSON file.",
    )
    parser.add_argument(
        "--channel",
        "-c",
        required=True,
        help="Slack channel name / stem (e.g. 'general', 'opp-acme-sase').",
    )
    parser.add_argument(
        "--opportunity-id",
        "-o",
        required=True,
        dest="opportunity_id",
        help="Opportunity ID for context (e.g. 'oid1234').",
    )
    parser.add_argument(
        "--since-ts",
        type=float,
        default=None,
        metavar="UNIX_TS",
        help="Only include messages newer than this Unix timestamp (incremental slice).",
    )
    parser.add_argument(
        "--metadata",
        type=Path,
        default=None,
        metavar="PATH",
        help=(
            "Optional path to Slack metadata JSON (with channels[].members[]) "
            "used to resolve user IDs to display names."
        ),
    )
    parser.add_argument(
        "--previous-analysis",
        type=Path,
        default=None,
        metavar="PATH",
        help="Path to a previous ChannelAnalysis JSON file (triggers incremental prompt).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        metavar="PATH",
        help="Write the resulting ChannelAnalysis JSON to this file (prints to stdout if omitted).",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Only run Slack text reconstruction and skip the LLM summarisation step.",
    )
    return parser.parse_args()


from src.services.preprocessing.slack.formatter import (
    format_analysis_as_text,
)


def main() -> None:
    args = parse_args()

    # ------------------------------------------------------------------
    # Load inputs
    # ------------------------------------------------------------------
    slack_file: Path = args.file
    if not slack_file.exists():
        print(f"ERROR: Slack file not found: {slack_file}", file=sys.stderr)
        sys.exit(1)

    raw_bytes = slack_file.read_bytes()
    print(f"Loaded Slack file: {slack_file} ({len(raw_bytes):,} bytes)")

    # Optional: build user_map from metadata so @mentions resolve to friendly names
    user_map: dict[str, str] | None = None
    if args.metadata:
        metadata_path: Path = args.metadata
        if not metadata_path.exists():
            print(f"ERROR: Metadata file not found: {metadata_path}", file=sys.stderr)
            sys.exit(1)

        metadata = json.loads(metadata_path.read_text())
        user_map = {}
        for channel in metadata.get("channels", []):
            for member in channel.get("members", []):
                uid = member.get("id")
                name = member.get("name")
                if uid and name:
                    user_map[uid] = name

        print(f"Loaded metadata from {metadata_path} ({len(user_map)} users)")

    previous_analysis = None
    if args.previous_analysis:
        prev_path: Path = args.previous_analysis
        if not prev_path.exists():
            print(
                f"ERROR: Previous analysis file not found: {prev_path}", file=sys.stderr
            )
            sys.exit(1)
        from src.services.preprocessing.slack.schemas import ChannelAnalysis

        previous_analysis = ChannelAnalysis.model_validate_json(prev_path.read_text())
        print(f"Loaded previous analysis: {prev_path}")

    # ------------------------------------------------------------------
    # Run end-to-end pipeline
    # ------------------------------------------------------------------
    print("\n--- Step 1: Text reconstruction ---")
    from src.services.preprocessing.slack.preprocessor import SlackPreprocessor

    preprocessor = SlackPreprocessor()
    dialogue, latest_ts = preprocessor.preprocess(
        raw_bytes,
        user_map=user_map,
        since_ts=args.since_ts,
    )

    if not dialogue:
        print(
            "No processable messages found (nothing newer than since_ts, or file is empty)."
        )
        sys.exit(0)

    print(f"Dialogue length : {len(dialogue):,} characters")
    print(f"Latest message ts: {latest_ts}")
    print("\n--- Dialogue preview (first 800 chars) ---")
    print(dialogue[:800])
    if len(dialogue) > 800:
        print(f"... [{len(dialogue) - 800:,} more characters]")

    # If requested, stop here so we can validate text reconstruction without LLM access.
    if args.no_llm:
        print("\n(no-llm flag set; skipping LLM summarisation)")
        return

    print("\n--- Step 2: LLM summarisation ---")
    mode = "incremental" if previous_analysis else "first-run"
    print(f"Mode: {mode}")
    print(f"Channel: {args.channel}  |  Opportunity: {args.opportunity_id}")

    from src.services.preprocessing.slack import SlackOrchestrator

    orchestrator = SlackOrchestrator()
    result = orchestrator.process(
        raw_bytes=raw_bytes,
        channel=args.channel,
        opportunity_id=args.opportunity_id,
        since_ts=args.since_ts,
        user_map=user_map,
        previous_analysis=previous_analysis,
    )

    if result is None:
        print("Orchestrator returned None — no new messages to process.")
        sys.exit(0)

    analysis, checkpoint_ts = result

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------
    output_json = analysis.model_dump_json(indent=2)

    print("\n--- Step 3: Results ---")
    print(f"Checkpoint ts   : {checkpoint_ts}")
    print(
        f"Summary         : {analysis.summary[:200]}{'...' if len(analysis.summary) > 200 else ''}"
    )
    print(f"Requirements    : {len(analysis.requirements)}")
    print(f"Decisions       : {len(analysis.decisions)}")
    print(f"Action items    : {len(analysis.action_items)}")
    print(f"Open questions  : {len(analysis.open_questions)}")
    print(f"Risks/constraints: {len(analysis.risks_or_constraints)}")
    ent = analysis.entities
    print(
        f"Entities        : "
        f"products={len(ent.products)}, "
        f"features={len(ent.features)}, "
        f"integrations={len(ent.integrations)}, "
        f"people={len(ent.people)}, "
        f"teams={len(ent.teams)}, "
        f"vendors={len(ent.vendors)}"
    )

    readable_text = format_analysis_as_text(
        analysis, args.channel, args.opportunity_id, checkpoint_ts
    )

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output_json)
        txt_path = args.output.with_suffix(".txt")
        txt_path.write_text(readable_text)
        print(f"\nFull analysis JSON written to : {args.output}")
        print(f"Human-readable summary written to: {txt_path}")
    else:
        print("\n--- Full ChannelAnalysis JSON ---")
        print(output_json)

    print("\n--- Human-readable summary ---")
    print(readable_text)

    print("\nSmoke test passed.")


if __name__ == "__main__":
    main()
