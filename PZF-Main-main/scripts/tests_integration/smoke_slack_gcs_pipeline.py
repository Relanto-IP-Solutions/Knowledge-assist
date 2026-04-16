"""Cloud smoke test: Slack preprocessing through GcsPipeline against real GCS.

Runs GcsPipeline.run_opportunity() against the real GCS bucket (`GCS_BUCKET_INGESTION`)
to verify:
  1. The pipeline reads raw messages and metadata from GCS.
  2. summary.txt and state.json are written to the processed tier.
  3. A second run with no new messages is a no-op (state.json ts unchanged).
  4. If new messages exist, the incremental prompt produces an updated analysis.

Expected GCS layout (must exist before running):
  {opp_id}/raw/slack/{channel_id}/slack_messages.json
  {opp_id}/raw/slack/slack_metadata.json

Usage
-----
  # Basic run (cold start OR incremental, depending on whether state.json exists):
  uv run python scripts/tests_integration/smoke_slack_gcs_pipeline.py \\
      --opportunity-id 006Ki000004r26LIAQ \\
      --channel C0AGAC0TZ0X

  # Force cold start by deleting state.json first:
  uv run python scripts/tests_integration/smoke_slack_gcs_pipeline.py \\
      --opportunity-id 006Ki000004r26LIAQ \\
      --channel C0AGAC0TZ0X \\
      --reset

  # Run the pipeline twice to verify incremental no-op:
  uv run python scripts/tests_integration/smoke_slack_gcs_pipeline.py \\
      --opportunity-id 006Ki000004r26LIAQ \\
      --channel C0AGAC0TZ0X \\
      --runs 2

Requirements
------------
  configs/.env      : GCP_PROJECT_ID, GCS_BUCKET_INGESTION, VERTEX_AI_LOCATION, LLM_MODEL_NAME
  configs/secrets/.env : GOOGLE_APPLICATION_CREDENTIALS pointing to a service account
                         with roles/storage.objectAdmin + roles/aiplatform.user
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Cloud smoke test: Slack pipeline against real GCS.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--opportunity-id",
        "-o",
        required=True,
        dest="opportunity_id",
        help="GCS opportunity ID (top-level folder name, e.g. '006Ki000004r26LIAQ').",
    )
    parser.add_argument(
        "--channel",
        "-c",
        required=True,
        help="Channel ID (sub-directory under raw/slack/, e.g. 'C0AGAC0TZ0X').",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete state.json from GCS before running to force a cold start.",
    )
    parser.add_argument(
        "--runs",
        "-r",
        type=int,
        default=1,
        metavar="N",
        help="Number of pipeline iterations to execute (default: 1). "
        "A second run with unchanged messages will be a no-op.",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _print_separator(title: str, width: int = 72) -> None:
    print(f"\n{'=' * width}")
    print(f"  {title}")
    print("=" * width)


def _print_state(storage, opp_id: str, channel: str, label: str = "") -> dict | None:
    """Read and print state.json from GCS. Returns the parsed dict or None."""
    state_object = f"{channel}/state.json"
    try:
        raw = storage.read("processed", opp_id, "slack_messages", state_object)
        state = json.loads(raw)
        a = state.get("analysis", {})
        print(f"\n  {label or 'state.json'}")
        print(f"    last_processed_ts : {state.get('last_processed_ts')}")
        print(f"    summary (first 120): {str(a.get('summary', ''))[:120]}")
        print(f"    requirements      : {len(a.get('requirements', []))}")
        print(f"    decisions         : {len(a.get('decisions', []))}")
        print(f"    action items      : {len(a.get('action_items', []))}")
        print(f"    open questions    : {len(a.get('open_questions', []))}")
        print(f"    risks/constraints : {len(a.get('risks_or_constraints', []))}")
        ent = a.get("entities", {})
        print(
            f"    entities          : "
            f"products={len(ent.get('products', []))}, "
            f"features={len(ent.get('features', []))}, "
            f"people={len(ent.get('people', []))}, "
            f"teams={len(ent.get('teams', []))}"
        )
        return state
    except FileNotFoundError:
        print(f"\n  {label or 'state.json'}: NOT FOUND (cold start on this run)")
        return None


def _print_summary_txt(storage, opp_id: str, channel: str) -> None:
    """Read and print a preview of summary.txt from GCS."""
    try:
        raw = storage.read(
            "processed", opp_id, "slack_messages", f"{channel}/summary.txt"
        )
        text = raw.decode("utf-8")
        print(f"\n  summary.txt preview ({len(text):,} chars total):")
        print(textwrap.indent(text[:600], "    "))
        if len(text) > 600:
            print(f"    ... [{len(text) - 600:,} more chars]")
    except FileNotFoundError:
        print("\n  summary.txt: NOT FOUND")


def _show_delta(before: dict | None, after: dict | None, run_number: int) -> None:
    if before is None or after is None:
        return
    print(f"\n  [Delta from run {run_number - 1} → run {run_number}]")
    fields = [
        "requirements",
        "decisions",
        "action_items",
        "open_questions",
        "risks_or_constraints",
    ]
    a_before = before.get("analysis", {})
    a_after = after.get("analysis", {})
    for f in fields:
        n_before = len(a_before.get(f, []))
        n_after = len(a_after.get(f, []))
        diff = n_after - n_before
        sign = "+" if diff >= 0 else ""
        print(f"    {f:<25}: {n_before} → {n_after}  ({sign}{diff})")
    ts_before = before.get("last_processed_ts", 0)
    ts_after = after.get("last_processed_ts", 0)
    same = "unchanged (no new messages)" if ts_before == ts_after else "ADVANCED"
    print(f"    checkpoint_ts     : {ts_before} → {ts_after}  [{same}]")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    args = _parse_args()
    opp_id = args.opportunity_id
    channel = args.channel

    _print_separator("SLACK GCS PIPELINE SMOKE TEST")
    print(f"  Opportunity ID : {opp_id}")
    print(f"  Channel        : {channel}")
    print(f"  Reset          : {args.reset}")
    print(f"  Runs           : {args.runs}")

    from src.services.pipelines.gcs_pipeline import GcsPipeline
    from src.services.storage.service import Storage

    storage = Storage()
    pipeline = GcsPipeline(storage=storage)

    # ------------------------------------------------------------------
    # Verify raw inputs exist in GCS before doing anything
    # ------------------------------------------------------------------
    _print_separator("PRE-FLIGHT: verifying GCS inputs")
    raw_messages = f"{channel}/slack_messages.json"
    raw_metadata = "slack_metadata.json"

    msgs_exists = storage.exists("raw", opp_id, "slack", raw_messages)
    meta_exists = storage.exists("raw", opp_id, "slack", raw_metadata)

    print(f"  raw/slack/{raw_messages} : {'FOUND' if msgs_exists else 'MISSING'}")
    print(f"  raw/slack/{raw_metadata}       : {'FOUND' if meta_exists else 'MISSING'}")

    if not msgs_exists:
        print(
            f"\nERROR: Raw messages file not found in GCS.\n"
            f"  Expected: {opp_id}/raw/slack/{raw_messages}",
            file=sys.stderr,
        )
        sys.exit(1)

    # ------------------------------------------------------------------
    # Optional reset: delete state.json to force cold start
    # ------------------------------------------------------------------
    if args.reset:
        _print_separator("RESET: deleting state.json")
        storage.delete("processed", opp_id, "slack_messages", f"{channel}/state.json")
        print("  state.json deleted (cold start will be forced on next run).")

    # ------------------------------------------------------------------
    # Run N iterations
    # ------------------------------------------------------------------
    states: list[dict | None] = []

    for run_idx in range(1, args.runs + 1):
        is_cold_expected = run_idx == 1 and (
            args.reset
            or not storage.exists(
                "processed", opp_id, "slack_messages", f"{channel}/state.json"
            )
        )
        run_type = "COLD START" if is_cold_expected else "INCREMENTAL"
        _print_separator(f"RUN {run_idx}/{args.runs} — {run_type}")

        state_before = _print_state(
            storage, opp_id, channel, label=f"state.json BEFORE run {run_idx}"
        )

        print(f"\n  Calling GcsPipeline.run_opportunity('{opp_id}') ...")
        try:
            written, deleted = pipeline.run_opportunity(opp_id)
        except Exception as exc:
            print(f"\nERROR: Pipeline run failed — {exc}", file=sys.stderr)
            raise

        if written:
            print(f"  Objects written: {written}")
        else:
            print(
                "  Pipeline wrote nothing (no new messages or all files already up to date)."
            )
        if deleted:
            print(f"  Objects deleted (orphans): {deleted}")

        state_after = _print_state(
            storage, opp_id, channel, label=f"state.json AFTER run {run_idx}"
        )
        _print_summary_txt(storage, opp_id, channel)
        _show_delta(state_before, state_after, run_idx)

        states.append(state_after)

    # ------------------------------------------------------------------
    # Final assertions
    # ------------------------------------------------------------------
    _print_separator("ASSERTIONS")
    passed = True

    final_state = states[-1]
    if final_state is None:
        print("  FAIL: state.json was not written after all runs.")
        passed = False
    else:
        print("  PASS: state.json exists after pipeline run(s).")
        if final_state.get("last_processed_ts"):
            print("  PASS: state.json contains last_processed_ts checkpoint.")
        else:
            print("  WARN: state.json has no last_processed_ts.")

    if args.runs >= 2 and states[0] is not None and states[-1] is not None:
        ts_first = states[0].get("last_processed_ts")
        ts_last = states[-1].get("last_processed_ts")
        if ts_first == ts_last:
            print(
                "  PASS: Incremental re-run did not advance checkpoint (no new messages — correct no-op)."
            )
        else:
            print(
                "  INFO: Checkpoint advanced across runs (new messages were picked up)."
            )

    summary_exists = storage.exists(
        "processed", opp_id, "slack_messages", f"{channel}/summary.txt"
    )
    if summary_exists:
        print("  PASS: summary.txt exists in GCS processed tier.")
    else:
        print("  FAIL: summary.txt is missing from GCS processed tier.")
        passed = False

    _print_separator("SMOKE TEST " + ("PASSED" if passed else "FAILED"))
    if not passed:
        sys.exit(1)


if __name__ == "__main__":
    main()
