"""Smoke test for event-based document deletion flow.

Before: print document_registry and chunk_registry state for the document.
Delete object from GCS processed/documents, then run deletion (registry only; pgvector).
After: assert document and chunks are gone; print PASS/FAIL.

Run with:
  uv run python scripts/tests_integration/smoke_document_deletion_flow.py --opportunity-id oid2024 --object-name "doc1.txt"
  uv run python scripts/tests_integration/smoke_document_deletion_flow.py --opportunity-id oid2024 --object-name "doc1.txt" --skip-gcs-delete

Requires:
- configs/secrets/.env: GOOGLE_APPLICATION_CREDENTIALS, DB (PG_DATABASE, etc.)
- configs/.env or configs/secrets/.env: GCP_PROJECT_ID, GCS_BUCKET_INGESTION
"""

from __future__ import annotations

import argparse
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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Smoke test: delete doc from GCS, run deletion pipeline, verify registry and chunks removed."
    )
    parser.add_argument("--opportunity-id", required=True, help="Opportunity ID")
    parser.add_argument(
        "--object-name",
        required=True,
        help="Object name under processed/documents (e.g. doc1.txt)",
    )
    parser.add_argument(
        "--skip-gcs-delete",
        action="store_true",
        help="Do not delete from GCS; only run registry deletion (e.g. doc already removed).",
    )
    args = parser.parse_args()

    from configs.settings import get_settings
    from src.services.database_manager.registry import RegistryClient
    from src.services.pipelines.ingestion_pipeline import IngestionPipeline
    from src.services.storage import Storage

    settings = get_settings()
    bucket = (settings.ingestion.gcs_bucket_ingestion or "").strip()
    if not bucket and not args.skip_gcs_delete:
        print("Error: GCS_BUCKET_INGESTION not set.")
        sys.exit(1)

    opportunity_id = args.opportunity_id
    object_name = args.object_name
    document_id = f"{opportunity_id}:documents:{object_name}"

    registry = RegistryClient()

    # Before
    doc_before = registry.get_document(document_id)
    chunks_before = registry.get_chunks(document_id)
    print("Before:")
    print(f"  document_registry = {doc_before}")
    print(f"  chunk_registry   = {len(chunks_before)} chunk(s)")

    if not args.skip_gcs_delete:
        print("Deleting object from GCS ...")
        storage = Storage()
        storage.delete("processed", opportunity_id, "documents", object_name)
        print("  GCS delete done.")

    print("Running deletion (document_registry + chunk_registry) ...")
    pipeline = IngestionPipeline()
    deleted = pipeline.delete_document_from_registry(opportunity_id, object_name)
    print(f"  delete_document_from_registry returned {deleted!r}")

    # After
    doc_after = registry.get_document(document_id)
    chunks_after = registry.get_chunks(document_id)
    print("After:")
    print(f"  document_registry = {doc_after}")
    print(f"  chunk_registry   = {len(chunks_after)} chunk(s)")

    if doc_after is None and chunks_after == []:
        print("PASS: Document and chunks removed.")
    else:
        print("FAIL: Document or chunks still present.")
        sys.exit(1)


if __name__ == "__main__":
    main()
