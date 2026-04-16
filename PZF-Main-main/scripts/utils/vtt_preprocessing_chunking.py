"""
Preprocess a VTT file and chunk it into 2-minute windows with 30s overlap.
Single script: preprocessing (disfluency removal, speaker merge) + chunking.
Writes one JSON file per chunk to the output directory.

Run from project root:
  uv run python scripts/utils/vtt_preprocessing_chunking.py src/data/AIR-232.vtt -o src/data/chunks
"""

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd


# Ensure project root is on path when running script directly
_project_root = Path(__file__).resolve().parent.parent
if _project_root not in sys.path:
    sys.path.insert(0, str(_project_root))

from src.utils.logger import get_logger


logger = get_logger(__name__)


# --- Preprocessing (VTT parse, disfluencies, speaker merge) ---

DISFLUENCY_PATTERN = re.compile(
    r"\b(?:um|uh|er|erm|you know|you-know|ah|eh|mm|hmm|uhm|uh-huh|kinda|sorta)\b[,\s]*",
    re.IGNORECASE,
)

VTT_BLOCK_PATTERN = re.compile(
    r"(\d{2}:\d{2}:\d{2}\.\d{3}) --> (\d{2}:\d{2}:\d{2}\.\d{3})\n(.*?)(?=\n\n|\Z)",
    re.DOTALL,
)


def _remove_disfluencies(text: str) -> str:
    if not text:
        return text
    cleaned = DISFLUENCY_PATTERN.sub("", text)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    return cleaned.strip()


def _read_vtt(vtt_file_path: str) -> str:
    with open(vtt_file_path, encoding="utf-8") as f:
        return f.read()


def _clean_speaker(speaker: str) -> str:
    speaker = re.sub(r"\s*\([^)]*\)", "", speaker)
    return speaker.strip()


def _clean_dialogue(dialogue: str) -> str:
    dialogue = dialogue.replace("\n", " ").strip()
    return _remove_disfluencies(dialogue)


def _split_speaker_and_dialogue(text_block: str) -> tuple[str, str]:
    if ": " in text_block:
        raw_speaker, raw_dialogue = text_block.split(": ", 1)
    else:
        raw_speaker, raw_dialogue = "Unknown", text_block
    return _clean_speaker(raw_speaker), _clean_dialogue(raw_dialogue)


def _extract_raw_cues(vtt_content: str) -> list[dict[str, str]]:
    raw_cues: list[dict[str, str]] = []
    for match in VTT_BLOCK_PATTERN.finditer(vtt_content):
        start, end, text_block = match.groups()
        speaker, dialogue = _split_speaker_and_dialogue(text_block)
        raw_cues.append({
            "start_time": start,
            "end_time": end,
            "speaker": speaker,
            "dialogue": dialogue,
        })
    return raw_cues


def _merge_consecutive_cues(raw_cues: list[dict[str, str]]) -> list[dict[str, str]]:
    if not raw_cues:
        return []
    merged: list[dict[str, str]] = []
    current = raw_cues[0].copy()
    for next_cue in raw_cues[1:]:
        if next_cue["speaker"] == current["speaker"]:
            current["end_time"] = next_cue["end_time"]
            current["dialogue"] += " " + next_cue["dialogue"]
        else:
            merged.append(current)
            current = next_cue.copy()
    merged.append(current)
    return merged


def preprocess_vtt(vtt_file_path: str) -> pd.DataFrame:
    """Parse VTT, remove disfluencies, merge consecutive speaker cues; return DataFrame."""
    content = _read_vtt(vtt_file_path)
    raw = _extract_raw_cues(content)
    merged = _merge_consecutive_cues(raw)
    if not merged:
        return pd.DataFrame(columns=["start_time", "end_time", "speaker", "dialogue"])
    df = pd.DataFrame(merged)
    return df[["start_time", "end_time", "speaker", "dialogue"]]


# --- Chunking (2 min windows, 30s overlap) ---

CHUNK_DURATION_SEC = 120
OVERLAP_SEC = 30


def _time_str_to_seconds(time_str: str) -> float:
    parts = time_str.strip().split(":")
    if len(parts) != 3:
        return 0.0
    h, m, s = int(parts[0]), int(parts[1]), float(parts[2])
    return h * 3600 + m * 60 + s


def _seconds_to_time_str(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    sec_int = int(s)
    ms = round((s - sec_int) * 1000) % 1000
    return f"{h:02d}:{m:02d}:{sec_int:02d}.{ms:03d}"


def _chunk_windows(
    total_duration_sec: float,
    chunk_duration_sec: float = CHUNK_DURATION_SEC,
    overlap_sec: float = OVERLAP_SEC,
) -> list[tuple[float, float]]:
    step = chunk_duration_sec - overlap_sec
    windows: list[tuple[float, float]] = []
    start = 0.0
    while start < total_duration_sec:
        end = min(start + chunk_duration_sec, total_duration_sec)
        windows.append((start, end))
        if end >= total_duration_sec:
            break
        start += step
    return windows


def _format_chunk_text(df_chunk: pd.DataFrame) -> str:
    lines = [
        f"{row['speaker']} : {str(row['dialogue']).strip()}"
        for _, row in df_chunk.iterrows()
    ]
    return "\n".join(lines)


def _get_cues_in_window(
    df: pd.DataFrame, start_sec: float, end_sec: float
) -> pd.DataFrame:
    def overlaps(row: pd.Series) -> bool:
        s = _time_str_to_seconds(row["start_time"])
        e = _time_str_to_seconds(row["end_time"])
        return s < end_sec and e > start_sec

    return df[df.apply(overlaps, axis=1)].copy()


def _build_chunk_payload(
    text: str,
    transcript_id: str,
    file_name: str,
    chunk_start_sec: float,
    chunk_end_sec: float,
    date_iso: str | None = None,
) -> dict[str, Any]:
    time_duration = f"{_seconds_to_time_str(chunk_start_sec)} - {_seconds_to_time_str(chunk_end_sec)}"
    generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    metadata: dict[str, Any] = {
        "transcript_id": transcript_id,
        "generated_at": generated_at,
        "file": file_name,
        "date": date_iso or "",
        "opportunity_id": transcript_id,
        "time_duration": time_duration,
    }
    return {"text": text, "metadata": metadata}


def _chunk_and_write(
    df: pd.DataFrame,
    transcript_id: str,
    file_name: str,
    output_dir: Path,
    date_iso: str | None = None,
) -> list[Path]:
    if df.empty:
        return []
    last_end = df["end_time"].iloc[-1]
    total_sec = _time_str_to_seconds(last_end)
    windows = _chunk_windows(total_sec)
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for i, (start_sec, end_sec) in enumerate(windows, start=1):
        df_chunk = _get_cues_in_window(df, start_sec, end_sec)
        if df_chunk.empty:
            continue
        text = _format_chunk_text(df_chunk)
        payload = _build_chunk_payload(
            text, transcript_id, file_name, start_sec, end_sec, date_iso
        )
        out_file = output_dir / f"{transcript_id}_chunk_{i:03d}.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        written.append(out_file)
    return written


# --- Entrypoint ---


def run_preprocess_and_chunk(
    vtt_path: str | Path,
    output_dir: str | Path,
    transcript_id: str | None = None,
    date_iso: str | None = None,
) -> list[Path]:
    """Preprocess VTT and write one JSON chunk file per 2-min window (30s overlap)."""
    vtt_path = Path(vtt_path)
    output_dir = Path(output_dir)
    if not vtt_path.exists():
        raise FileNotFoundError(f"VTT file not found: {vtt_path}")

    tid = transcript_id or vtt_path.stem
    file_name = vtt_path.name

    logger.info(
        "Preprocessing VTT", extra={"file": str(vtt_path), "transcript_id": tid}
    )
    df = preprocess_vtt(str(vtt_path))

    if df.empty:
        logger.warning("No cues extracted from VTT", extra={"file": str(vtt_path)})
        return []

    written = _chunk_and_write(df, tid, file_name, output_dir, date_iso)
    logger.info(
        "Chunking complete",
        extra={
            "transcript_id": tid,
            "chunk_count": len(written),
            "output_dir": str(output_dir),
        },
    )
    return written


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Preprocess VTT and chunk into 2-min windows with 30s overlap.",
    )
    parser.add_argument("vtt_file", type=Path, help="Path to the .vtt file")
    parser.add_argument(
        "-o",
        "--output-dir",
        type=Path,
        default=Path("src/data/chunks"),
        help="Directory for chunk JSON files (default: src/data/chunks)",
    )
    parser.add_argument(
        "--transcript-id",
        type=str,
        default=None,
        help="Transcript/opportunity ID (default: stem of VTT filename)",
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="ISO date for metadata (e.g. 2026-01-06T14:30:00+05:30)",
    )
    args = parser.parse_args()

    run_preprocess_and_chunk(
        vtt_path=args.vtt_file,
        output_dir=args.output_dir,
        transcript_id=args.transcript_id,
        date_iso=args.date,
    )


if __name__ == "__main__":
    main()
