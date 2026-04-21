"""Browse and query Knowledge-Assist opportunity PostgreSQL tables interactively.

Usage
-----
    # Show row counts for all tables (default)
    uv run python -m scripts.view_pg_data

    # Show all rows in a specific table
    uv run python -m scripts.view_pg_data --table opportunities

    # Limit rows shown
    uv run python -m scripts.view_pg_data --table answers --limit 20

    # Filter by column value
    uv run python -m scripts.view_pg_data --table answers --where "status='confirmed'"

    # Run a raw SQL query
    uv run python -m scripts.view_pg_data --sql "SELECT opportunity_id, status, completeness_pct FROM opportunities"

    # Show table schema (columns + types)
    uv run python -m scripts.view_pg_data --schema opportunities

    # List all tables with row counts
    uv run python -m scripts.view_pg_data --counts
"""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

for _ef in [
    _PROJECT_ROOT / "configs" / ".env",
    _PROJECT_ROOT / "configs" / "secrets" / ".env",
]:
    if _ef.exists():
        load_dotenv(_ef, override=False)

# ---------------------------------------------------------------------------
# All tables in the data model
# ---------------------------------------------------------------------------
ALL_TABLES = [
    "opportunities",
    "questions",
    "answers",
    "answer_versions",
    "citations",
    "conflicts",
    "feedback",
]

# Max column display width
_MAX_COL_WIDTH = 40


# ---------------------------------------------------------------------------
# Connection (reused from create_pg_tables logic)
# ---------------------------------------------------------------------------


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def get_connection():
    """Open and return a database connection (Cloud SQL connector or TCP)."""
    instance_conn_name = _env("CLOUDSQL_INSTANCE_CONNECTION_NAME")

    if instance_conn_name:
        from google.cloud.sql.connector import Connector

        use_iam = _env("CLOUDSQL_USE_IAM_AUTH", "true").lower() == "true"
        db_user = _env("PG_USER")
        db_name = _env("PG_DATABASE", "postgres")
        db_pass = _env("PG_PASSWORD") or None

        connector = Connector()
        if use_iam:
            conn = connector.connect(
                instance_conn_name,
                "pg8000",
                user=db_user,
                db=db_name,
                enable_iam_auth=True,
            )
        else:
            conn = connector.connect(
                instance_conn_name,
                "pg8000",
                user=db_user,
                password=db_pass,
                db=db_name,
            )
        conn.autocommit = True
        return conn, connector

    else:
        import psycopg2

        conn = psycopg2.connect(
            host=_env("PG_HOST", "0.0.0.0"),
            port=int(_env("PG_PORT", "5432")),
            dbname=_env("PG_DATABASE", "postgres"),
            user=_env("PG_USER"),
            password=_env("PG_PASSWORD") or None,
            sslmode="disable",
        )
        conn.autocommit = True
        return conn, None


def run_query(conn, sql: str, params=None):
    """Execute a SELECT and return (columns, rows)."""
    cur = conn.cursor()
    try:
        cur.execute(sql, params or ())
        desc = getattr(cur, "description", None)
        cols = [d[0] for d in desc] if desc else []
        rows = cur.fetchall() or []
        return cols, rows
    finally:
        with contextlib.suppress(Exception):
            cur.close()


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------


def _trunc(val, width: int = _MAX_COL_WIDTH) -> str:
    s = str(val) if val is not None else "NULL"
    s = s.replace("\n", " ").replace("\r", "")
    return s if len(s) <= width else s[: width - 3] + "..."


def print_table(cols: list[str], rows: list, title: str = "") -> None:
    """Pretty-print query results as a fixed-width table."""
    if not cols:
        print("  (no columns)")
        return

    # Calculate column widths
    widths = [len(c) for c in cols]
    display_rows = []
    for row in rows:
        display_row = [_trunc(v) for v in row]
        display_rows.append(display_row)
        for i, cell in enumerate(display_row):
            widths[i] = min(max(widths[i], len(cell)), _MAX_COL_WIDTH)

    sep = "+-" + "-+-".join("-" * w for w in widths) + "-+"
    header = "| " + " | ".join(c.ljust(widths[i]) for i, c in enumerate(cols)) + " |"

    if title:
        print(f"\n{'':=<{len(sep)}}")
        print(f"  {title}")
    print(sep)
    print(header)
    print(sep)
    for row in display_rows:
        print(
            "| "
            + " | ".join(cell.ljust(widths[i]) for i, cell in enumerate(row))
            + " |"
        )
    print(sep)
    print(f"  {len(rows)} row(s)\n")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_counts(conn) -> None:
    """Show row count for every table."""
    print("\n" + "=" * 50)
    print(f"  {'Table':<25} {'Rows':>10}")
    print("-" * 50)
    total = 0
    for table in ALL_TABLES:
        try:
            _, rows = run_query(conn, f"SELECT COUNT(*) FROM {table}")
            count = rows[0][0] if rows else 0
        except Exception as exc:
            count = f"ERR: {exc}"
        total += count if isinstance(count, int) else 0
        print(f"  {table:<25} {count!s:>10}")
    print("-" * 50)
    print(f"  {'TOTAL':<25} {total:>10}")
    print("=" * 50 + "\n")


def cmd_schema(conn, table: str) -> None:
    """Show column definitions for a table."""
    sql = """
        SELECT
            column_name,
            data_type,
            character_maximum_length,
            is_nullable,
            column_default
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name   = %s
        ORDER BY ordinal_position
    """
    cols, rows = run_query(conn, sql, (table,))
    if not rows:
        print(f"\n  Table '{table}' not found or has no columns.\n")
        return
    print_table(cols, rows, title=f"Schema: {table}")

    # also show indexes
    idx_sql = """
        SELECT indexname, indexdef
        FROM pg_indexes
        WHERE schemaname = 'public'
          AND tablename  = %s
        ORDER BY indexname
    """
    icols, irows = run_query(conn, idx_sql, (table,))
    if irows:
        print_table(icols, irows, title=f"Indexes on {table}")


def cmd_table(conn, table: str, limit: int, where: str | None) -> None:
    """Show rows from a table."""
    if table not in ALL_TABLES:
        print(f"\n  Unknown table '{table}'. Available: {', '.join(ALL_TABLES)}\n")
        return

    where_clause = f"WHERE {where}" if where else ""
    sql = f"SELECT * FROM {table} {where_clause} LIMIT {limit}"
    cols, rows = run_query(conn, sql)
    if not rows:
        print(
            f"\n  No rows found in '{table}'"
            + (f" with filter: {where}" if where else "")
            + "\n"
        )
        return
    print_table(
        cols,
        rows,
        title=f"{table}"
        + (f"  [WHERE {where}]" if where else "")
        + f"  [LIMIT {limit}]",
    )


def cmd_sql(conn, sql: str) -> None:
    """Run a raw SQL query and display the results."""
    try:
        cols, rows = run_query(conn, sql)
        print_table(
            cols, rows, title=f"Query: {sql[:60]}{'...' if len(sql) > 60 else ''}"
        )
    except Exception as exc:
        print(f"\n  Query error: {exc}\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="View Knowledge-Assist opportunity data in Cloud SQL (PostgreSQL).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--counts",
        action="store_true",
        help="Show row counts for all tables (default).",
    )
    group.add_argument("--table", metavar="TABLE", help="Show rows from TABLE.")
    group.add_argument(
        "--schema", metavar="TABLE", help="Show column schema for TABLE."
    )
    group.add_argument("--sql", metavar="SQL", help="Run a raw SQL SELECT query.")

    parser.add_argument(
        "--where", metavar="CONDITION", help="SQL WHERE clause (used with --table)."
    )
    parser.add_argument(
        "--limit", type=int, default=50, help="Max rows to display (default: 50)."
    )

    args = parser.parse_args()

    # Connect
    instance_conn_name = _env("CLOUDSQL_INSTANCE_CONNECTION_NAME")
    pg_host = _env("PG_HOST")
    if not instance_conn_name and not pg_host:
        print("ERROR: Set CLOUDSQL_INSTANCE_CONNECTION_NAME or PG_HOST in configs/.env")
        sys.exit(1)

    try:
        conn, connector = get_connection()
    except Exception as exc:
        print(f"Connection failed: {exc}")
        sys.exit(1)

    try:
        # Default: show counts
        if args.table:
            cmd_table(conn, args.table, args.limit, args.where)
        elif args.schema:
            cmd_schema(conn, args.schema)
        elif args.sql:
            cmd_sql(conn, args.sql)
        else:
            cmd_counts(conn)
    finally:
        conn.close()
        if connector:
            connector.close()


if __name__ == "__main__":
    main()
