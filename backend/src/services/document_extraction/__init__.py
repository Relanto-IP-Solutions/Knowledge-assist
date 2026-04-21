"""Document extraction service: Gemini-based OCR for PDF/images, native for DOCX/MD/PPTX."""

from src.services.document_extraction.extractors import NativeExtractor, VisionExtractor
from src.services.document_extraction.service import DocumentExtractionService


__all__ = [
    "DocumentExtractionService",
    "NativeExtractor",
    "VisionExtractor",
]
