#!/usr/bin/env python3
"""Smoke: run the deployed Cloud Workflow ``ingestion-pipeline`` (full GCP ingestion chain).

This triggers **in order** (see ``workflows/ingestion_pipeline.yaml``):

1. **gcs-file-processor** — raw/ → processed/
2. **pubsub-dispatch** — publishes messages for each processed file
3. **rag-ingestion** — runs via your **Pub/Sub → Cloud Function** subscription (not a separate CLI call)

**Why ``lookback_minutes=0`` (default here)**  
If you ran data connectors **hours ago**, raw objects were written then. The functions use a
*rolling window*: with ``lookback_minutes=15``, only blobs **updated in the last 15 minutes**
are considered — your older raw would be **skipped**. Passing **0** means *no age filter*:
process everything that the pipeline logic picks up for the scope (all OIDs or one OID).

Examples
--------
  # All opportunities, full backfill (after connectors ran earlier today)
  uv run python scripts/tests_integration/smoke_ingestion_cloud_workflow.py \\
    --project YOUR_PROJECT_ID

  # Only one OID
  uv run python scripts/tests_integration/smoke_ingestion_cloud_workflow.py \\
    --project YOUR_PROJECT_ID --opportunity-id oid0123

  # Dry-run: print gcloud command only
  uv run python scripts/tests_integration/smoke_ingestion_cloud_workflow.py \\
    --project YOUR_PROJECT_ID --dry-run

Requires
--------
  ``gcloud`` CLI, credentials that can run workflows (``workflows.executions.create``), and the
  workflow deployed with correct Cloud Run URLs inside the YAML.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--project",
        "-p",
        required=True,
        help="GCP project ID (e.g. my-proj-123)",
    )
    p.add_argument(
        "--location",
        "-l",
        default="us-central1",
        help="Workflow region. Default: us-central1",
    )
    p.add_argument(
        "--workflow",
        "-w",
        default="ingestion-pipeline",
        help="Deployed workflow name. Default: ingestion-pipeline",
    )
    p.add_argument(
        "--opportunity-id",
        "-o",
        default="",
        help="Canonical OID (e.g. oid0123). Omit or empty for all opportunities.",
    )
    p.add_argument(
        "--lookback-minutes",
        type=int,
        default=0,
        help=(
            "Passed to gcs-file-processor and pubsub-dispatch. "
            "Use 0 to process/dispatch regardless of blob age (needed if connectors ran hours ago). "
            "Default: 0."
        ),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the gcloud command and exit without running",
    )
    args = p.parse_args()

    exe = shutil.which("gcloud") or shutil.which("gcloud.cmd")
    if not exe:
        print("ERROR: gcloud not found in PATH.", file=sys.stderr)
        return 1

    payload = {
        "lookback_minutes": int(args.lookback_minutes),
        "opportunity_id": (args.opportunity_id or "").strip(),
    }
    data_json = json.dumps(payload, separators=(",", ":"))

    cmd = [
        exe,
        "workflows",
        "run",
        args.workflow,
        f"--location={args.location}",
        f"--project={args.project}",
        f"--data={data_json}",
    ]

    print("Ingestion workflow smoke")
    print(f"  payload: {payload}")
    print(f"  command: {' '.join(cmd)}")
    print()

    if args.dry_run:
        return 0

    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        return e.returncode or 1
    except OSError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print("\nDone. Check execution in Cloud Console → Workflows, and logs for gcs-file-processor, pubsub-dispatch, rag-ingestion.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
