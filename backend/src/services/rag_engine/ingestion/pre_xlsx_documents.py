"""Preprocessed Excel-as-text chunking for RAG (``_pre_xlsx_*.txt`` blobs).

Same role as ``SlackMessagesChunker`` / ``ZoomTranscriptsChunker``: dedicated chunker for one
source shape. All logic lives here — **no dependency** on any ``excel preprocessing/`` scripts.

Expected blob naming (preprocessor output):
``_pre_xlsx_<sheet_token>__<filename_token>_<chunk_index>.txt``
(double underscore separates sheet from filename tokens).

Chunking: column-count row cap (10 rows if >8 columns else 20) plus greedy packing
≤ ``max_chars_per_chunk`` (default ``PRE_XLSX_MAX_CHARS_PER_CHUNK``); full rows only, no overlap.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.utils.logger import get_logger


logger = get_logger(__name__)

# Wider than generic document chunks (1500): wide tables need more room per vector chunk.
PRE_XLSX_MAX_CHARS_PER_CHUNK = 3000

_ROW_LINE_RE = re.compile(r"^Row\s+(\d+):\s*(.*)$", re.DOTALL)

_PRE_XLSX_DOUBLE_UNDERSCORE_RE = re.compile(
    r"^_pre_xlsx_(.+)__(.+)_(\d+)\.(?:txt|text)$",
    re.IGNORECASE,
)
_PRE_XLSX_TAIL_INDEX_RE = re.compile(
    r"^_pre_xlsx_(.+)_(\d+)\.(?:txt|text)$",
    re.IGNORECASE,
)


@dataclass
class _PreprocessedSpreadsheetTable:
    file_name: str
    sheet_name: str
    columns: list[str]
    rows: list[tuple[int, list[str]]]


class PreXlsxDocumentsChunker:
    """Chunk preprocessed spreadsheet text bytes for document ingestion."""

    def __init__(self, max_chars_per_chunk: int = PRE_XLSX_MAX_CHARS_PER_CHUNK) -> None:
        self.max_chars_per_chunk = max_chars_per_chunk

    @staticmethod
    def is_pre_xlsx_blob(blob_name: str) -> bool:
        base = blob_name.rsplit("/", 1)[-1]
        return base.lower().startswith("_pre_xlsx_")

    @staticmethod
    def parse_pre_xlsx_blob_stem(
        blob_name: str,
    ) -> tuple[str | None, str | None, int | None]:
        """Parse basename: ``_pre_xlsx_<sheet>__<file>_<n>.txt`` or tail ``_<n>.txt`` only."""
        base = blob_name.rsplit("/", 1)[-1]
        m = _PRE_XLSX_DOUBLE_UNDERSCORE_RE.match(base)
        if m:
            return (
                m.group(1).replace("_", " "),
                m.group(2).replace("_", " "),
                int(m.group(3)),
            )
        m2 = _PRE_XLSX_TAIL_INDEX_RE.match(base)
        if m2:
            return None, None, int(m2.group(2))
        return None, None, None

    def _parse_table(
        self, text: str, path_hint: str = ""
    ) -> _PreprocessedSpreadsheetTable:
        lines = [ln.rstrip() for ln in text.splitlines()]
        file_name, sheet_name = "", ""
        columns: list[str] = []
        rows: list[tuple[int, list[str]]] = []
        i, n = 0, len(lines)
        while i < n:
            line = lines[i]
            if line.startswith("FILE:"):
                file_name = line[5:].strip()
            elif line.startswith("SHEET:"):
                sheet_name = line[6:].strip()
            elif line.startswith("COLUMNS:"):
                rest = line[len("COLUMNS:") :].strip()
                if rest:
                    columns = [c.strip() for c in rest.split(" | ")]
                    i += 1
                    continue
                i += 1
                while i < n and not lines[i].strip():
                    i += 1
                if i < n:
                    columns = [c.strip() for c in lines[i].split(" | ")]
                i += 1
                continue
            elif line == "ROWS:":
                i += 1
                continue
            m = _ROW_LINE_RE.match(line)
            if m:
                rest = m.group(2)
                vals = [v.strip() for v in rest.split(" | ")] if rest else []
                nc = len(columns) or len(vals)
                while len(vals) < nc:
                    vals.append("")
                rows.append((int(m.group(1)), vals[:nc]))
            i += 1
        hint = path_hint or ""
        return _PreprocessedSpreadsheetTable(
            file_name or hint,
            sheet_name or "UNKNOWN",
            columns,
            rows,
        )

    @staticmethod
    def _row_line(cols: list[str], rnum: int, vals: list[str]) -> str:
        nc = len(cols)
        v = list(vals[:nc]) if len(vals) >= nc else list(vals) + [""] * (nc - len(vals))
        return f"Row {rnum}: " + " | ".join(v)

    def _chunk_table(self, table: _PreprocessedSpreadsheetTable) -> list[str]:
        if not table.rows or not table.columns:
            return []
        cols = table.columns
        row_limit = 10 if len(cols) > 8 else 20
        col_line = "COLUMNS:" + " | ".join(cols)
        max_c = self.max_chars_per_chunk
        chunks: list[str] = []

        lines: list[str] = [col_line]
        size = len(col_line)
        rows_in_chunk = 0

        def flush() -> None:
            nonlocal lines, size, rows_in_chunk
            if len(lines) > 1:
                chunks.append("\n".join(lines) + "\n")
            lines = [col_line]
            size = len(col_line)
            rows_in_chunk = 0

        for rnum, vals in table.rows:
            rl = self._row_line(cols, rnum, vals)
            inc = 1 + len(rl)

            if rows_in_chunk >= row_limit:
                flush()

            if size + inc <= max_c:
                lines.append(rl)
                size += inc
                rows_in_chunk += 1
            elif len(lines) == 1:
                chunks.append(f"{col_line}\n{rl}" + "\n")
                lines = [col_line]
                size = len(col_line)
                rows_in_chunk = 0
            else:
                flush()
                lines = [col_line, rl]
                size = len(col_line) + inc
                rows_in_chunk = 1

        if len(lines) > 1:
            chunks.append("\n".join(lines) + "\n")
        return chunks

    def chunk(
        self, content: bytes, blob_name: str, opportunity_id: str = ""
    ) -> list[str]:
        """Parse UTF-8 spreadsheet text and return chunk strings for embedding."""
        logger.bind(opportunity_id=opportunity_id).info(
            "Pre-xlsx documents chunker: table chunking"
        )
        text = content.decode("utf-8", errors="replace")
        table = self._parse_table(text, path_hint=blob_name)
        chunks = self._chunk_table(table)
        logger.bind(opportunity_id=opportunity_id).info(
            "Pre-xlsx documents chunker: chunk_count=%s",
            len(chunks),
        )
        return chunks
