"""Detect live PostgreSQL schema drift against last apply baseline.

Compares the live DB fingerprint to `db/schema/last_schema_baseline.json`
written by `scripts/db/apply_modular_schema.py`.

Usage (from repo root):
    uv run python scripts/db/check_schema_drift.py

Exit code:
    0 = no drift
    1 = drift detected or baseline missing
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

for _ef in (_ROOT / "configs" / ".env", _ROOT / "configs" / "secrets" / ".env"):
    if _ef.exists():
        load_dotenv(_ef, override=False)

from scripts.db.apply_modular_schema import _CORE_MODULES  # noqa: E402
from src.services.database_manager.connection import get_db_connection  # noqa: E402

_BASELINE_FILE = _ROOT / "db" / "schema" / "last_schema_baseline.json"


def _compute_modules_checksum(modules_dir: Path, order: list[str]) -> str:
    hasher = hashlib.sha256()
    for name in order:
        content = (modules_dir / name).read_text(encoding="utf-8")
        hasher.update(name.encode("utf-8"))
        hasher.update(b"\n")
        hasher.update(content.encode("utf-8"))
        hasher.update(b"\n-- module-separator --\n")
    return hasher.hexdigest()


def _fetch_rows(cur, query: str) -> list[tuple]:
    cur.execute(query)
    return cur.fetchall()


def _compute_schema_fingerprint(cur) -> str:
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


def main() -> int:
    modules_dir = _ROOT / "db" / "schema" / "modules"
    order = list(_CORE_MODULES)
    expected_modules_checksum = _compute_modules_checksum(modules_dir, order)

    if not _BASELINE_FILE.is_file():
        print(
            "DRIFT CHECK FAILED: missing baseline file db/schema/last_schema_baseline.json. "
            "Run: uv run python scripts/db/apply_modular_schema.py"
        )
        return 1

    try:
        baseline = json.loads(_BASELINE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"DRIFT CHECK FAILED: invalid baseline file: {e}")
        return 1

    baseline_modules_checksum = baseline.get("modules_checksum")
    baseline_schema_fingerprint = baseline.get("schema_fingerprint")
    baseline_applied_at = baseline.get("applied_at", "")

    if not baseline_modules_checksum or not baseline_schema_fingerprint:
        print("DRIFT CHECK FAILED: baseline file is incomplete. Re-run apply_modular_schema.py.")
        return 1

    con = get_db_connection()
    try:
        cur = con.cursor()
        current_schema_fingerprint = _compute_schema_fingerprint(cur)

        drift_messages: list[str] = []
        if baseline_modules_checksum != expected_modules_checksum:
            drift_messages.append(
                "Module checksum mismatch (repo modules changed since last baseline)."
            )
        if baseline_schema_fingerprint != current_schema_fingerprint:
            drift_messages.append(
                "Live schema fingerprint mismatch (possible manual DB DDL or drift)."
            )

        if drift_messages:
            print("SCHEMA DRIFT DETECTED:")
            for msg in drift_messages:
                print(f"- {msg}")
            print(f"- Baseline applied_at: {baseline_applied_at}")
            print("- Action: run scripts/db/apply_modular_schema.py via approved pipeline.")
            return 1

        print("No schema drift detected.")
        print(f"Baseline applied_at: {baseline_applied_at}")
        return 0
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
