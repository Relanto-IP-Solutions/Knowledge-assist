"""Gmail/Email preprocessing package.

This package provides preprocessing for Gmail threads, transforming raw
JSON from the Gmail connector into cleaned, deduplicated text ready for
RAG ingestion.

Main components:
    GmailPreprocessor  - Orchestrates the full preprocessing pipeline
    ThreadCleaner      - 8-step text cleaning (signatures, disclaimers, etc.)
    ThreadDeduplicator - Removes quoted content across thread messages
    GmailFormatter     - Formats threads as readable text

Models:
    GmailThread    - Raw thread from connector
    GmailMessage   - Single message within a thread
    CleanedThread  - Thread after cleaning and deduplication
    CleanedMessage - Message after cleaning and deduplication
    Participant    - Email participant with name and domain

Usage:
    from src.services.preprocessing.mail import GmailPreprocessor

    preprocessor = GmailPreprocessor()
    cleaned_thread, formatted_text = preprocessor.preprocess_and_format(raw_bytes)
"""

from src.services.preprocessing.mail.cleaner import (
    ThreadCleaner,
    clean_body,
    clean_subject,
)
from src.services.preprocessing.mail.deduplicator import (
    ThreadDeduplicator,
    deduplicate_thread_messages,
)
from src.services.preprocessing.mail.formatter import GmailFormatter
from src.services.preprocessing.mail.models import (
    CleanedMessage,
    CleanedThread,
    DateRange,
    GmailMessage,
    GmailThread,
    Participant,
    ThreadMetadata,
)
from src.services.preprocessing.mail.preprocessor import (
    GmailPreprocessor,
    build_thread_from_messages,
)


__all__ = [
    "CleanedMessage",
    "CleanedThread",
    "DateRange",
    "GmailFormatter",
    "GmailMessage",
    # Main orchestrator
    "GmailPreprocessor",
    # Models
    "GmailThread",
    "Participant",
    # Components
    "ThreadCleaner",
    "ThreadDeduplicator",
    "ThreadMetadata",
    "build_thread_from_messages",
    # Utility functions
    "clean_body",
    "clean_subject",
    "deduplicate_thread_messages",
]
