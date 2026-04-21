"""Smoke test for ingestion: invoke IngestionPipeline.run_message() locally for one GCS file.

Run with:
  uv run python scripts/tests_integration/smoke_ingestion_pipeline.py --opportunity-id oid1000 --source-type zoom_transcripts --create-test-file
  uv run python scripts/tests_integration/smoke_ingestion_pipeline.py --opportunity-id oid1000 --source-type documents --object-name path/to/file.pdf
  uv run python scripts/tests_integration/smoke_ingestion_pipeline.py --dry-run

Requires (full run):
- configs/secrets/.env: GOOGLE_APPLICATION_CREDENTIALS, PG_PASSWORD, CLOUDSQL_INSTANCE_CONNECTION_NAME
- configs/.env or configs/secrets/.env: GCP_PROJECT_ID, GCS_BUCKET_INGESTION, PG_* settings
- PostgreSQL with pgvector extension and chunk_registry/document_registry tables
- For --create-test-file: only zoom_transcripts is supported (writes minimal transcript to GCS then runs)
- Otherwise: a real file must exist at gs://{bucket}/{opp}/processed/{source_type}/{object_name}
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
os.environ.setdefault("LOCATION", os.environ.get("VERTEX_AI_LOCATION", "us-central1"))

# Minimal Zoom transcript (tab-separated) for --create-test-file
ZOOM_SMOKE_CONTENT = """start_time\tend_time\tspeaker\tdialogue
00:00:00\t00:00:05\tSpeaker 1\tHello and welcome to the smoke test.
00:00:05\t00:00:12\tSpeaker 2\tThis is a minimal transcript for ingestion pipeline smoke.
00:00:12\t00:00:18\tSpeaker 1\tIt should chunk and embed successfully.
"""


def dry_run(
    bucket: str, opportunity_id: str, source_type: str, object_name: str
) -> None:
    """Print required env and example message without calling the pipeline."""
    from configs.settings import get_settings

    settings = get_settings()
    project_id = os.environ.get("PROJECT_ID") or settings.ingestion.gcp_project_id

    print("Ingestion pipeline smoke — dry run (pgvector)")
    print("  Required env (set in configs/.env or configs/secrets/.env):")
    print("    GOOGLE_APPLICATION_CREDENTIALS  path to service account JSON")
    print("    GCP_PROJECT_ID                  GCP project ID")
    print("    GCS_BUCKET_INGESTION            bucket name")
    print("    PG_DATABASE, PG_USER, PG_PASSWORD  PostgreSQL credentials")
    print("    CLOUDSQL_INSTANCE_CONNECTION_NAME  Cloud SQL instance")
    print("    OUTPUT_TOPIC                    (optional) completion topic")
    print()
    print("  Current:")
    print(f"    GCP_PROJECT_ID={project_id!r}")
    print(f"    GCS_BUCKET_INGESTION={bucket!r}")
    print()
    data_path = f"gs://{bucket}/{opportunity_id}/processed/{source_type}/{object_name}"
    print("  Example message:")
    print(f"    data_path={data_path!r}")
    print(f"    source_type={source_type!r}")
    print()
    print(
        "  Full run: pass --opportunity-id, --source-type, --object-name (or use --create-test-file for zoom)."
    )
    print("  Dry run OK")


def create_zoom_test_file(bucket: str, opportunity_id: str) -> str:
    """Write minimal Zoom transcript to GCS; return object_name."""
    from src.services.storage import Storage

    storage = Storage()
    object_name = "smoke_zoom.txt"
    storage.write(
        "processed",
        opportunity_id,
        "zoom_transcripts",
        object_name,
        ZOOM_SMOKE_CONTENT.encode("utf-8"),
        content_type="text/plain",
    )
    return object_name


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingestion pipeline smoke test")
    parser.add_argument(
        "--opportunity-id",
        default=os.environ.get("OPPORTUNITY_ID", "oid1000"),
        help="Opportunity ID",
    )
    parser.add_argument(
        "--source-type",
        choices=["documents", "slack_messages", "zoom_transcripts", "gmail_messages"],
        default="zoom_transcripts",
        help="Source type",
    )
    parser.add_argument(
        "--object-name",
        help="Object name under processed/{source_type}/ (e.g. file.pdf or path/to/file.txt)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print required env and example message only",
    )
    parser.add_argument(
        "--create-test-file",
        action="store_true",
        help="Write minimal test file to GCS then run (only zoom_transcripts)",
    )
    args = parser.parse_args()

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
    source_type = args.source_type
    object_name = args.object_name

    if args.create_test_file:
        if source_type != "zoom_transcripts":
            print(
                "Error: --create-test-file is only supported for --source-type zoom_transcripts"
            )
            sys.exit(1)
        print("Creating minimal Zoom transcript in GCS...")
        object_name = create_zoom_test_file(bucket, opportunity_id)
        print(
            f"  Wrote gs://{bucket}/{opportunity_id}/processed/zoom_transcripts/{object_name}"
        )
    elif not object_name:
        print(
            "Error: pass --object-name (or use --create-test-file for zoom_transcripts)"
        )
        sys.exit(1)

    if args.dry_run:
        dry_run(bucket, opportunity_id, source_type, object_name)
        return

    data_path = f"gs://{bucket}/{opportunity_id}/processed/{source_type}/{object_name}"
    message = {
        "source_type": source_type,
        "data_path": data_path,
        "metadata": {
            "opportunity_id": opportunity_id,
            "channel": "gdrive",
            "source_id": object_name,
            "document_id": f"{opportunity_id}/processed/{source_type}/{object_name}",
        },
    }

    print(f"Running IngestionPipeline.run_message() for {data_path} ...")
    pipeline = IngestionPipeline()
    result = pipeline.run_message(message)
    print(f"Result: {result}")
    if result:
        print("Ingestion smoke OK")
    else:
        print("Ingestion returned None (check logs for skip/failure)")
        sys.exit(1)


if __name__ == "__main__":
    main()
