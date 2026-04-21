"""Create Cloud SQL PostgreSQL instance and restore data dump.

Uses gcloud CLI to:
1. Create a Cloud SQL PostgreSQL instance (if it doesn't exist) in the configured region
   with the same database name, user, and password from configs/.env
2. Restore dump via either:
   - GCS: upload to bucket, gcloud sql import (default, requires bucket)
   - Local: Cloud SQL Proxy + psql (--local-restore, no GCS needed)

Prerequisites:
- gcloud CLI installed and authenticated: gcloud auth login && gcloud auth application-default login
- Cloud SQL Admin API enabled: gcloud services enable sqladmin.googleapis.com
- For GCS restore: GCS bucket (GCS_BUCKET_INGESTION)
- For local restore (--local-restore): psql (PostgreSQL client) in PATH

Usage:
    uv run python -m scripts.setup.setup_cloudsql_and_restore

    # Restore from local file only (no GCS upload):
    uv run python -m scripts.setup.setup_cloudsql_and_restore --local-restore

    # Skip instance creation (instance already exists):
    uv run python -m scripts.setup.setup_cloudsql_and_restore --no-create-instance
"""

from __future__ import annotations

import argparse
import logging
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from dotenv import load_dotenv


# ---------------------------------------------------------------------------
# Bootstrap: load .env before imports that need it
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_ENV_FILES = [
    _PROJECT_ROOT / "configs" / ".env",
    _PROJECT_ROOT / "configs" / "secrets" / ".env",
]
for _ef in _ENV_FILES:
    if _ef.exists():
        load_dotenv(_ef, override=False)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def _env(name: str, default: str = "") -> str:
    v = os.environ.get(name, default)
    return v.strip() if isinstance(v, str) else str(v or "")


def _parse_connection_name(conn: str) -> tuple[str, str, str]:
    """Parse CLOUDSQL_INSTANCE_CONNECTION_NAME into (project, region, instance)."""
    parts = conn.split(":")
    if len(parts) != 3:
        raise ValueError(
            f"CLOUDSQL_INSTANCE_CONNECTION_NAME must be project:region:instance, got: {conn}"
        )
    return parts[0], parts[1], parts[2]


def _run(
    cmd: list[str], check: bool = True, capture: bool = False
) -> subprocess.CompletedProcess:
    """Run a command, logging it."""
    logger.info("Running: %s", " ".join(cmd))
    result = subprocess.run(
        cmd,
        check=check,
        capture_output=capture,
        text=True,
        shell=False,
    )
    return result


def _instance_exists(project: str, instance: str) -> bool:
    """Check if the Cloud SQL instance exists."""
    try:
        _run(
            [
                "gcloud",
                "sql",
                "instances",
                "describe",
                instance,
                f"--project={project}",
            ],
            capture=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def _create_instance(
    project: str,
    region: str,
    instance: str,
    password: str,
) -> None:
    """Create Cloud SQL PostgreSQL instance with gcloud."""
    cmd = [
        "gcloud",
        "sql",
        "instances",
        "create",
        instance,
        f"--project={project}",
        "--database-version=POSTGRES_16",
        f"--region={region}",
        "--tier=db-f1-micro",  # Smallest tier for dev; use db-g1-small or custom for prod
        "--storage-type=PD_SSD",
        "--storage-size=10GB",
        "--storage-auto-increase",
        f"--root-password={password}",
    ]
    _run(cmd)


def _set_password(project: str, instance: str, password: str) -> None:
    """Set postgres user password (if instance already existed with different password)."""
    _run([
        "gcloud",
        "sql",
        "users",
        "set-password",
        "postgres",
        f"--instance={instance}",
        f"--project={project}",
        f"--password={password}",
    ])


def _preprocess_dump(dump_path: Path) -> Path:
    """Remove or replace non-standard psql commands that Cloud SQL import may reject.

    The dump may contain \\restrict or other psql meta-commands. We comment them out.
    Returns path to a temp file with the cleaned dump.
    """
    with open(dump_path, encoding="utf-8", errors="replace") as f:
        content = f.read()

    lines = content.split("\n")
    out_lines = []
    for line in lines:
        stripped = line.strip()
        # Cloud SQL import may not support \restrict; treat as comment.
        # Keep \. (COPY block terminator) and other standard pg_dump meta-commands.
        if stripped.startswith("\\restrict"):
            out_lines.append("-- " + line)
        else:
            out_lines.append(line)

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".sql",
        delete=False,
        encoding="utf-8",
    ) as tmp:
        tmp.write("\n".join(out_lines))
        return Path(tmp.name)


def _upload_to_gcs(local_path: Path, gcs_uri: str) -> None:
    """Upload file to GCS using gcloud storage cp."""
    _run([
        "gcloud",
        "storage",
        "cp",
        str(local_path),
        gcs_uri,
    ])


def _get_instance_service_account(project: str, instance: str) -> str:
    """Get the Cloud SQL instance's service account email."""
    result = _run(
        [
            "gcloud",
            "sql",
            "instances",
            "describe",
            instance,
            f"--project={project}",
            "--format=value(serviceAccountEmailAddress)",
        ],
        capture=True,
    )
    return result.stdout.strip()


def _grant_bucket_access(project: str, instance: str, bucket: str) -> None:
    """Grant Cloud SQL instance's service account read access to the GCS bucket."""
    sa = _get_instance_service_account(project, instance)
    logger.info("Granting %s Storage Object Viewer on gs://%s", sa, bucket)
    _run([
        "gcloud",
        "storage",
        "buckets",
        "add-iam-policy-binding",
        f"gs://{bucket}",
        f"--member=serviceAccount:{sa}",
        "--role=roles/storage.objectViewer",
        f"--project={project}",
    ])


def _import_sql(
    project: str,
    instance: str,
    gcs_uri: str,
    database: str,
    user: str,
) -> None:
    """Import SQL dump from GCS into Cloud SQL."""
    _run([
        "gcloud",
        "sql",
        "import",
        "sql",
        instance,
        gcs_uri,
        f"--project={project}",
        f"--database={database}",
        f"--user={user}",
        "--quiet",
    ])


def _get_cloud_sql_proxy() -> Path:
    """Find cloud-sql-proxy in PATH or download it."""
    proxy = shutil.which("cloud-sql-proxy") or shutil.which("cloud_sql_proxy")
    if proxy:
        return Path(proxy)
    # Download to temp
    machine = platform.machine().lower()
    system = platform.system().lower()
    version = "v2.14.0"
    base = "https://storage.googleapis.com/cloud-sql-connectors/cloud-sql-proxy"
    if system == "windows":
        ext = ".x64.exe"
    elif system == "darwin":
        ext = (
            ".darwin.arm64"
            if "arm" in machine or "aarch64" in machine
            else ".darwin.amd64"
        )
    else:
        ext = (
            ".linux.arm64"
            if "arm" in machine or "aarch64" in machine
            else ".linux.amd64"
        )
    url = f"{base}/{version}/cloud-sql-proxy{ext}"
    dest = Path(tempfile.gettempdir()) / (
        "cloud-sql-proxy" + (".exe" if system == "windows" else "")
    )
    if not dest.exists():
        logger.info("Downloading Cloud SQL Proxy to %s...", dest)
        try:
            import urllib.request

            urllib.request.urlretrieve(url, dest)
            if system != "windows":
                dest.chmod(0o755)
        except Exception as e:
            raise RuntimeError(
                f"Could not download Cloud SQL Proxy from {url}. "
                f"Install manually: https://cloud.google.com/sql/docs/postgres/connect-auth-proxy#install. {e}"
            ) from e
    return dest


def _restore_via_local(
    conn_name: str,
    dump_path: Path,
    database: str,
    user: str,
    password: str,
    port: int = 5434,
) -> None:
    """Restore dump using Cloud SQL Proxy + psql (no GCS)."""
    psql_path = shutil.which("psql")
    if not psql_path:
        raise RuntimeError(
            "psql not found. Install PostgreSQL client: "
            "Windows: https://www.postgresql.org/download/windows/ | "
            "Mac: brew install postgresql | Linux: apt install postgresql-client"
        )
    proxy_path = _get_cloud_sql_proxy()
    dump_path = dump_path.resolve()
    proxy_proc = None
    try:
        proxy_cmd = [str(proxy_path), f"--port={port}", conn_name]
        logger.info("Starting Cloud SQL Proxy: %s", " ".join(proxy_cmd))
        proxy_proc = subprocess.Popen(
            proxy_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        time.sleep(3)
        if proxy_proc.poll() is not None:
            _, err = proxy_proc.communicate()
            raise RuntimeError(f"Cloud SQL Proxy exited: {err}")
        env = os.environ.copy()
        env["PGPASSWORD"] = password
        logger.info("Restoring dump via psql (this may take several minutes)...")
        _run(
            [
                psql_path,
                "-h",
                "127.0.0.1",
                "-p",
                str(port),
                "-U",
                user,
                "-d",
                database,
                "-f",
                str(dump_path),
            ],
            env=env,
        )
    finally:
        if proxy_proc and proxy_proc.poll() is None:
            proxy_proc.terminate()
            proxy_proc.wait(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create Cloud SQL PostgreSQL instance and restore dump.",
    )
    parser.add_argument(
        "--no-create-instance",
        action="store_true",
        help="Skip instance creation (instance already exists).",
    )
    parser.add_argument(
        "--no-restore",
        action="store_true",
        help="Skip dump restore (only create instance).",
    )
    parser.add_argument(
        "--dump-file",
        type=Path,
        default=_PROJECT_ROOT / "data" / "database_dump" / "postgres_data.db",
        help="Path to the PostgreSQL dump file.",
    )
    parser.add_argument(
        "--gcs-prefix",
        type=str,
        default="cloudsql-dumps",
        help="GCS object prefix for the dump (under the bucket).",
    )
    parser.add_argument(
        "--local-restore",
        action="store_true",
        help="Restore from local dump via Cloud SQL Proxy + psql (no GCS upload). Requires psql.",
    )
    args = parser.parse_args()

    # Load config
    project = _env("GCP_PROJECT_ID") or _env("CLOUDSQL_PROJECT_ID")
    conn_name = _env("CLOUDSQL_INSTANCE_CONNECTION_NAME")
    database = _env("PG_DATABASE", "postgres")
    user = _env("PG_USER", "postgres")
    password = _env("PG_PASSWORD")
    bucket = _env("GCS_BUCKET_INGESTION")

    if conn_name:
        try:
            _proj, region, instance = _parse_connection_name(conn_name)
            if not project:
                project = _proj
        except ValueError as e:
            logger.exception("%s", e)
            return 1
    else:
        project = project or _env("GCP_PROJECT_ID")
        region = _env("VERTEX_AI_LOCATION", "us-central1")
        instance = "your-db-instance"

    if not project:
        logger.error(
            "Set GCP_PROJECT_ID or CLOUDSQL_INSTANCE_CONNECTION_NAME in configs/.env"
        )
        return 1

    if not password and (not args.no_create_instance or args.local_restore):
        logger.error("Set PG_PASSWORD in configs/.env or configs/secrets/.env")
        return 1

    if not bucket and not args.no_restore and not args.local_restore:
        logger.error(
            "Set GCS_BUCKET_INGESTION in configs/.env for dump upload, "
            "or use --local-restore to restore from local file (no GCS), or --no-restore to skip."
        )
        return 1

    if not args.dump_file.exists() and not args.no_restore:
        logger.error("Dump file not found: %s", args.dump_file)
        return 1

    # Step 1: Create instance if needed
    if not args.no_create_instance:
        if _instance_exists(project, instance):
            logger.info(
                "Instance %s already exists. Setting password if needed.", instance
            )
            _set_password(project, instance, password)
        else:
            logger.info("Creating Cloud SQL instance %s in %s...", instance, region)
            _create_instance(project, region, instance, password)
            logger.info("Instance created successfully.")
    else:
        logger.info("Skipping instance creation (--no-create-instance).")

    # Step 2: Restore dump
    if not args.no_restore:
        dump_path = args.dump_file.resolve()
        conn_name = f"{project}:{region}:{instance}"

        if args.local_restore:
            logger.info("Restoring from local file (no GCS)...")
            cleaned_path = _preprocess_dump(dump_path)
            try:
                _restore_via_local(conn_name, cleaned_path, database, user, password)
            finally:
                cleaned_path.unlink(missing_ok=True)
        else:
            gcs_object = f"{args.gcs_prefix}/postgres_dump.sql"
            gcs_uri = f"gs://{bucket}/{gcs_object}"

            logger.info("Granting Cloud SQL service account access to bucket...")
            _grant_bucket_access(project, instance, bucket)

            logger.info("Preprocessing dump (remove non-standard commands)...")
            cleaned_path = _preprocess_dump(dump_path)
            try:
                logger.info("Uploading dump to %s...", gcs_uri)
                _upload_to_gcs(cleaned_path, gcs_uri)

                logger.info(
                    "Importing SQL into Cloud SQL (this may take several minutes)..."
                )
                _import_sql(project, instance, gcs_uri, database, user)
                logger.info("Import completed successfully.")

                _run(["gcloud", "storage", "rm", gcs_uri], check=False)
            finally:
                cleaned_path.unlink(missing_ok=True)

    logger.info("Done. Instance: %s:%s:%s", project, region, instance)
    return 0


if __name__ == "__main__":
    sys.exit(main())
