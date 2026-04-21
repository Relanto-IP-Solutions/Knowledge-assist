"""Gmail preprocessing orchestrator.

This module is the main entry point for processing raw Gmail thread JSON files.
It coordinates:
    1. Parsing and validating raw thread JSON
    2. Text cleaning (signatures, disclaimers, etc.)
    3. Thread deduplication (removing quoted content)
    4. Formatting for the processed tier

Usage:
    from src.services.preprocessing.mail import GmailPreprocessor

    preprocessor = GmailPreprocessor()
    cleaned_thread = preprocessor.preprocess(raw_bytes)
    formatted_text = preprocessor.format(cleaned_thread)
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from src.services.preprocessing.mail.cleaner import ThreadCleaner, clean_subject
from src.services.preprocessing.mail.deduplicator import deduplicate_thread_messages
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
from src.utils.logger import get_logger


logger = get_logger(__name__)


class GmailPreprocessor:
    """Orchestrates Gmail thread preprocessing.

    Transforms raw thread JSON from the connector into cleaned, deduplicated
    text ready for formatting and RAG ingestion.
    """

    def __init__(self) -> None:
        self._cleaner = ThreadCleaner()
        self._formatter = GmailFormatter()

    def parse_thread_json(self, raw_bytes: bytes) -> GmailThread:
        """Parse and validate raw thread JSON.

        Args:
            raw_bytes: Raw JSON bytes from GCS.

        Returns:
            Validated GmailThread model.

        Raises:
            ValueError: If JSON is invalid or doesn't match schema.
        """
        try:
            data = json.loads(raw_bytes.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ValueError(f"Invalid JSON: {e}") from e

        # Parse with Pydantic validation
        try:
            return GmailThread.model_validate(data)
        except Exception as e:
            raise ValueError(f"Invalid thread schema: {e}") from e

    def preprocess(self, raw_bytes: bytes) -> CleanedThread:
        """Process raw thread JSON into a cleaned thread.

        This is the main entry point that coordinates:
        1. JSON parsing and validation
        2. Text cleaning for each message
        3. Thread-level deduplication
        4. Building the CleanedThread model

        Args:
            raw_bytes: Raw JSON bytes from GCS.

        Returns:
            CleanedThread ready for formatting.
        """
        thread = self.parse_thread_json(raw_bytes)

        # Step 1: Clean each message body
        cleaned_bodies: dict[str, str] = {}
        for msg in thread.messages:
            cleaned = self._cleaner.clean_body(msg.body_text)
            cleaned_bodies[msg.id] = cleaned or ""

        # Step 2: Deduplicate across the thread
        deduplicated_bodies = deduplicate_thread_messages(
            thread.messages, cleaned_bodies
        )

        # Step 3: Build cleaned messages
        cleaned_messages: list[CleanedMessage] = []
        for msg in thread.messages:
            cleaned_body = cleaned_bodies.get(msg.id, "")
            deduped_body = deduplicated_bodies.get(msg.id, "")

            cleaned_msg = CleanedMessage(
                id=msg.id,
                timestamp=msg.timestamp,
                sender=msg.sender,
                to=msg.to,
                cc=msg.cc,
                body_cleaned=cleaned_body,
                body_deduplicated=deduped_body,
                is_empty_after_cleaning=not deduped_body.strip(),
            )
            cleaned_messages.append(cleaned_msg)

        # Count messages with actual content
        content_count = sum(
            1 for m in cleaned_messages if not m.is_empty_after_cleaning
        )

        # Build cleaned thread
        cleaned_thread = CleanedThread(
            thread_id=thread.thread_id,
            subject=clean_subject(thread.subject) or "(no subject)",
            participants=thread.participants,
            message_count=len(thread.messages),
            content_message_count=content_count,
            date_range=thread.date_range,
            messages=cleaned_messages,
            opportunity_id=thread.metadata.opportunity_id,
        )

        logger.debug(
            "Preprocessed thread: %s (%d/%d messages with content)",
            thread.thread_id,
            content_count,
            len(thread.messages),
        )

        return cleaned_thread

    def format(self, thread: CleanedThread) -> str:
        """Format a cleaned thread as readable text.

        Args:
            thread: Cleaned thread from preprocess().

        Returns:
            Formatted text for the processed tier.
        """
        return self._formatter.format_thread(thread)

    def preprocess_and_format(self, raw_bytes: bytes) -> tuple[CleanedThread, str]:
        """Convenience method to preprocess and format in one call.

        Args:
            raw_bytes: Raw JSON bytes from GCS.

        Returns:
            Tuple of (CleanedThread, formatted_text).
        """
        cleaned = self.preprocess(raw_bytes)
        formatted = self.format(cleaned)
        return cleaned, formatted


def build_thread_from_messages(
    messages_data: list[dict[str, Any]],
    thread_id: str,
    opportunity_id: str,
) -> GmailThread:
    """Build a GmailThread from a list of message dictionaries.

    This is a helper for building thread JSON from individual messages,
    useful when migrating from message-level to thread-level storage.

    Args:
        messages_data: List of message dicts with keys matching GmailMessage.
        thread_id: The Gmail thread ID.
        opportunity_id: Associated opportunity ID.

    Returns:
        Assembled GmailThread ready for processing.
    """
    # Parse messages
    messages = [GmailMessage.model_validate(m) for m in messages_data]

    # Sort by timestamp
    messages.sort(key=lambda m: m.timestamp)

    # Extract unique participants
    participants_seen: set[str] = set()
    participants: list[Participant] = []
    for msg in messages:
        if msg.sender.email not in participants_seen:
            participants.append(msg.sender)
            participants_seen.add(msg.sender.email)
        for recipient in msg.to + msg.cc:
            if recipient.email not in participants_seen:
                participants.append(recipient)
                participants_seen.add(recipient.email)

    # Get subject from first message
    subject = messages[0].body_text if messages else "(no subject)"
    for msg in messages:
        # Try to find a clean subject (sometimes first message has empty subject)
        if hasattr(msg, "subject") and msg.subject:
            subject = msg.subject
            break

    # For now, use snippet or first line as subject if not available
    # The actual subject should come from the connector
    subject = subject.split("\n")[0][:100] if subject else "(no subject)"

    return GmailThread(
        thread_id=thread_id,
        subject=subject,
        participants=participants,
        message_count=len(messages),
        date_range=DateRange(
            first=messages[0].timestamp if messages else datetime.now(),
            last=messages[-1].timestamp if messages else datetime.now(),
        ),
        messages=messages,
        metadata=ThreadMetadata(
            opportunity_id=opportunity_id,
            synced_at=datetime.now(),
            labels=[],
        ),
    )
