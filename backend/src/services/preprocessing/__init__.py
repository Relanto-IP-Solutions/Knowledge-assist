"""Per-source preprocessing: parse and normalize raw bytes into clean text.

Each module exposes a parse() function:
    parse(data: bytes) -> str

Modules:
    vtt   — Zoom VTT transcript files
    slack — Slack JSONL export files
    mail  — Gmail thread JSON files (clean, deduplicate, format)
"""
