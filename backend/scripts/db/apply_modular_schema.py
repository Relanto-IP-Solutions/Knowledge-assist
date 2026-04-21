"""Apply modular PostgreSQL DDL under db/schema/modules/ in dependency order.

Usage (from repo root):
    uv run python scripts/db/apply_modular_schema.py

Requires the same database env vars as the app (configs/.env, configs/secrets/.env):
    CLOUDSQL_INSTANCE_CONNECTION_NAME or PG_HOST, PG_USER, PG_DATABASE, etc.

This does not drop existing tables. Uses CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv


_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

for _ef in (_ROOT / "configs" / ".env", _ROOT / "configs" / "secrets" / ".env"):
    if _ef.exists():
        load_dotenv(_ef, override=False)

from src.services.database_manager.connection import get_db_connection  # noqa: E402


_CORE_MODULES: tuple[str, ...] = (
    "00_extensions.sql",
    "10_users.sql",
    "20_opportunities.sql",
    "25_user_connections.sql",
    "30_opportunity_sources.sql",
    "40_document_registry.sql",
    "50_chunk_registry.sql",
    "60_sase_batches.sql",
    "65_sase_questions.sql",
    "70_sase_picklist_options.sql",
    "80_answers.sql",
    "85_answer_versions.sql",
    "90_citations.sql",
    "95_conflicts.sql",
    "97_opportunity_question_answers.sql",
    "98_feedback.sql",
    "99_teams.sql",
    "99_team_members.sql",
    "99_audit_log.sql",
)


def _has_executable_sql(sql: str) -> bool:
    body = "\n".join(
        line for line in sql.splitlines() if not line.strip().startswith("--")
    )
    return bool(
        re.search(r"\b(CREATE|ALTER|DROP|SELECT|INSERT|COMMENT)\b", body, re.I)
    )


def _compute_modules_checksum(modules_dir: Path, order: list[str]) -> str:
    hasher = hashlib.sha256()
    for name in order:
        path = modules_dir / name
        content = path.read_text(encoding="utf-8")
        hasher.update(name.encode("utf-8"))
        hasher.update(b"\n")
        hasher.update(content.encode("utf-8"))
        hasher.update(b"\n-- module-separator --\n")
    return hasher.hexdigest()


def _fetch_rows(cur, query: str) -> list[tuple]:
    cur.execute(query)
    return cur.fetchall()


def _compute_schema_fingerprint(cur) -> str:
    # Canonical, order-stable snapshot of public schema metadata.
    snapshot = {
        "tables": _fetch_rows(
            cur,
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
            ORDER BY table_name
            """,
        ),
        "columns": _fetch_rows(
            cur,
            """
            SELECT
                table_name,
                column_name,
                data_type,
                is_nullable,
                COALESCE(column_default, '')
            FROM information_schema.columns
            WHERE table_schema = 'public'
            ORDER BY table_name, ordinal_position
            """,
        ),
        "constraints": _fetch_rows(
            cur,
            """
            SELECT
                tc.table_name,
                tc.constraint_name,
                tc.constraint_type
            FROM information_schema.table_constraints tc
            WHERE tc.table_schema = 'public'
            ORDER BY tc.table_name, tc.constraint_type, tc.constraint_name
            """,
        ),
        "indexes": _fetch_rows(
            cur,
            """
            SELECT
                tablename,
                indexname,
                indexdef
            FROM pg_indexes
            WHERE schemaname = 'public'
            ORDER BY tablename, indexname
            """,
        ),
    }
    payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    args = parser.parse_args()

    modules_dir = _ROOT / "db" / "schema" / "modules"
    if not modules_dir.is_dir():
        print(f"ERROR: modules directory missing: {modules_dir}", file=sys.stderr)
        sys.exit(1)

    order = list(_CORE_MODULES)

    con = get_db_connection()
    try:
        cur = con.cursor()
        for name in order:
            path = modules_dir / name
            if not path.is_file():
                print(f"ERROR: missing module file: {path}", file=sys.stderr)
                sys.exit(1)
            sql = path.read_text(encoding="utf-8")
            if not _has_executable_sql(sql):
                print(f"skip (comments only): {name}")
                continue
            print(f"apply: {name}")
            cur.execute(sql)
        modules_checksum = _compute_modules_checksum(modules_dir, order)
        schema_fingerprint = _compute_schema_fingerprint(cur)
        baseline_path = _ROOT / "db" / "schema" / "last_schema_baseline.json"
        baseline_path.write_text(
            json.dumps(
                {
                    "schema_name": "public",
                    "modules_checksum": modules_checksum,
                    "schema_fingerprint": schema_fingerprint,
                    "applied_at": datetime.now(timezone.utc).isoformat(),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        con.commit()
        print("done.")
        print(f"baseline written: {baseline_path}")
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


if __name__ == "__main__":
    main()
