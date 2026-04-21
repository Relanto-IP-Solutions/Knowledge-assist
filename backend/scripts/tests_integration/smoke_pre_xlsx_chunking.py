#!/usr/bin/env python3
"""Smoke test: chunk ``_pre_xlsx_*.txt`` like document ingestion and print Vertex upsert payloads.

Uses ``DocumentsChunker`` from ``src/services/rag_engine/ingestion/`` (which delegates to
``PreXlsxDocumentsChunker`` for ``_pre_xlsx_*`` blobs — **no** ``excel preprocessing/`` code).

By default reads every ``_pre_xlsx*.txt`` under ``data/input`` (or ``--input-dir``). Use
``--file`` / ``-f`` for an exact path (**quote** names that contain spaces), or ``--glob`` / ``-g``
(e.g. ``-g '*additional_tests*'``) to avoid shell-splitting issues.

Runs table chunking (same limits as ingestion: ``PRE_XLSX_MAX_CHARS_PER_CHUNK``, no overlap),
writes chunk bodies to ``data/output``, and prints ``restricts`` and ``embedding_metadata`` as
used for vector upserts.

**Run from the repository root** (the directory that contains ``scripts/`` and ``src/``),
not from ``excel preprocessing/`` or other subfolders — otherwise Python will not find this file
and relative ``--input-dir ./data/input`` will point at the wrong place.

Usage (repo root):

    cd /path/to/Knowledge-Assist
    uv run python scripts/tests_integration/smoke_pre_xlsx_chunking.py -o oid12345
    uv run python scripts/tests_integration/smoke_pre_xlsx_chunking.py -o oid12345 -f _pre_xlsx_sheet__workbook_1.txt
    uv run python scripts/tests_integration/smoke_pre_xlsx_chunking.py -o oid12345 -g '*additional_tests*'
    uv run python scripts/tests_integration/smoke_pre_xlsx_chunking.py -o oid12345 -f "_pre_xlsx_foo_Copy of bar.txt"
    uv run python scripts/tests_integration/smoke_pre_xlsx_chunking.py -o oid12345 --input-dir ./data/input --output-dir ./data/output

From another directory, pass the script by absolute path (defaults still use the repo that contains this file):

    uv run python /path/to/Knowledge-Assist/scripts/tests_integration/smoke_pre_xlsx_chunking.py -o oid12345
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


# Repo root: parent of scripts/
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.services.rag_engine.ingestion.document_datapoints import (
    build_document_datapoints_for_upsert,
    safe_string_for_datapoint_id,
)
from src.services.rag_engine.ingestion.documents import DocumentsChunker


def _truncate_text_in_meta(meta: dict, max_chars: int = 400) -> dict:
    out = dict(meta)
    t = out.get("text")
    if isinstance(t, str) and len(t) > max_chars:
        out["text"] = t[:max_chars] + f"... [{len(t)} chars total]"
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Smoke test pre-xlsx chunking + upsert payload preview.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Filenames with spaces:
  The shell splits on spaces unless you quote the path, e.g.
    -f "_pre_xlsx_additional_tests_Copy of SCJohnson - Zero Trust SASE - POV - Pre-Reqs & Test Plan .txt"
  Or avoid quoting the full name by using a glob (under --input-dir):
    -g '*additional_tests*'
    -g '*Copy of SCJohnson*Pre-Reqs*'
""",
    )
    parser.add_argument(
        "-f",
        "--file",
        dest="files",
        action="append",
        metavar="NAME",
        default=None,
        help=(
            "Exact file (basename or path under --input-dir). Repeat -f for multiple. "
            "Quote NAME if it contains spaces. Omit -f and -g to process all _pre_xlsx*.txt."
        ),
    )
    parser.add_argument(
        "-g",
        "--glob",
        dest="glob_pattern",
        metavar="PATTERN",
        default=None,
        help=(
            "Glob under --input-dir only (Path.glob). Example: -g '*additional_tests*'. "
            "Use when the filename has spaces so you do not need to quote the whole -f argument."
        ),
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=_REPO_ROOT / "data" / "input",
        help="Directory containing _pre_xlsx*.txt files",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=_REPO_ROOT / "data" / "output",
        help="Directory to write ingest-time chunk .txt files",
    )
    parser.add_argument(
        "-o",
        "--opportunity-id",
        metavar="OPPORTUNITY_ID",
        default="smoke_opp",
        help="Opportunity ID for restricts, embedding_metadata, and chunker logs (default: smoke_opp)",
    )
    parser.add_argument(
        "--channel",
        default="documents",
        help="Sample channel for restricts",
    )
    parser.add_argument(
        "--source-id",
        default="smoke_source",
        help="Sample source_id for restricts",
    )
    parser.add_argument(
        "--document-id",
        default="",
        help="Optional document_id metadata (empty → default opp:documents:object_name)",
    )
    args = parser.parse_args()

    if args.files and args.glob_pattern:
        print("ERROR: use either -f/--file or -g/--glob, not both.", file=sys.stderr)
        sys.exit(2)

    input_dir = args.input_dir.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    if not input_dir.is_dir():
        print(f"ERROR: input dir not found: {input_dir}", file=sys.stderr)
        print(
            f"Hint: repo root is {_REPO_ROOT} — run this script from that directory, or pass "
            f"--input-dir with an absolute path. Current working directory: {Path.cwd()}",
            file=sys.stderr,
        )
        sys.exit(1)
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.glob_pattern:
        paths = sorted(p for p in input_dir.glob(args.glob_pattern) if p.is_file())
        if not paths:
            print(
                f"ERROR: no files match glob {args.glob_pattern!r} under {input_dir}",
                file=sys.stderr,
            )
            print(
                "Hint: quote the pattern if your shell expands * (e.g. -g '*foo*'). "
                "Try: ls data/input | head",
                file=sys.stderr,
            )
            sys.exit(1)
    elif args.files:
        paths = []
        for raw in args.files:
            candidate = Path(raw).expanduser()
            if not candidate.is_absolute():
                candidate = (input_dir / candidate).resolve()
            else:
                candidate = candidate.resolve()
            if not candidate.is_file():
                print(f"ERROR: file not found: {candidate}", file=sys.stderr)
                print(
                    "Hint: if the name has spaces, wrap it in double quotes for -f, or use -g '*part*of*name*'.",
                    file=sys.stderr,
                )
                sys.exit(1)
            if not candidate.name.lower().startswith("_pre_xlsx_"):
                print(
                    f"WARNING: expected a _pre_xlsx_* blob name; continuing anyway: {candidate.name}",
                    file=sys.stderr,
                )
            paths.append(candidate)
        paths = sorted(set(paths), key=str)
    else:
        paths = sorted(input_dir.glob("_pre_xlsx*.txt"))
        if not paths:
            print(f"No _pre_xlsx*.txt under {input_dir}", file=sys.stderr)
            print(
                f"Hint: copy sample ``_pre_xlsx*.txt`` files here, use --input-dir, -f \"quoted name\", or -g '*pattern*'. "
                f"Repo root: {_REPO_ROOT}. CWD: {Path.cwd()}",
                file=sys.stderr,
            )
            sys.exit(1)

    print(
        f"opportunity_id={args.opportunity_id!r}  channel={args.channel!r}  "
        f"source_id={args.source_id!r}  files={len(paths)}",
        flush=True,
    )

    chunker = DocumentsChunker(chunk_size=1500, overlap=300)

    for path in paths:
        object_name = path.name
        content = path.read_bytes()
        chunks = chunker.extract_and_chunk(content, object_name, args.opportunity_id)
        print(f"\n{'=' * 72}\nFILE: {path.name}\n  ingest chunks: {len(chunks)}\n")

        datapoints = build_document_datapoints_for_upsert(
            chunks,
            args.opportunity_id,
            args.channel,
            args.source_id,
            args.document_id,
            object_name,
            safe_string=safe_string_for_datapoint_id,
        )

        stem = path.stem
        for idx, dp in enumerate(datapoints):
            out_path = output_dir / f"{stem}_ingest_chunk_{idx}.txt"
            out_path.write_text(dp["text"], encoding="utf-8")
            print(f"  wrote: {out_path.name}")

        for idx, dp in enumerate(datapoints):
            print(f"\n--- datapoint [{idx}] ---")
            print("datapoint_id:", dp["datapoint_id"])
            print("chunk_id:", dp.get("chunk_id"))
            print("restricts:")
            print(json.dumps(dp["restricts"], indent=2))
            print("embedding_metadata (text truncated for console):")
            print(
                json.dumps(
                    _truncate_text_in_meta(dp["embedding_metadata"]),
                    indent=2,
                )
            )


if __name__ == "__main__":
    main()
