"""Zoom transcript parsing and time-window chunking for RAG ingestion.

Expects tab-separated transcript (start_time, end_time, speaker, dialogue).
Parses to segments, chunks by time windows with overlap, returns chunk dicts.
Uses same disfluency cleaning pattern as preprocessing/zoom/vtt.py.
Used by IngestionPipeline for source_type=zoom_transcripts.
"""

from __future__ import annotations

import re

from src.utils.logger import get_logger


logger = get_logger(__name__)

# Same disfluency pattern as in src.services.preprocessing.zoom.vtt
DISFLUENCY_PATTERN = re.compile(
    r"\b(?:um|uh|er|erm|you know|you-know|ah|eh|mm|hmm|uhm|uh-huh|kinda|sorta)\b[,\s]*",
    re.IGNORECASE,
)


class ZoomTranscriptsChunker:
    """Parse tab-format Zoom transcript and chunk by time windows."""

    def __init__(
        self,
        window_minutes: int = 3,
        overlap_minutes: int = 1,
    ) -> None:
        self.window_minutes = window_minutes
        self.overlap_minutes = overlap_minutes

    @staticmethod
    def _preprocess_text(text: str) -> str:
        """Remove disfluencies and normalize whitespace."""
        if not text:
            return ""
        cleaned = DISFLUENCY_PATTERN.sub("", text)
        return re.sub(r"\s{2,}", " ", cleaned).strip()

    @staticmethod
    def _timestamp_to_seconds(timestamp: str) -> int:
        """Convert HH:MM:SS or HH:MM:SS.fff to seconds."""
        parts = timestamp.strip().split(":")
        if len(parts) < 3:
            return 0
        h, m = int(parts[0]), int(parts[1])
        s = float(parts[2])
        return int(h) * 3600 + int(m) * 60 + int(s)

    def _parse_structured_transcript(self, text: str) -> list[dict]:
        """Parse tab-separated lines: start_time, end_time, speaker, dialogue.

        First line is assumed to be header (e.g. start_time\tend_time\tspeaker\tdialogue).
        """
        lines = text.splitlines()
        segments: list[dict] = []
        for line in lines[1:]:
            parts = line.split("\t")
            if len(parts) < 4:
                continue
            try:
                start_seconds = self._timestamp_to_seconds(parts[0])
                end_seconds = self._timestamp_to_seconds(parts[1])
            except (ValueError, IndexError):
                logger.warning(
                    "Failed to parse timestamp in Zoom transcript line", exc_info=True
                )
                continue
            speaker = parts[2].strip()
            dialogue = parts[3].strip()
            segments.append({
                "start": start_seconds,
                "end": end_seconds,
                "text": f"{speaker}: {dialogue}",
            })
        return segments

    def _chunk_by_time(
        self,
        segments: list[dict],
    ) -> list[dict]:
        """Group segments into time windows; each chunk has text, start_time, end_time."""
        if not segments:
            return []
        window = self.window_minutes * 60
        overlap = self.overlap_minutes * 60
        step = window - overlap
        max_time = segments[-1]["end"]
        chunks: list[dict] = []
        start_time = 0
        while start_time <= max_time:
            end_time = start_time + window
            parts = [
                seg["text"] for seg in segments if start_time <= seg["start"] < end_time
            ]
            if parts:
                combined = self._preprocess_text(" ".join(parts))
                if combined:
                    chunks.append({
                        "text": combined,
                        "start_time": start_time,
                        "end_time": end_time,
                    })
            start_time += step
        return chunks

    def chunk(self, transcript_text: str, opportunity_id: str = "") -> list[dict]:
        """Parse tab-format transcript and return time-window chunks.

        Expects first line to be header (start_time\tend_time\tspeaker\tdialogue).
        Returns empty list if format is not recognized or no segments.

        Args:
            transcript_text: Full transcript string (tab-separated).
            opportunity_id: Opportunity ID for log correlation.

        Returns:
            List of dicts with keys: text, start_time, end_time.
        """
        if not transcript_text or not transcript_text.strip():
            return []
        if not transcript_text.lstrip().startswith("start_time"):
            logger.bind(opportunity_id=opportunity_id).warning(
                "Zoom transcripts chunker: unknown format (expected start_time header)"
            )
            return []

        logger.bind(opportunity_id=opportunity_id).info(
            "Zoom transcripts chunker: parsing and chunking"
        )
        segments = self._parse_structured_transcript(transcript_text)
        if not segments:
            logger.bind(opportunity_id=opportunity_id).warning(
                "Zoom transcripts chunker: no segments parsed"
            )
            return []

        chunks = self._chunk_by_time(segments)
        logger.bind(opportunity_id=opportunity_id).info(
            "Zoom transcripts chunker: produced chunks — chunk_count=%s",
            len(chunks),
        )
        return chunks
