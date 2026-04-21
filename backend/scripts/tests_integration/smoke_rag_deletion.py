"""Smoke test for RAG deletion (orphan reconciliation): run ingestion for a list of documents.

Runs IngestionPipeline.run_message() for each document name. Each run executes
reconciliation first (list GCS processed/documents, compare to document_registry,
delete orphans from document_registry / chunk_registry), then processes that document.

Run with:
  uv run python scripts/tests_integration/smoke_rag_deletion.py --opportunity-id oid2024 --object-names "doc1.txt,doc2.txt"
  uv run python scripts/tests_integration/smoke_rag_deletion.py --opportunity-id oid2024 --object-name "doc1.txt" --object-name "doc2.txt"
  uv run python scripts/tests_integration/smoke_rag_deletion.py --opportunity-id oid2024 --object-names "a.txt,b.txt" --dry-run

Requires (full run):
- configs/secrets/.env: GOOGLE_APPLICATION_CREDENTIALS, DB (PG_DATABASE=pzf_dor, etc.)
- configs/.env or configs/secrets/.env: GCP_PROJECT_ID, GCS_BUCKET_INGESTION
- Env: PROJECT_ID, optional OUTPUT_TOPIC
- Files must exist at gs://{bucket}/{opp}/processed/documents/{object_name} for each name
  (processed/documents contains processed text files, e.g. .txt, not raw PDFs)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

# Load env so settings and GCP creds are available. Secrets override .env so DB/creds in secrets/.env win.
try:
    from dotenv import load_dotenv

    if (_PROJECT_ROOT / "configs" / ".env").exists():
        load_dotenv(_PROJECT_ROOT / "configs" / ".env", override=False)
    if (_PROJECT_ROOT / "configs" / "secrets" / ".env").exists():
        load_dotenv(_PROJECT_ROOT / "configs" / "secrets" / ".env", override=True)
except ImportError:
    pass

os.environ.setdefault("PROJECT_ID", os.environ.get("GCP_PROJECT_ID", ""))

SOURCE_TYPE = "documents"


def dry_run(bucket: str, opportunity_id: str, object_names: list[str]) -> None:
    """Print required env and example messages without calling the pipeline."""
    from configs.settings import get_settings

    settings = get_settings()
    project_id = os.environ.get("PROJECT_ID") or settings.ingestion.gcp_project_id

    print("RAG deletion smoke — dry run")
    print("  Required env (set in configs/.env or configs/secrets/.env or shell):")
    print("    GOOGLE_APPLICATION_CREDENTIALS  path to service account JSON")
    print("    GCP_PROJECT_ID                  (or PROJECT_ID)")
    print("    GCS_BUCKET_INGESTION            bucket name")
    print(
        "    PG_DATABASE                     e.g. pzf_dor (for document_registry/chunk_registry)"
    )
    print("    PROJECT_ID                     (defaults to GCP_PROJECT_ID)")
    print("    OUTPUT_TOPIC                   (optional) completion topic")
    print()
    print("  Current:")
    print(f"    PROJECT_ID={project_id!r}")
    print(f"    GCS_BUCKET_INGESTION={bucket!r}")
    print()
    print(f"  Document names ({len(object_names)}):")
    for name in object_names:
        data_path = f"gs://{bucket}/{opportunity_id}/processed/{SOURCE_TYPE}/{name}"
        print(f"    {name!r} -> data_path={data_path!r}")
    print()
    print(
        "  Full run: pass --opportunity-id and --object-names (or repeated --object-name)."
    )
    print("  Dry run OK")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="RAG deletion smoke test: run ingestion for a list of documents (reconciliation runs before each)."
    )
    parser.add_argument(
        "--opportunity-id",
        default=os.environ.get("OPPORTUNITY_ID", "oid1000"),
        help="Opportunity ID",
    )
    parser.add_argument(
        "--object-names",
        help="Comma-separated object names under processed/documents (e.g. 'a.txt,b.txt')",
    )
    parser.add_argument(
        "--object-name",
        action="append",
        dest="object_name_list",
        help="Single object name under processed/documents (repeat for multiple)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print required env and example messages only",
    )
    args = parser.parse_args()

    # Build list: from --object-names (comma-separated) and/or repeated --object-name
    object_names = []
    if args.object_names:
        object_names.extend(
            s.strip() for s in args.object_names.split(",") if s.strip()
        )
    if args.object_name_list:
        object_names.extend(s.strip() for s in args.object_name_list if s.strip())

    if not object_names:
        parser.error(
            "Provide at least one document name via --object-names (comma-separated) or one or more --object-name"
        )
        return

    from configs.settings import get_settings
    from src.services.pipelines.ingestion_pipeline import IngestionPipeline

    settings = get_settings()
    bucket = (settings.ingestion.gcs_bucket_ingestion or "").strip()
    if not bucket:
        print(
            "Error: GCS_BUCKET_INGESTION not set. Set it in configs/.env or configs/secrets/.env"
        )
        sys.exit(1)

    opportunity_id = args.opportunity_id

    if args.dry_run:
        dry_run(bucket, opportunity_id, object_names)
        return

    pipeline = IngestionPipeline()
    failed = []
    for i, object_name in enumerate(object_names):
        data_path = (
            f"gs://{bucket}/{opportunity_id}/processed/{SOURCE_TYPE}/{object_name}"
        )
        message = {
            "source_type": SOURCE_TYPE,
            "data_path": data_path,
            "metadata": {
                "opportunity_id": opportunity_id,
                "channel": "gdrive",
                "source_id": object_name,
                "document_id": f"{opportunity_id}/processed/{SOURCE_TYPE}/{object_name}",
            },
        }
        print(
            f"[{i + 1}/{len(object_names)}] Running IngestionPipeline.run_message() for {data_path} ..."
        )
        try:
            result = pipeline.run_message(message)
            if result:
                print(f"  Result: {result}")
            else:
                print("  Result: None (skip/failure — check logs)")
                failed.append(object_name)
        except Exception as e:
            print(f"  Error: {e}")
            failed.append(object_name)

    if failed:
        print(
            f"\nRAG deletion smoke: {len(failed)} of {len(object_names)} document(s) failed: {failed}"
        )
        sys.exit(1)
    print(f"\nRAG deletion smoke OK — processed {len(object_names)} document(s).")


if __name__ == "__main__":
    main()
