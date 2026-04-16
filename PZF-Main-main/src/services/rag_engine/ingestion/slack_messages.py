"""Slack section-based chunking for RAG ingestion.

Takes sectioned plain text (e.g. from SlackAnalysisFormatter with ===== SECTION =====)
and returns chunks by section with optional splitting of large sections.
Used by IngestionPipeline for source_type=slack_messages.
"""

from __future__ import annotations

import re

from src.utils.logger import get_logger


logger = get_logger(__name__)

# Section header pattern matching formatter output (==== TITLE ====)
SECTION_PATTERN = re.compile(
    r"=+\s*\n\s*([A-Z][A-Z &]+?)\s*\n=+",
    re.MULTILINE,
)

DEFAULT_MAX_CHARS_PER_CHUNK = 4500


class SlackMessagesChunker:
    """Chunk sectioned Slack summary text by section boundaries and size."""

    def __init__(self, max_chars_per_chunk: int = DEFAULT_MAX_CHARS_PER_CHUNK) -> None:
        self.max_chars_per_chunk = max_chars_per_chunk

    @staticmethod
    def _preprocess(text: str) -> str:
        """Normalize whitespace."""
        return re.sub(r"\s{2,}", " ", text).strip()

    def _split_into_sections(self, text: str) -> dict[str, str]:
        """Split text by section headers; return dict of section_name -> content."""
        matches = list(SECTION_PATTERN.finditer(text))
        sections: dict[str, str] = {}
        for i, match in enumerate(matches):
            section_name = match.group(1).strip()
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            sections[section_name] = text[start:end].strip()
        return sections

    def _split_large_section(
        self,
        section_name: str,
        content: str,
    ) -> list[dict]:
        """Split a section into parts if it exceeds max_chars_per_chunk."""
        if len(content) <= self.max_chars_per_chunk:
            return [
                {
                    "section": section_name,
                    "part": 1,
                    "text": self._preprocess(content),
                }
            ]
        paragraphs = content.split("\n\n")
        chunks: list[dict] = []
        current_text = ""
        part = 1
        for para in paragraphs:
            if len(current_text) + len(para) < self.max_chars_per_chunk:
                current_text += "\n\n" + para if current_text else para
            else:
                if current_text.strip():
                    chunks.append({
                        "section": section_name,
                        "part": part,
                        "text": self._preprocess(current_text.strip()),
                    })
                    part += 1
                current_text = para
        if current_text.strip():
            chunks.append({
                "section": section_name,
                "part": part,
                "text": self._preprocess(current_text.strip()),
            })
        return chunks

    def chunk(self, sectioned_text: str, opportunity_id: str = "") -> list[dict]:
        """Chunk sectioned Slack summary text into a list of dicts.

        Each dict has: section, part, text, chunk_index.

        Args:
            sectioned_text: Plain text with section headers (==== SECTION NAME ====).
            opportunity_id: Opportunity ID for log correlation.

        Returns:
            List of chunk dicts with keys: section, part, text, chunk_index.
        """
        logger.bind(opportunity_id=opportunity_id).info(
            "Slack messages chunker: splitting into sections"
        )
        sections = self._split_into_sections(sectioned_text)
        if not sections:
            logger.bind(opportunity_id=opportunity_id).warning(
                "Slack messages chunker: no sections found"
            )
            return []

        all_chunks: list[dict] = []
        chunk_index = 0
        for section_name, content in sections.items():
            for c in self._split_large_section(section_name, content):
                c["chunk_index"] = chunk_index
                all_chunks.append(c)
                chunk_index += 1

        logger.bind(opportunity_id=opportunity_id).info(
            "Slack messages chunker: produced chunks — chunk_count=%s",
            len(all_chunks),
        )
        return all_chunks
