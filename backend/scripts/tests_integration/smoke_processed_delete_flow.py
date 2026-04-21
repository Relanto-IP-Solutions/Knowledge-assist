#!/usr/bin/env python3
"""Smoke: processed/documents file → document_deleted on Pub/Sub → rag deletion.

Tests the path when an object under ``{opp}/processed/documents/{file}`` is removed:
builds the same **document_deleted** payload as production, publishes to
**rag-ingestion-queue** (or POSTs **pubsub-dispatch**), then optionally runs
**delete_document_from_registry** locally (same as **rag-ingestion**).

Requires
--------
  GCS_BUCKET_INGESTION, GCP_PROJECT_ID; ADC or GOOGLE_APPLICATION_CREDENTIALS
  Pub/Sub publish: permission on rag-ingestion-queue
  Local rag step: DB connection settings (same as app)

Examples
--------
  uv run python scripts/tests_integration/smoke_processed_delete_flow.py -o oid1001 -f report.txt

  uv run python scripts/tests_integration/smoke_processed_delete_flow.py -o oid1001 -f report.txt --no-gcs-delete

  uv run python scripts/tests_integration/smoke_processed_delete_flow.py -o oid1001 -f report.txt \\
    --no-gcs-delete --no-local-delete

  uv run python scripts/tests_integration/smoke_processed_delete_flow.py -o oid1 -f x.txt --no-gcs-delete \\
    --dispatch-url "$PUBSUB_DISPATCH_URL" \\
    --identity-token "$(gcloud auth print-identity-token --audiences=\"$PUBSUB_DISPATCH_URL\")"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from dotenv import load_dotenv

    if (_PROJECT_ROOT / "configs" / ".env").exists():
        load_dotenv(_PROJECT_ROOT / "configs" / ".env", override=False)
    if (_PROJECT_ROOT / "configs" / "secrets" / ".env").exists():
        load_dotenv(_PROJECT_ROOT / "configs" / "secrets" / ".env", override=True)
except ImportError:
    pass

os.environ.setdefault("PROJECT_ID", os.environ.get("GCP_PROJECT_ID", ""))


def main() -> int:
    p = argparse.ArgumentParser(
        description="Smoke: processed delete → Pub/Sub document_deleted → rag deletion.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("-o", "--opportunity-id", required=True)
    p.add_argument(
        "-f",
        "--file",
        "--object-name",
        dest="object_name",
        required=True,
        metavar="FILE",
        help="Object name under processed/documents (e.g. report.txt)",
    )
    p.add_argument(
        "--no-gcs-delete",
        action="store_true",
        help="Skip GCS delete (file already removed from processed/documents).",
    )
    p.add_argument("--no-publish", action="store_true", help="Skip Pub/Sub / dispatch")
    p.add_argument(
        "--no-local-delete",
        action="store_true",
        help="Skip local registry delete; verify rag-ingestion in cloud",
    )
    p.add_argument(
        "--dispatch-url",
        default=os.environ.get("PUBSUB_DISPATCH_URL", "").strip(),
        help="POST to pubsub-dispatch instead of publishing directly to Pub/Sub",
    )
    p.add_argument(
        "--identity-token",
        default=os.environ.get("PUBSUB_DISPATCH_IDENTITY_TOKEN", "").strip(),
        help="OIDC token when using --dispatch-url",
    )
    p.add_argument("--dry-run", action="store_true", help="Print payload only")
    args = p.parse_args()

    from configs.settings import get_settings
    from src.services.pipelines.pubsub_pipeline import PubsubPipeline
    from src.services.storage import Storage

    settings = get_settings()
    bucket = (settings.ingestion.gcs_bucket_ingestion or "").strip()
    opp, oname = args.opportunity_id, args.object_name
    pipeline = PubsubPipeline()
    payload = pipeline._build_message(
        bucket or "placeholder", opp, "documents", oname, action_type="document_deleted"
    )

    print("=== document_deleted payload")
    print(json.dumps(payload, indent=2))
    if args.dry_run:
        print("\nPASS dry-run.")
        return 0

    if not bucket and not args.no_gcs_delete:
        print("Error: set GCS_BUCKET_INGESTION or use --no-gcs-delete.")
        return 1

    if not args.no_gcs_delete:
        print(f"\n=== Delete gs://{bucket}/{opp}/processed/documents/{oname}")
        storage = Storage()
        if not storage.exists("processed", opp, "documents", oname):
            print("WARN: object not in GCS; continuing.")
        else:
            storage.delete("processed", opp, "documents", oname)
            if storage.exists("processed", opp, "documents", oname):
                print("FAIL: GCS delete failed")
                return 1
            print("OK: removed from processed/documents")

    if args.no_publish:
        print("\n=== Skipped publish (--no-publish)")
    elif args.dispatch_url:
        gs_uri = f"gs://{bucket or 'placeholder'}/{opp}/processed/documents/{oname}"
        print("\n=== POST pubsub-dispatch")
        results = pipeline.publish_deletions_via_dispatch(
            args.dispatch_url,
            [gs_uri],
            identity_token=args.identity_token or None,
        )
        print(f"Results: {results}")
        if not results or not results[0].get("ok"):
            print("FAIL: dispatch did not publish")
            return 1
        print("OK: dispatch → rag-ingestion-queue")
    else:
        if not settings.ingestion.gcp_project_id:
            print("Error: GCP_PROJECT_ID required for Pub/Sub publish")
            return 1
        print("\n=== Publish rag-ingestion-queue")
        from src.services.pubsub.publisher import Publisher

        msg_id = Publisher(topic=settings.ingestion.pubsub_topic_rag_ingestion).publish(
            payload, opportunity_id=opp
        )
        print(f"OK: message_id={msg_id}")

    if args.no_local_delete:
        print("\nDone (--no-local-delete). Check rag-ingestion logs if deployed.")
        return 0

    print("\n=== Local rag delete (same as rag-ingestion document_deleted)")

    from src.services.database_manager.registry import RegistryClient
    from src.services.pipelines.ingestion_pipeline import IngestionPipeline

    doc_id = f"{opp}:documents:{oname}"
    reg = RegistryClient()
    IngestionPipeline().delete_document_from_registry(opp, oname)
    after_doc = reg.get_document(doc_id)
    after_chunks = reg.get_chunks(doc_id)
    print(
        f"After: document_row_absent={after_doc is None}, chunk_count={len(after_chunks)}"
    )
    print("\nPASS smoke_processed_delete_flow.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
