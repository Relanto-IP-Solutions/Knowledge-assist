"""Document AI service: extract text from PDFs via Google Document AI (imageless mode)."""

from src.services.document_ai.client import DocumentAiClient, DocumentTooLargeError


__all__ = ["DocumentAiClient", "DocumentTooLargeError"]
