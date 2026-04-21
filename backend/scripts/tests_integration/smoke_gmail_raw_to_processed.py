"""Smoke test: Gmail raw -> processed pipeline via GcsPipeline.

Tests the preprocessing pipeline for Gmail threads stored in GCS:
  - Reads raw/gmail/{thread_id}/thread.json
  - Preprocesses (clean, deduplicate, format)
  - Writes processed/gmail_messages/{thread_id}/content.txt

Usage:
    uv run python scripts/tests_integration/smoke_gmail_raw_to_processed.py --opp-id oid99

Requirements:
    - Raw Gmail data must exist in GCS (run smoke_gmail_oauth_and_gcs.py first)
    - configs/.env and configs/secrets/.env configured
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Smoke test: Gmail raw -> processed pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--opp-id",
        required=True,
        dest="opp_id",
        help="Opportunity ID to process (e.g., 'oid99')",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete existing processed Gmail files before running",
    )
    return parser.parse_args()


def _print_separator(title: str, width: int = 70) -> None:
    print(f"\n{'=' * width}")
    print(f"  {title}")
    print("=" * width)


def _print_raw_threads(storage, opp_id: str) -> list[str]:
    """List and display raw Gmail threads in GCS."""
    print("\n  Scanning raw/gmail/ for thread.json files...")
    try:
        raw_objects = storage.list_objects("raw", opp_id, "gmail")
        thread_files = [obj for obj in raw_objects if obj.endswith("/thread.json")]

        if not thread_files:
            print("  No thread.json files found in raw/gmail/")
            return []

        print(f"  Found {len(thread_files)} thread(s):")
        for tf in thread_files:
            thread_id = tf.rsplit("/", 1)[0]
            print(f"    - {thread_id}")
        return thread_files
    except Exception as e:
        print(f"  Error listing raw objects: {e}")
        return []


def _print_thread_preview(storage, opp_id: str, object_name: str) -> None:
    """Read and display a preview of a raw thread.json."""
    try:
        raw_bytes = storage.read("raw", opp_id, "gmail", object_name)
        thread = json.loads(raw_bytes)
        print(f"\n  Thread preview ({object_name}):")
        print(f"    Subject: {thread.get('subject', 'N/A')}")
        print(
            f"    Messages: {thread.get('message_count', len(thread.get('messages', [])))}"
        )
        participants = thread.get("participants", [])
        if participants:
            names = [p.get("name") or p.get("email", "?") for p in participants[:3]]
            print(f"    Participants: {', '.join(names)}")
    except Exception as e:
        print(f"    Error reading thread: {e}")


def _print_processed_content(storage, opp_id: str, thread_id: str) -> bool:
    """Read and display processed content.txt for a thread."""
    content_path = f"{thread_id}/content.txt"
    state_path = f"{thread_id}/state.json"

    try:
        content = storage.read("processed", opp_id, "gmail_messages", content_path)
        text = content.decode("utf-8") if isinstance(content, bytes) else content

        print(f"\n  Processed content ({thread_id}):")
        print(f"    Length: {len(text):,} chars")
        print("    Preview:")
        preview = text[:500]
        # Handle Windows encoding issues by replacing unprintable chars
        safe_preview = preview.encode("ascii", errors="replace").decode("ascii")
        print(textwrap.indent(safe_preview, "      "))
        if len(text) > 500:
            print(f"      ... [{len(text) - 500:,} more chars]")

        # Also show state.json
        try:
            state = json.loads(
                storage.read("processed", opp_id, "gmail_messages", state_path)
            )
            print(
                f"    State: {state.get('content_message_count')}/{state.get('message_count')} messages with content"
            )
        except FileNotFoundError:
            pass

        return True
    except FileNotFoundError:
        print(f"\n  Processed content NOT FOUND for {thread_id}")
        return False


def main() -> None:
    args = _parse_args()
    opp_id = args.opp_id

    _print_separator("GMAIL RAW -> PROCESSED PIPELINE TEST")
    print(f"  Opportunity ID: {opp_id}")
    print(f"  Reset: {args.reset}")

    from src.services.pipelines.gcs_pipeline import GcsPipeline
    from src.services.storage.service import Storage

    storage = Storage()
    pipeline = GcsPipeline(storage=storage)

    # Step 1: Check raw data
    _print_separator("Step 1: Checking raw Gmail data in GCS")
    thread_files = _print_raw_threads(storage, opp_id)

    if not thread_files:
        print(
            "\nERROR: No raw Gmail threads found. Run smoke_gmail_oauth_and_gcs.py first."
        )
        sys.exit(1)

    # Show preview of first thread
    _print_thread_preview(storage, opp_id, thread_files[0])

    # Step 2: Optional reset
    if args.reset:
        _print_separator("Step 2: Resetting processed Gmail data")
        try:
            processed_objects = storage.list_objects(
                "processed", opp_id, "gmail_messages"
            )
            for obj in processed_objects:
                storage.delete("processed", opp_id, "gmail_messages", obj)
                print(f"    Deleted: {obj}")
            print("  Reset complete.")
        except Exception as e:
            print(f"  Reset failed: {e}")
    else:
        _print_separator("Step 2: Skip reset (use --reset to force reprocessing)")

    # Step 3: Run pipeline
    _print_separator("Step 3: Running GcsPipeline.run_opportunity()")
    print(f"\n  Processing opportunity: {opp_id}")

    try:
        written, deleted = pipeline.run_opportunity(opp_id)

        print("\n  Results:")
        print(f"    Objects written: {len(written)}")
        for uri in written:
            print(f"      - {uri}")

        if deleted:
            print(f"    Objects deleted (orphans): {len(deleted)}")
            for uri in deleted:
                print(f"      - {uri}")

        if not written:
            print("    (No new objects written - files may already be up to date)")
    except Exception as e:
        print("\n  ERROR: Pipeline failed!")
        print(f"  {type(e).__name__}: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)

    # Step 4: Verify processed output
    _print_separator("Step 4: Verifying processed output")

    success_count = 0
    for tf in thread_files:
        thread_id = tf.rsplit("/", 1)[0]
        if _print_processed_content(storage, opp_id, thread_id):
            success_count += 1

    # Summary
    _print_separator("TEST SUMMARY")
    print(f"  Raw threads: {len(thread_files)}")
    print(f"  Processed successfully: {success_count}")

    if success_count == len(thread_files):
        print("\n  SUCCESS: All Gmail threads processed!")
        print("\n  Next steps:")
        print("    1. Run the RAG ingestion pipeline to embed and index")
        print("    2. Test retrieval with a query")
    elif success_count > 0:
        print(
            f"\n  PARTIAL SUCCESS: {success_count}/{len(thread_files)} threads processed"
        )
    else:
        print("\n  FAILED: No threads were processed")
        sys.exit(1)


if __name__ == "__main__":
    main()
