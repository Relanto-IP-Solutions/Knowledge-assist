"""Gmail thread formatter for processed output.

Formats a cleaned thread into readable text suitable for:
    1. Human review in the processed GCS tier
    2. Chunking for RAG ingestion

Output format (compact):
    - Thread header: subject, participants, message count, date range
    - Each message: [timestamp] sender name, followed by body
    - 50-char separators for visual clarity without verbosity
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from src.services.preprocessing.mail.models import CleanedMessage, CleanedThread


# Width of separator lines (compact format)
_SEPARATOR_WIDTH = 50


def _format_date_range(first: datetime, last: datetime) -> str:
    """Format a date range for display."""
    if first.date() == last.date():
        return first.strftime("%b %d, %Y")
    elif first.year == last.year and first.month == last.month:
        return f"{first.strftime('%b %d')}-{last.strftime('%d, %Y')}"
    elif first.year == last.year:
        return f"{first.strftime('%b %d')} - {last.strftime('%b %d, %Y')}"
    else:
        return f"{first.strftime('%b %d, %Y')} - {last.strftime('%b %d, %Y')}"


def _format_timestamp(dt: datetime) -> str:
    """Format a timestamp for message headers."""
    return dt.strftime("%b %d, %H:%M")


def _format_participants(participants: list) -> str:
    """Format participant list for thread header."""
    parts = []
    for p in participants:
        if p.name:
            parts.append(f"{p.name} ({p.domain})")
        else:
            parts.append(p.email)
    return ", ".join(parts)


class GmailFormatter:
    """Formats cleaned Gmail threads into readable text."""

    def __init__(self, separator_width: int = _SEPARATOR_WIDTH) -> None:
        self.separator_width = separator_width

    def format_thread_header(self, thread: CleanedThread) -> str:
        """Format the thread header section."""
        participants_str = _format_participants(thread.participants)
        date_range_str = _format_date_range(
            thread.date_range.first, thread.date_range.last
        )

        lines = [
            "=" * self.separator_width,
            f"THREAD: {thread.subject}",
            f"Participants: {participants_str}",
            f"Messages: {thread.content_message_count} | {date_range_str}",
            "=" * self.separator_width,
        ]
        return "\n".join(lines)

    def format_message(
        self,
        message: CleanedMessage,
        index: int,
        total: int,
    ) -> str:
        """Format a single message with header and body.

        Args:
            message: The cleaned message to format.
            index: 1-based index of this message in the thread.
            total: Total number of messages in the thread.

        Returns:
            Formatted message text.
        """
        if message.is_empty_after_cleaning:
            return ""

        sender_name = message.sender.name or message.sender.email.split("@")[0]

        lines = [
            "",
            f"[{_format_timestamp(message.timestamp)}] {sender_name}",
            message.body_deduplicated,
        ]
        return "\n".join(lines)

    def format_thread(self, thread: CleanedThread) -> str:
        """Format a complete thread as readable text.

        Args:
            thread: The cleaned thread to format.

        Returns:
            Complete formatted thread text suitable for the processed tier.
        """
        parts = [self.format_thread_header(thread)]

        # Only include messages with content
        content_messages = [m for m in thread.messages if not m.is_empty_after_cleaning]
        total = len(content_messages)

        for i, message in enumerate(content_messages, start=1):
            formatted = self.format_message(message, i, total)
            if formatted:
                parts.append(formatted)

        return "\n".join(parts)

    def format_context_header(
        self,
        thread: CleanedThread,
        message_range: tuple[int, int] | None = None,
    ) -> str:
        """Format a context header for RAG chunks.

        This header is prepended to every chunk so each embedding
        has sufficient context to stand alone.

        Args:
            thread: The thread being chunked.
            message_range: Optional (start, end) 1-based indices of messages
                          in this chunk. If None, represents the whole thread.

        Returns:
            Context header text.
        """
        participants_str = _format_participants(thread.participants)
        date_range_str = _format_date_range(
            thread.date_range.first, thread.date_range.last
        )

        lines = [
            "=" * self.separator_width,
            f"THREAD: {thread.subject}",
            f"Participants: {participants_str}",
            f"Messages: {thread.content_message_count} | {date_range_str}",
        ]

        if message_range:
            start, end = message_range
            lines.append(f"[Chunk: {start}-{end} of {thread.content_message_count}]")

        lines.append("=" * self.separator_width)
        return "\n".join(lines)
