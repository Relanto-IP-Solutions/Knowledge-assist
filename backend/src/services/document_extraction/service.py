"""Document extraction service: orchestrates VisionExtractor and NativeExtractor."""

from __future__ import annotations

from configs.settings import get_settings
from src.services.document_extraction.extractors.native import NativeExtractor
from src.services.document_extraction.extractors.vision import (
    VISION_MIME,
    VisionExtractor,
)
from src.utils.logger import get_logger


logger = get_logger(__name__)

# Extensions that require vision extraction (PDF, images)
VISION_EXTENSIONS = frozenset({".pdf", ".jpg", ".jpeg", ".png", ".gif", ".webp"})

# Extensions that use native extraction (DOCX, MD, PPTX, XLSX)
NATIVE_EXTENSIONS = frozenset({".docx", ".md", ".markdown", ".pptx", ".xlsx"})


class DocumentExtractionService:
    """Orchestrates document extraction: routes by file type to VisionExtractor or NativeExtractor."""

    def __init__(
        self,
        vision_extractor: VisionExtractor | None = None,
        native_extractor: NativeExtractor | None = None,
    ) -> None:
        settings = get_settings()
        self._vision = vision_extractor or VisionExtractor(
            batch_size=settings.ingestion.gemini_extraction_batch_size,
            max_workers=settings.ingestion.gemini_extraction_max_workers,
        )
        self._native = native_extractor or NativeExtractor()

    def extract(self, content: bytes, object_name: str) -> str:
        """Extract text from document bytes based on file extension.

        Args:
            content: Raw file bytes.
            object_name: Object name for extension detection (e.g. report.pdf).

        Returns:
            Extracted text as a string.

        Raises:
            ValueError: If file type is not supported.
        """
        ext = (object_name or "").lower()
        if "." in ext:
            # Get extension (handle multi-part like .tar.gz)
            ext = "." + ext.rsplit(".", 1)[-1]

        if ext in VISION_EXTENSIONS:
            mime_type = VISION_MIME.get(ext, "application/pdf")
            return self._vision.extract(content, mime_type, object_name)

        if ext in NATIVE_EXTENSIONS:
            return self._native.extract(content, object_name)

        raise ValueError(
            f"Unsupported file type for extraction: {object_name}. "
            f"Supported: {', '.join(sorted(VISION_EXTENSIONS | NATIVE_EXTENSIONS))}"
        )
