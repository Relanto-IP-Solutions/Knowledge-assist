#!/usr/bin/env python3
"""Smoke: invoke deployed **rag-orchestrator** via ``gcloud functions call`` (no curl quoting).

Uses the same mechanism as manual testing but avoids Windows ``--data`` / JSON escaping issues
by passing ``--data`` as a single argv element built in Python.

Examples
--------
  uv run python scripts/tests_integration/smoke_rag_orchestrator.py \\
    --project eighth-bivouac-490806-s2 --opportunity-id oid1111

  # Batch poll (Pub/Sub pull; body ``{}``)
  uv run python scripts/tests_integration/smoke_rag_orchestrator.py \\
    --project eighth-bivouac-490806-s2 --batch

  uv run python scripts/tests_integration/smoke_rag_orchestrator.py --dry-run

Why not curl + ``print-identity-token --audiences``?
  User Google accounts often cannot use ``--audiences`` (requires SA or impersonation).
  Connector smoke uses identity tokens **without** ``--audiences``. For **gcloud functions call**,
  gcloud handles auth — no manual Bearer token.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--project", "-p", default="eighth-bivouac-490806-s2")
    p.add_argument("--region", "-l", default="us-central1")
    p.add_argument(
        "--opportunity-id",
        "-o",
        default="",
        help="Single-opp mode. Omit when using --batch.",
    )
    p.add_argument(
        "--batch",
        action="store_true",
        help="POST body {} — pull from PUBSUB_SUBSCRIPTION_RETRIEVAL_INITIATION.",
    )
    p.add_argument(
        "--function-name",
        default="rag-orchestrator",
        help="Cloud Function name. Default: rag-orchestrator",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print gcloud command and exit 0 without running.",
    )
    args = p.parse_args()

    if args.batch and args.opportunity_id:
        print("ERROR: use either --batch or --opportunity-id, not both.", file=sys.stderr)
        return 2
    if not args.batch and not args.opportunity_id:
        print("ERROR: pass --opportunity-id OID or --batch.", file=sys.stderr)
        return 2

    exe = shutil.which("gcloud") or shutil.which("gcloud.cmd")
    if not exe:
        print("ERROR: gcloud not found in PATH.", file=sys.stderr)
        return 1

    if args.batch:
        payload: dict[str, str] = {}
    else:
        payload = {"opportunity_id": args.opportunity_id.strip()}
    data_str = json.dumps(payload, separators=(",", ":"))

    cmd = [
        exe,
        "functions",
        "call",
        args.function_name,
        f"--region={args.region}",
        f"--project={args.project}",
        f"--data={data_str}",
    ]

    print("rag-orchestrator smoke")
    print(f"  payload: {payload}")
    print(f"  command: {' '.join(cmd)}")
    print()

    if args.dry_run:
        return 0

    try:
        return subprocess.call(cmd)
    except OSError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
