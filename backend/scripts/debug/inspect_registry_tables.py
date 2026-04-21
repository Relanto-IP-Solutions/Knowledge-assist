"""Inspect document_registry and chunk_registry: fetch sample rows and show column formats.

Run with:
  uv run python scripts/debug/inspect_registry_tables.py
  uv run python scripts/debug/inspect_registry_tables.py --limit-docs 3 --limit-chunks 20

Requires DB config (PG_* or CLOUDSQL_*) in configs/.env or configs/secrets/.env.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from dotenv import load_dotenv

    for _ef in (
        _PROJECT_ROOT / "configs" / ".env",
        _PROJECT_ROOT / "configs" / "secrets" / ".env",
    ):
        if _ef.exists():
            load_dotenv(_ef, override=False)
except ImportError:
    pass


def _describe_columns(cursor) -> list[tuple[str, str]]:
    """Return list of (column_name, type_name) from cursor.description."""
    if not cursor.description:
        return []
    return [
        (d[0], getattr(d[1], "name", str(d[1])) if hasattr(d[1], "name") else str(d[1]))
        for d in cursor.description
    ]


def _format_value(v) -> str:
    """Summarize value for display (type and sample)."""
    if v is None:
        return "NULL"
    t = type(v).__name__
    if isinstance(v, str):
        return f"str(len={len(v)}): {repr(v[:80]) + '...' if len(v) > 80 else repr(v)}"
    if isinstance(v, (int, float, bool)):
        return f"{t}: {v}"
    if hasattr(v, "isoformat"):
        return f"datetime: {v.isoformat()}"
    return f"{t}: {repr(v)[:60]}"


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Inspect document_registry and chunk_registry column formats"
    )
    parser.add_argument(
        "--limit-docs", type=int, default=5, help="Max document_registry rows to fetch"
    )
    parser.add_argument(
        "--limit-chunks", type=int, default=15, help="Max chunk_registry rows to fetch"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON of rows (no format summary)",
    )
    args = parser.parse_args()

    try:
        from src.services.database_manager import get_db_connection, rows_to_dicts
    except Exception as e:
        print(f"Failed to import database_manager: {e}", file=sys.stderr)
        return 1

    con = get_db_connection()
    try:
        cur = con.cursor()

        # --- document_registry ---
        print("=" * 60)
        print("TABLE: document_registry")
        print("=" * 60)
        cur.execute(
            "SELECT document_id, opportunity_id, source_type, gcs_path, doc_hash, total_chunks, created_at, updated_at "
            "FROM document_registry ORDER BY updated_at DESC NULLS LAST LIMIT %s",
            (args.limit_docs,),
        )
        raw_docs = cur.fetchall()
        doc_cols = _describe_columns(cur)
        print("Columns:", [c[0] for c in doc_cols])
        print("Types (approx):", [c[1] for c in doc_cols])
        print()

        rows_docs = rows_to_dicts(cur, raw_docs)
        if not rows_docs:
            print("(no rows in document_registry)")
        else:
            print(f"Sample rows ({len(rows_docs)}):")
            for i, row in enumerate(rows_docs):
                print(f"  --- Row {i + 1} ---")
                for k, v in row.items():
                    print(f"    {k}: {_format_value(v)}")
            if args.json:
                print("\nRaw JSON (document_registry):")
                print(json.dumps(rows_docs, default=str, indent=2))

        # --- chunk_registry ---
        print()
        print("=" * 60)
        print("TABLE: chunk_registry")
        print("=" * 60)
        cur.execute(
            "SELECT chunk_id, document_id, opportunity_id, chunk_index, chunk_hash, datapoint_id, created_at, updated_at "
            "FROM chunk_registry ORDER BY document_id, chunk_index LIMIT %s",
            (args.limit_chunks,),
        )
        raw_chunks = cur.fetchall()
        chunk_cols = _describe_columns(cur)
        print("Columns:", [c[0] for c in chunk_cols])
        print("Types (approx):", [c[1] for c in chunk_cols])
        print()

        rows_chunks = rows_to_dicts(cur, raw_chunks)
        if not rows_chunks:
            print("(no rows in chunk_registry)")
        else:
            print(f"Sample rows ({len(rows_chunks)}):")
            for i, row in enumerate(rows_chunks):
                print(f"  --- Chunk row {i + 1} ---")
                for k, v in row.items():
                    print(f"    {k}: {_format_value(v)}")
            if args.json:
                print("\nRaw JSON (chunk_registry):")
                print(json.dumps(rows_chunks, default=str, indent=2))

        # Summary of formats
        print()
        print("=" * 60)
        print("FORMAT SUMMARY (for ingestion/deletion logic)")
        print("=" * 60)
        if rows_docs:
            r = rows_docs[0]
            print("document_registry:")
            print(f"  document_id   format: e.g. {r.get('document_id')!r}")
            print(f"  opportunity_id: {r.get('opportunity_id')!r}")
            print(f"  source_type: {r.get('source_type')!r}")
            print(f"  gcs_path: {r.get('gcs_path')!r}")
            print(f"  doc_hash: str(len={len(r.get('doc_hash') or '')}) hex")
            print(
                f"  total_chunks: {type(r.get('total_chunks')).__name__} = {r.get('total_chunks')}"
            )
        if rows_chunks:
            r = rows_chunks[0]
            print("chunk_registry:")
            print(f"  chunk_id: {r.get('chunk_id')!r}")
            print(f"  document_id: {r.get('document_id')!r}")
            print(
                f"  chunk_index: {type(r.get('chunk_index')).__name__} = {r.get('chunk_index')}"
            )
            print(f"  datapoint_id: {r.get('datapoint_id')!r}")
            print(f"  chunk_hash: str(len={len(r.get('chunk_hash') or '')}) hex")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1
    finally:
        con.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
