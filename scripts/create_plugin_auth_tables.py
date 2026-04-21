"""DEPRECATED: do not use this script for schema creation.

Schema ownership moved to modular SQL files under db/schema/modules.
Use instead:
    uv run python scripts/db/apply_modular_schema.py

Keep `auth_models.py` for ORM mapping/querying only.
This file is intentionally kept temporarily to avoid accidental breakage in
external references, but execution is blocked to prevent schema drift.
"""

from __future__ import annotations

import sys


def main() -> None:
    print(
        "ERROR: scripts/create_plugin_auth_tables.py is deprecated and disabled.\n"
        "Use: uv run python scripts/db/apply_modular_schema.py",
        file=sys.stderr,
    )
    sys.exit(2)


if __name__ == "__main__":
    main()

"""
Create SQLAlchemy tables for plugin OAuth / sync (users, opportunities, opportunity_sources).

Requires DB env vars in configs/.env and configs/secrets/.env.

Usage (from repo root):
    uv run python scripts/create_plugin_auth_tables.py

If Cloud SQL Connector fails with invalid_grant (stale gcloud user credentials), either:
  - Run: gcloud auth application-default login
  - Or bypass the connector and use TCP (Cloud SQL Auth Proxy or local Postgres):

    set PLUGIN_AUTH_DDL_USE_PG_DIRECT=1
    uv run python scripts/create_plugin_auth_tables.py

When PLUGIN_AUTH_DDL_USE_PG_DIRECT=1, set PG_HOST, PG_PORT, PG_USER, PG_PASSWORD, PG_DATABASE
(e.g. PG_HOST=0.0.0.0 while cloud-sql-proxy is running).
"""

import os
import sys
from pathlib import Path
from urllib.parse import quote_plus


_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Register models on Base before create_all
from google.auth.exceptions import RefreshError
from sqlalchemy import create_engine

from configs.settings import get_settings
from src.services.database_manager.orm import Base


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _direct_tcp_engine():
    s = get_settings().database
    host = (s.pg_host or "").strip()
    if not host:
        print(
            "ERROR: Direct TCP selected but PG_HOST is empty.\n"
            "  Set PG_HOST, PG_USER, PG_PASSWORD, PG_DATABASE in configs (and PG_PORT if not 5432).\n"
            "  For Cloud SQL, run Cloud SQL Auth Proxy locally and use PG_HOST=0.0.0.0.",
            file=sys.stderr,
        )
        sys.exit(1)
    user = quote_plus(s.pg_user or "")
    password = quote_plus(s.pg_password or "")
    db = s.pg_database or "postgres"
    port = s.pg_port
    sslmode = (s.pg_sslmode or "require").strip()
    url = f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db}?sslmode={quote_plus(sslmode)}"
    return create_engine(url)


def main() -> None:
    s = get_settings().database
    cloudsql = (s.cloudsql_instance_connection_name or "").strip()
    force_direct = _truthy_env("PLUGIN_AUTH_DDL_USE_PG_DIRECT")

    if force_direct or not cloudsql:
        if force_direct:
            print("Using direct PostgreSQL (PLUGIN_AUTH_DDL_USE_PG_DIRECT=1).")
        else:
            print(
                "CLOUDSQL_INSTANCE_CONNECTION_NAME is unset — using direct PostgreSQL (PG_*)."
            )
        engine = _direct_tcp_engine()
    else:
        from src.services.database_manager.orm import get_engine

        print(
            "Using Cloud SQL Python Connector (CLOUDSQL_INSTANCE_CONNECTION_NAME is set)."
        )
        engine = get_engine()

    try:
        Base.metadata.create_all(bind=engine)
    except RefreshError as e:
        print(
            "ERROR: Cloud SQL Connector could not refresh credentials (invalid_grant).\n"
            "  Fix A — refresh Application Default Credentials:\n"
            "    gcloud auth application-default login\n"
            "  Fix B — use TCP instead (proxy or local Postgres):\n"
            "    set PLUGIN_AUTH_DDL_USE_PG_DIRECT=1\n"
            "    (set PG_HOST=0.0.0.0 if using cloud-sql-proxy; keep PG_USER/PG_PASSWORD)\n"
            f"\n  Details: {e}",
            file=sys.stderr,
        )
        sys.exit(1)
    except AttributeError as e:
        if "decode" in str(e) and "NoneType" in str(e):
            print(
                "ERROR: PostgreSQL asked for a password but none was supplied (pg8000).\n"
                "  If you use built-in user + password on Cloud SQL:\n"
                "    CLOUDSQL_USE_IAM_AUTH=false\n"
                "    PG_USER=postgres  (or your user)\n"
                "    PG_PASSWORD=<your Cloud SQL password>  in configs/secrets/.env\n"
                "  If you intend IAM database auth:\n"
                "    CLOUDSQL_USE_IAM_AUTH=true\n"
                "    PG_USER=<IAM-enabled DB username>\n"
                "    Ensure IAM is enabled on the instance and the user is created for IAM.\n"
                f"\n  Raw error: {e}",
                file=sys.stderr,
            )
            sys.exit(1)
        raise

    print(
        "create_all finished: users, opportunities, opportunity_sources (if defined on Base)."
    )


if __name__ == "__main__":
    main()
