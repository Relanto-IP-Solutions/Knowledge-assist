"""Vision-based extraction for PDF and images via Gemini (LLMClient)."""

from __future__ import annotations

import io
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from pypdf import PdfReader, PdfWriter

from src.services.llm.client import LLMClient
from src.utils.logger import get_logger


# Suppress pypdf FloatObject warnings for malformed PDFs (e.g. 0.000000-10374927)
logging.getLogger("pypdf.generic._base").setLevel(logging.ERROR)

logger = get_logger(__name__)

# MIME types for supported vision formats
VISION_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
}

DEFAULT_PROMPT = """\
You are an expert at reading handwritten notes and documents.

Transcribe all text from these pages into clean Markdown format:
- Use # ## ### for headings and section titles
- Preserve bullet points, numbered lists, and tables
- Do NOT add summaries, explanations, or commentary
- Do NOT wrap in JSON or code blocks
- Output ONLY the transcribed content, nothing else
"""

BATCH_PROMPT_SUFFIX = (
    "\n\nNote: This is a batch of pages from a larger document. "
    "Transcribe only the content visible in these pages."
)


def _clean_markdown(text: str) -> str:
    """Strip excessive whitespace padding Gemini adds when reproducing visual layouts."""
    text = re.sub(r" {4,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _get_pdf_page_count(content: bytes) -> int:
    """Return the number of pages in a PDF."""
    return len(PdfReader(io.BytesIO(content)).pages)


def _extract_pdf_pages(content: bytes, start: int, end: int) -> bytes:
    """Return bytes for pages [start, end) (0-indexed) of the given PDF."""
    reader = PdfReader(io.BytesIO(content))
    writer = PdfWriter()
    for i in range(start, min(end, len(reader.pages))):
        writer.add_page(reader.pages[i])
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


class VisionExtractor:
    """Extract text from PDF and images via Gemini Vision (LLMClient)."""

    def __init__(
        self,
        llm: LLMClient | None = None,
        batch_size: int = 15,
        max_workers: int = 10,
    ) -> None:
        self._llm = llm or LLMClient()
        self._batch_size = batch_size
        self._max_workers = max_workers

    def extract(self, content: bytes, mime_type: str, object_name: str) -> str:
        """Extract text from PDF or image bytes via Gemini Vision.

        - Images: single API call.
        - PDFs: split into page batches, parallel calls, collate in order.

        Args:
            content: Raw file bytes.
            mime_type: MIME type (e.g. application/pdf, image/jpeg).
            object_name: Object name for logging.

        Returns:
            Extracted/transcribed text.
        """
        if mime_type != "application/pdf" or self._batch_size <= 0:
            text = self._llm.generate_content_from_media(
                content, mime_type, DEFAULT_PROMPT
            )
            return _clean_markdown(text)

        total_pages = _get_pdf_page_count(content)
        total_batches = (total_pages + self._batch_size - 1) // self._batch_size

        logger.info(
            "VisionExtractor: %s pages → %s batches of %s",
            total_pages,
            total_batches,
            self._batch_size,
            extra={"object_name": object_name},
        )

        batch_prompt = DEFAULT_PROMPT + BATCH_PROMPT_SUFFIX
        effective_workers = max(1, min(self._max_workers, total_batches))

        batches: list[tuple[int, int, int]] = []
        for batch_num, start in enumerate(
            range(0, total_pages, self._batch_size), start=1
        ):
            end = min(start + self._batch_size, total_pages)
            batches.append((batch_num, start, end))

        def _run_one(batch_num: int, start: int, end: int) -> tuple[int, str]:
            chunk_bytes = _extract_pdf_pages(content, start, end)
            try:
                text = self._llm.generate_content_from_media(
                    chunk_bytes, mime_type, batch_prompt
                )
                logger.debug(
                    "VisionExtractor batch %s/%s done",
                    batch_num,
                    total_batches,
                    extra={"object_name": object_name},
                )
                return batch_num, text
            except Exception as exc:
                logger.warning(
                    "VisionExtractor batch %s failed: %s",
                    batch_num,
                    exc,
                    extra={"object_name": object_name},
                )
                return (
                    batch_num,
                    f"\n\n<!-- Pages {start + 1}–{end} FAILED: {exc} -->\n\n",
                )

        results_by_batch: dict[int, str] = {}
        with ThreadPoolExecutor(max_workers=effective_workers) as executor:
            future_map = {
                executor.submit(_run_one, batch_num, start, end): batch_num
                for (batch_num, start, end) in batches
            }
            for fut in as_completed(future_map):
                batch_num, text = fut.result()
                results_by_batch[batch_num] = text

        parts = [results_by_batch[i] for i in range(1, total_batches + 1)]
        combined = "\n\n".join(parts)
        return _clean_markdown(combined)
