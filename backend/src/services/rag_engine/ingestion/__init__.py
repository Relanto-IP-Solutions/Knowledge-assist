"""RAG ingestion: chunking and extraction for documents, Slack, Zoom, Gmail, and pre-xlsx text.

Per-source chunkers used by IngestionPipeline:
- DocumentsChunker: extract text from PDF/DOCX/PPTX/TXT and character-based chunking;
  delegates ``_pre_xlsx_*`` blobs to PreXlsxDocumentsChunker
- PreXlsxDocumentsChunker: table-aware chunking for preprocessed spreadsheet .txt
- SlackMessagesChunker: section-based chunking of Slack summary text
- ZoomTranscriptsChunker: parse tab-format transcript and time-window chunking
- GmailMessagesChunker: sliding-window chunking of Gmail threads
"""

from src.services.rag_engine.ingestion.documents import DocumentsChunker
from src.services.rag_engine.ingestion.gmail_messages import GmailMessagesChunker
from src.services.rag_engine.ingestion.pre_xlsx_documents import (
    PRE_XLSX_MAX_CHARS_PER_CHUNK,
    PreXlsxDocumentsChunker,
)
from src.services.rag_engine.ingestion.slack_messages import SlackMessagesChunker
from src.services.rag_engine.ingestion.zoom_transcripts import ZoomTranscriptsChunker


__all__ = [
    "PRE_XLSX_MAX_CHARS_PER_CHUNK",
    "DocumentsChunker",
    "GmailMessagesChunker",
    "PreXlsxDocumentsChunker",
    "SlackMessagesChunker",
    "ZoomTranscriptsChunker",
]
