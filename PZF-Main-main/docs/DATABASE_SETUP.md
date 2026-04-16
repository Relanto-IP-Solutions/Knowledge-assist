# Database Setup — Quick Start

Set up Cloud SQL PostgreSQL and restore the data dump on any machine or project in a few commands.

## Prerequisites

- **gcloud CLI** — [Install](https://cloud.google.com/sdk/docs/install)
- **uv** — `pip install uv` or [Install](https://docs.astral.sh/uv/)
- **GCP project** with billing enabled
- **psql** (for `--local-restore`) — PostgreSQL client: [Windows](https://www.postgresql.org/download/windows/) | Mac: `brew install postgresql` | Linux: `apt install postgresql-client`

## Setup in 3 commands

```powershell
# 1. Clone and enter project
git clone <repo-url>
cd <your-repo-folder>

# 2. Install dependencies
uv sync

# 3. Run setup (prompts for project ID, password, etc.)
uv run python -m scripts.setup_database

# Or restore directly from local dump (no GCS bucket needed):
uv run python -m scripts.setup_database --local-restore
```

Or on Windows with the launcher:

```powershell
.\setup.ps1
```

On Linux/Mac:

```bash
chmod +x setup.sh
./setup.sh
```

## What the script does

1. Checks gcloud is installed and authenticated
2. Prompts for GCP project ID, postgres password, region, instance name (and GCS bucket unless `--local-restore`)
3. Creates/updates `configs/.env` and `configs/secrets/.env`
4. Enables Cloud SQL Admin and Storage APIs
5. Creates GCS bucket if needed (skipped with `--local-restore`)
6. Creates Cloud SQL PostgreSQL instance (or uses existing)
7. Restores `data/database_dump/postgres_data.db`:
   - **Default**: uploads to GCS, then `gcloud sql import`
   - **`--local-restore`**: uses Cloud SQL Proxy + psql directly (no GCS)

## First-time gcloud setup

If gcloud is not configured:

```powershell
gcloud auth login
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
```

## Non-interactive (CI / automation)

When `configs/.env` and `configs/secrets/.env` are already configured:

```powershell
uv run python -m scripts.setup_database --non-interactive
```

## Restore from local file (no GCS)

Use `--local-restore` to restore directly from the dump file. The script downloads Cloud SQL Proxy if needed and uses `psql` to apply the dump. No GCS bucket required.

```powershell
uv run python -m scripts.setup_database --local-restore
```

Requires **psql** (PostgreSQL client) in PATH.

## Skip instance creation or restore

```powershell
# Instance exists, only restore dump
uv run python -m scripts.setup_database --no-create-instance

# Restore locally without GCS (instance must exist)
uv run python -m scripts.setup_database --no-create-instance --local-restore

# Only create instance, skip restore
uv run python -m scripts.setup_database --no-restore
```

## Config reference

| Variable | Description | Example |
|----------|-------------|---------|
| `GCP_PROJECT_ID` | GCP project | `my-project` |
| `VERTEX_AI_LOCATION` | Region for Cloud SQL | `us-central1` |
| `CLOUDSQL_INSTANCE_CONNECTION_NAME` | `project:region:instance` | `my-project:us-central1:your-db-instance` |
| `GCS_BUCKET_INGESTION` | Bucket for dump upload | `my-project-ingestion` |
| `PG_PASSWORD` | postgres user password | (in `configs/secrets/.env`) |
