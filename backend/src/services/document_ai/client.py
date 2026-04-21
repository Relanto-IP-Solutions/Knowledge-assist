"""Document AI client: process PDF bytes and return extracted text (imageless mode, 30-page sync limit)."""

from pathlib import Path

import google.auth
from google.api_core.client_options import ClientOptions
from google.cloud import documentai_v1 as documentai
from google.oauth2 import service_account

from configs.settings import get_settings
from src.utils.logger import get_logger


class DocumentTooLargeError(Exception):
    """Raised when a document exceeds sync API limits (size or page count)."""


logger = get_logger(__name__)

# Sync API limits: 40 MB; with imageless mode, 30 pages per request
MAX_CONTENT_BYTES = 40 * 1024 * 1024
PDF_MIME = "application/pdf"


def _load_credentials(path: str):
    """Load service account credentials from a JSON key file."""
    path_resolved = Path(path).expanduser().resolve()
    return service_account.Credentials.from_service_account_file(str(path_resolved))


class DocumentAiClient:
    """Client for Google Document AI. Used for PDF extraction only (imageless mode)."""

    def __init__(
        self, processor_name: str | None = None, credentials_path: str | None = None
    ) -> None:
        settings = get_settings().ingestion
        self._processor_name = (
            processor_name or settings.document_ai_processor_name
        ).strip()
        if not self._processor_name:
            raise ValueError("Document AI processor name is not set")

        cred_path = (
            credentials_path
            or settings.document_ai_credentials_path.strip()
            or settings.google_application_credentials.strip()
        )
        if cred_path:
            credentials = _load_credentials(cred_path)
        else:
            credentials, _ = google.auth.default()

        # Endpoint from processor name: projects/PROJECT/locations/LOCATION/processors/ID
        location = "us"
        if "/locations/" in self._processor_name:
            parts = self._processor_name.split("/")
            for i, p in enumerate(parts):
                if p == "locations" and i + 1 < len(parts):
                    location = parts[i + 1]
                    break
        endpoint = f"{location}-documentai.googleapis.com"
        opts = ClientOptions(api_endpoint=endpoint)
        self._client = documentai.DocumentProcessorServiceClient(
            client_options=opts,
            credentials=credentials,
        )

    def process(self, data: bytes, mime_type: str) -> str:
        """Process document bytes and return extracted text. Intended for PDF only.

        - Enforces 40 MB max; raises DocumentTooLargeError if over.
        - Uses imageless (native PDF) mode for 30-page sync limit.
        - For non-PDF mime_type, returns empty string (no-op).
        """
        if mime_type != PDF_MIME:
            logger.debug("Document AI process called with non-PDF mime_type, skipping")
            return ""

        if len(data) > MAX_CONTENT_BYTES:
            raise DocumentTooLargeError(
                f"Document size {len(data)} bytes exceeds max {MAX_CONTENT_BYTES} (40 MB)"
            )

        raw_document = documentai.RawDocument(content=data, mime_type=mime_type)
        # Imageless (native PDF) mode: 30-page sync limit instead of 15.
        process_options = documentai.ProcessOptions(
            ocr_config=documentai.OcrConfig(enable_native_pdf_parsing=True),
        )
        request = documentai.ProcessRequest(
            name=self._processor_name,
            raw_document=raw_document,
            process_options=process_options,
            imageless_mode=True,
        )
        logger.debug(
            "Document AI process_document with imageless_mode=True, 30-page sync limit",
            extra={"bytes": len(data)},
        )

        try:
            result = self._client.process_document(request=request)
        except Exception as e:
            msg = str(e).lower()
            # Only treat as size/page limit when the error clearly indicates it (avoid masking other API errors).
            limit_phrases = (
                "page limit",
                "page count",
                "resource exhausted",
                "limit exceeded",
                "too many pages",
                "maximum 15",
            )
            if any(phrase in msg for phrase in limit_phrases):
                raise DocumentTooLargeError(
                    "Document exceeds sync limit (e.g. over 30 pages); use batch for large PDFs"
                ) from e
            logger.exception("Document AI process_document failed")
            raise

        document = result.document
        if document is None:
            return ""
        return document.text or ""
