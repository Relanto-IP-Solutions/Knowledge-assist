"""Easy one-command database setup for new machines or projects.

Runs on any computer with minimal config. Prompts for values if not in .env.
Enables APIs, creates bucket if needed, then creates Cloud SQL + restores dump.

Quick start (new machine / new project):
    1. Clone repo, cd into it
    2. uv sync
    3. uv run python -m scripts.setup.setup_database

The script will:
    - Check gcloud is installed and authenticated
    - Prompt for GCP project ID, postgres password, region, instance name (or use .env)
    - Create/update configs/.env and configs/secrets/.env
    - Enable Cloud SQL Admin API
    - Create Cloud SQL instance (or use existing)
    - Restore data/database_dump/postgres_data.db (via GCS upload or --local-restore)

Use --local-restore to restore directly from the local dump file (Cloud SQL Proxy + psql),
skipping GCS bucket creation/upload. Requires psql (PostgreSQL client) installed.
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Bootstrap: ensure project root is on path
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def _run(
    cmd: list[str], check: bool = True, capture: bool = False
) -> subprocess.CompletedProcess:
    result = subprocess.run(
        cmd, check=check, capture_output=capture, text=True, shell=False
    )
    return result


def _check_gcloud() -> bool:
    """Verify gcloud is installed and authenticated."""
    try:
        _run(["gcloud", "version"], capture=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        logger.exception(
            "gcloud CLI not found. Install: https://cloud.google.com/sdk/docs/install"
        )
        return False

    try:
        _run(
            [
                "gcloud",
                "auth",
                "list",
                "--filter=status:ACTIVE",
                "--format=value(account)",
            ],
            capture=True,
        )
    except subprocess.CalledProcessError:
        logger.exception("Not authenticated. Run: gcloud auth login")
        return False

    try:
        _run(
            ["gcloud", "auth", "application-default", "print-access-token"],
            capture=True,
        )
    except subprocess.CalledProcessError:
        logger.exception(
            "Application default credentials not set. Run: gcloud auth application-default login"
        )
        return False

    return True


def _prompt(prompt_text: str, default: str = "") -> str:
    """Prompt user for input with optional default."""
    prompt_text = f"{prompt_text} [{default}]: " if default else f"{prompt_text}: "
    try:
        val = input(prompt_text).strip()
    except EOFError:
        val = ""
    return val or default


def _ensure_env_and_secrets(
    project: str,
    region: str,
    instance: str,
    password: str,
    bucket: str,
) -> None:
    """Create/update configs/.env and configs/secrets/.env with minimal DB config."""
    configs = _PROJECT_ROOT / "configs"
    secrets = configs / "secrets"
    secrets.mkdir(parents=True, exist_ok=True)

    env_path = configs / ".env"
    conn_name = f"{project}:{region}:{instance}"
    bucket = bucket or f"{project}-ingestion"

    # Update or create .env with DB-related vars
    env_lines = []
    if env_path.exists():
        env_lines = env_path.read_text(encoding="utf-8").splitlines()
        skip_keys = (
            "GCP_PROJECT_ID",
            "VERTEX_AI_LOCATION",
            "CLOUDSQL_INSTANCE_CONNECTION_NAME",
            "GCS_BUCKET_INGESTION",
            "PG_DATABASE",
            "PG_USER",
            "PG_HOST",
            "PG_PORT",
            "CLOUDSQL_USE_IAM_AUTH",
        )
        new_lines = []
        for line in env_lines:
            if "# --- Cloud SQL" in (line.strip() or ""):
                continue
            if "=" in line and line.split("=")[0].strip() in skip_keys:
                continue
            new_lines.append(line)
        env_lines = new_lines

    while env_lines and not env_lines[-1].strip():
        env_lines.pop()

    db_section = f"""
# --- Cloud SQL / PostgreSQL (set by setup_database) ---
GCP_PROJECT_ID={project}
VERTEX_AI_LOCATION={region}
CLOUDSQL_INSTANCE_CONNECTION_NAME={conn_name}
GCS_BUCKET_INGESTION={bucket}
PG_DATABASE=postgres
PG_USER=postgres
PG_HOST=
PG_PORT=5432
CLOUDSQL_USE_IAM_AUTH=false
""".strip()

    env_lines.append("")
    env_lines.append(db_section)

    env_path.write_text("\n".join(env_lines) + "\n", encoding="utf-8")
    logger.info("Updated %s", env_path)

    # Secrets: PG_PASSWORD
    secrets_env = secrets / ".env"
    secrets_content = ""
    if secrets_env.exists():
        secrets_content = secrets_env.read_text(encoding="utf-8")
        # Remove old PG_PASSWORD line if present
        lines = [
            line
            for line in secrets_content.splitlines()
            if not line.strip().startswith("PG_PASSWORD=")
        ]
        secrets_content = "\n".join(lines).rstrip()

    if "PG_PASSWORD=" not in secrets_content:
        if secrets_content and not secrets_content.endswith("\n"):
            secrets_content += "\n"
        secrets_content += (
            f"\n# Database password (set by setup_database)\nPG_PASSWORD={password}\n"
        )
        secrets_env.write_text(secrets_content, encoding="utf-8")
        logger.info("Updated %s", secrets_env)


def _enable_apis(project: str) -> None:
    """Enable Cloud SQL Admin and Cloud Storage APIs."""
    apis = ["sqladmin.googleapis.com", "storage.googleapis.com"]
    for api in apis:
        try:
            _run(
                [
                    "gcloud",
                    "services",
                    "enable",
                    api,
                    f"--project={project}",
                ],
                capture=True,
            )
            logger.info("Enabled %s", api)
        except subprocess.CalledProcessError as e:
            logger.warning("Could not enable %s: %s", api, e)


def _ensure_bucket(project: str, bucket: str, region: str) -> None:
    """Create GCS bucket if it doesn't exist."""
    try:
        _run(
            [
                "gcloud",
                "storage",
                "buckets",
                "describe",
                f"gs://{bucket}",
                f"--project={project}",
            ],
            capture=True,
        )
        logger.info("Bucket gs://%s already exists", bucket)
    except subprocess.CalledProcessError:
        logger.info("Creating bucket gs://%s...", bucket)
        _run([
            "gcloud",
            "storage",
            "buckets",
            "create",
            f"gs://{bucket}",
            f"--project={project}",
            f"--location={region}",
        ])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Easy one-command database setup for new machines or projects.",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Fail if .env is missing required values (no prompts).",
    )
    parser.add_argument(
        "--no-create-instance",
        action="store_true",
        help="Skip instance creation (instance already exists).",
    )
    parser.add_argument(
        "--no-restore",
        action="store_true",
        help="Skip dump restore.",
    )
    parser.add_argument(
        "--local-restore",
        action="store_true",
        help="Restore from local dump via Cloud SQL Proxy + psql (no GCS bucket needed).",
    )
    args = parser.parse_args()

    logger.info("=== Knowledge-Assist Database Setup ===\n")

    if not _check_gcloud():
        return 1

    # Load existing .env if present
    from dotenv import load_dotenv

    for p in [
        _PROJECT_ROOT / "configs" / ".env",
        _PROJECT_ROOT / "configs" / "secrets" / ".env",
    ]:
        if p.exists():
            load_dotenv(p, override=False)

    project = os.environ.get("GCP_PROJECT_ID", "").strip()
    region = os.environ.get("VERTEX_AI_LOCATION", "us-central1").strip()
    conn = os.environ.get("CLOUDSQL_INSTANCE_CONNECTION_NAME", "").strip()
    password = os.environ.get("PG_PASSWORD", "").strip()
    bucket = os.environ.get("GCS_BUCKET_INGESTION", "").strip()

    if conn:
        parts = conn.split(":")
        if len(parts) == 3:
            project = project or parts[0]
            region = region or parts[1]
            instance = parts[2]
        else:
            instance = "your-db-instance"
    else:
        instance = "your-db-instance"

    bucket = bucket or (f"{project}-ingestion" if project else "")

    # Interactive prompts for missing values
    if not args.non_interactive:
        if not project:
            project = _prompt("GCP project ID")
        if not password and not args.no_create_instance:
            password = _prompt("Postgres password (for user 'postgres')")
        if not region:
            region = _prompt("Region", "us-central1") or "us-central1"
        if not instance:
            instance = (
                _prompt("Cloud SQL instance name", "your-db-instance")
                or "your-db-instance"
            )
        if not bucket and not args.local_restore:
            bucket = (
                _prompt("GCS bucket for dump upload", f"{project}-ingestion")
                or f"{project}-ingestion"
            )

    if not project:
        logger.error(
            "GCP_PROJECT_ID is required. Set in configs/.env or run interactively."
        )
        return 1
    if not password and (not args.no_create_instance or args.local_restore):
        logger.error(
            "PG_PASSWORD is required. Set in configs/secrets/.env or run interactively."
        )
        return 1
    if not bucket and not args.no_restore and not args.local_restore:
        logger.error(
            "GCS_BUCKET_INGESTION is required for restore. Set in configs/.env or use --local-restore."
        )
        return 1

    _ensure_env_and_secrets(
        project, region, instance, password, bucket or f"{project}-ingestion"
    )
    _enable_apis(project)
    if not args.local_restore and bucket:
        _ensure_bucket(project, bucket, region)

    # Re-load .env after writing
    load_dotenv(_PROJECT_ROOT / "configs" / ".env", override=True)
    load_dotenv(_PROJECT_ROOT / "configs" / "secrets" / ".env", override=True)

    # Run the actual setup (create instance + restore)
    cmd = [sys.executable, "-m", "scripts.setup.setup_cloudsql_and_restore"]
    if args.no_create_instance:
        cmd.append("--no-create-instance")
    if args.no_restore:
        cmd.append("--no-restore")
    if args.local_restore:
        cmd.append("--local-restore")
    result = subprocess.run(cmd, check=False)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
