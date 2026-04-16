#!/usr/bin/env python3
"""Smoke test: VTT preprocessing as used by the GCS pipeline.

Verifies that VTTPreprocessor (used in GcsPipeline._process_zoom) produces
a DataFrame with the expected shape, columns, speaker labels, and cleaned dialogue.

Usage (from project root):
  uv run python scripts/tests_integration/smoke_vtt_gcs_pipeline.py
  uv run python scripts/tests_integration/smoke_vtt_gcs_pipeline.py path/to/meeting.vtt
"""

import re
import sys
from pathlib import Path


# Allow importing src when run as script
_project_root = Path(__file__).resolve().parent.parent
if _project_root not in sys.path:
    sys.path.insert(0, str(_project_root))

# Sample WebVTT that exercises: timestamps, speaker labels, disfluencies, same-speaker merge
SAMPLE_VTT = b"""WEBVTT

00:00:01.000 --> 00:00:03.500
Alice: So um, let's start with the requirements.

00:00:03.500 --> 00:00:05.000
Alice: We need to capture the technical scope.

00:00:05.500 --> 00:00:08.000
Bob (he/him): Yeah, and uh the timeline as well.

00:00:08.500 --> 00:00:10.000
Bob: Sounds good.
"""

EXPECTED_COLUMNS = ["start_time", "end_time", "speaker", "dialogue"]


def run_smoke(vtt_bytes: bytes, label: str = "inline sample"):
    """Run VTT through the same preprocessor used by the GCS pipeline. Returns DataFrame."""
    from src.services.preprocessing.zoom import VTTPreprocessor

    df = VTTPreprocessor().preprocess(vtt_bytes)
    print(f"\n--- Input: {label} ({len(vtt_bytes)} bytes) ---")
    print(f"--- Output: {len(df)} rows x {len(df.columns)} cols ---")
    print(df.to_string(index=False))
    print("---")
    return df


def assert_expected(df, inline: bool = False) -> None:
    """Basic assertions that the GCS VTT pipeline output DataFrame looks correct."""
    import pandas as pd

    assert isinstance(df, pd.DataFrame), "preprocess() must return a DataFrame"
    assert list(df.columns) == EXPECTED_COLUMNS, (
        f"Expected columns {EXPECTED_COLUMNS}, got {list(df.columns)}"
    )
    assert not df.empty, "Expected at least one merged cue row"

    # All dialogue should be non-empty strings
    assert df["dialogue"].str.strip().ne("").all(), "Found blank dialogue entries"

    # Disfluencies removed from dialogue (standalone um/uh; words like 'consumers' are fine)
    joined = " ".join(df["dialogue"].tolist()).lower()
    assert not re.search(r"\bum\b", joined), (
        "Standalone disfluency 'um' should be removed"
    )
    assert not re.search(r"\buh\b", joined), (
        "Standalone disfluency 'uh' should be removed"
    )

    # Speaker parentheticals stripped (e.g. "Bob (he/him)" → "Bob")
    assert not df["speaker"].str.contains(r"\(", regex=True).any(), (
        "Parenthetical role/pronoun suffixes should be stripped from speaker names"
    )

    # For the inline sample, consecutive same-speaker cues must be merged into fewer rows
    if inline:
        assert len(df) == 2, (
            f"Inline sample: expected 2 merged rows (Alice, Bob), got {len(df)}"
        )
        assert df.iloc[0]["speaker"] == "Alice"
        assert df.iloc[1]["speaker"] == "Bob"

    print("Smoke assertions passed.")


def save_output(df, source_path: Path) -> Path:
    """Write the preprocessed DataFrame as tab-separated text to data/."""
    out_path = _project_root / "data" / (source_path.stem + "_preprocessed.txt")
    df.to_csv(out_path, sep="\t", index=False)
    print(f"Output saved → {out_path}")
    return out_path


def main() -> int:
    if len(sys.argv) > 1:
        path = Path(sys.argv[1])
        if not path.exists():
            print(f"File not found: {path}", file=sys.stderr)
            return 1
        vtt_bytes = path.read_bytes()
        df = run_smoke(vtt_bytes, label=str(path))
        assert_expected(df, inline=False)
        save_output(df, path)
    else:
        df = run_smoke(SAMPLE_VTT, label="inline sample")
        assert_expected(df, inline=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
