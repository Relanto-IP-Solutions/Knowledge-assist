"""Zoom VTT transcript preprocessing: parse, clean, and normalise raw VTT bytes into a DataFrame."""

import re

import pandas as pd

from src.utils.logger import get_logger


logger = get_logger(__name__)

DISFLUENCY_PATTERN = re.compile(
    r"\b(?:um|uh|er|erm|you know|you-know|ah|eh|mm|hmm|uhm|uh-huh|kinda|sorta)\b[,\s]*",
    re.IGNORECASE,
)

# Support both LF (\n) and CRLF (\r\n) line endings
VTT_BLOCK_PATTERN = re.compile(
    r"(\d{2}:\d{2}:\d{2}\.\d{3}) --> (\d{2}:\d{2}:\d{2}\.\d{3})\r?\n(.*?)(?=\r?\n\r?\n|\Z)",
    re.DOTALL,
)

_COLUMNS = ["start_time", "end_time", "speaker", "dialogue"]


class VTTPreprocessor:
    """Parse a WebVTT file into a structured DataFrame.

    Pipeline:
        decode bytes → extract cues → remove disfluencies → merge consecutive
        same-speaker cues → return DataFrame[start_time, end_time, speaker, dialogue].
    """

    def preprocess(self, data: bytes) -> pd.DataFrame:
        """Parse raw VTT bytes and return a cleaned, merged transcript as a DataFrame.

        Args:
            data: Raw bytes of a .vtt file.

        Returns:
            DataFrame with columns [start_time, end_time, speaker, dialogue].
            Returns an empty DataFrame with those columns if no cues are found.
        """
        content = data.decode("utf-8")
        raw_cues = self._extract_raw_cues(content)
        merged = self._merge_consecutive_cues(raw_cues)
        if not merged:
            return pd.DataFrame(columns=_COLUMNS)
        df = pd.DataFrame(merged)
        return df[_COLUMNS]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _extract_raw_cues(self, content: str) -> list[dict[str, str]]:
        cues: list[dict[str, str]] = []
        for match in VTT_BLOCK_PATTERN.finditer(content):
            start, end, text_block = match.groups()
            speaker, dialogue = self._split_speaker_dialogue(text_block)
            cues.append({
                "start_time": start,
                "end_time": end,
                "speaker": speaker,
                "dialogue": dialogue,
            })
        return cues

    def _remove_disfluencies(self, text: str) -> str:
        if not text:
            return text
        cleaned = DISFLUENCY_PATTERN.sub("", text)
        cleaned = re.sub(r"\s{2,}", " ", cleaned)
        return cleaned.strip()

    def _clean_speaker(self, speaker: str) -> str:
        """Strip parenthetical role/pronoun suffixes such as '(she/her)' or '(PM)'."""
        speaker = re.sub(r"\s*\([^)]*\)", "", speaker)
        return speaker.strip()

    def _split_speaker_dialogue(self, text_block: str) -> tuple[str, str]:
        """Split a cue text block into (speaker, cleaned_dialogue).

        Falls back to 'Unknown' when no 'Speaker: ...' pattern is present.
        """
        if ": " in text_block:
            raw_speaker, raw_dialogue = text_block.split(": ", 1)
        else:
            raw_speaker, raw_dialogue = "Unknown", text_block
        speaker = self._clean_speaker(raw_speaker)
        dialogue = self._remove_disfluencies(raw_dialogue.replace("\n", " ").strip())
        return speaker, dialogue

    def _merge_consecutive_cues(
        self, cues: list[dict[str, str]]
    ) -> list[dict[str, str]]:
        """Merge back-to-back cues from the same speaker into a single entry."""
        if not cues:
            return []
        merged: list[dict[str, str]] = []
        current = cues[0].copy()
        for next_cue in cues[1:]:
            if next_cue["speaker"] == current["speaker"]:
                current["end_time"] = next_cue["end_time"]
                current["dialogue"] += " " + next_cue["dialogue"]
            else:
                merged.append(current)
                current = next_cue.copy()
        merged.append(current)
        return merged


def parse(data: bytes) -> pd.DataFrame:
    """Parse a WebVTT (.vtt) file and return a cleaned transcript DataFrame.

    Thin module-level shim over VTTPreprocessor for interface compatibility.

    Args:
        data: Raw bytes of a .vtt file.

    Returns:
        DataFrame with columns [start_time, end_time, speaker, dialogue].
    """
    return VTTPreprocessor().preprocess(data)
