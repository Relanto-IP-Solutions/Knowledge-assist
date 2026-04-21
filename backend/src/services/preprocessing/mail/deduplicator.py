"""Thread deduplication for email preprocessing.

Email replies typically include quoted copies of earlier messages. This module
detects and removes content that appeared in previous messages within the same
thread to avoid embedding duplicate information.

Deduplication strategy:
    1. Sort messages chronologically (oldest first)
    2. Build a set of "seen" line hashes as we process each message
    3. For each message, keep only lines that haven't been seen before
    4. Preserve blank lines for paragraph structure

This approach ensures the earliest occurrence of each line is kept, and
later quoted copies are removed.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from src.services.preprocessing.mail.models import GmailMessage


# Minimum line length to consider for deduplication
# Very short lines (< 10 chars) are often common phrases that legitimately repeat
_MIN_DEDUP_LINE_LENGTH = 10

# Patterns for lines that should never be deduplicated (greetings, closings)
_PRESERVE_PATTERNS = [
    re.compile(
        r"^\s*(hi|hello|hey|dear|good\s+(morning|afternoon|evening))", re.IGNORECASE
    ),
    re.compile(r"^\s*(thanks|thank\s+you|best|regards|cheers)", re.IGNORECASE),
]


def _normalize_for_comparison(line: str) -> str:
    """Normalize a line for duplicate comparison.

    Strips whitespace, converts to lowercase, and removes common punctuation
    variations so that "Hello!" matches "Hello" matches "hello".
    """
    normalized = line.strip().lower()
    normalized = re.sub(r"[^\w\s]", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def _should_preserve(line: str) -> bool:
    """Check if a line should be preserved regardless of duplication.

    Some common phrases (greetings, closings) naturally repeat across emails
    and should not be deduplicated.
    """
    stripped = line.strip()
    if len(stripped) < _MIN_DEDUP_LINE_LENGTH:
        return True
    return any(pattern.match(stripped) for pattern in _PRESERVE_PATTERNS)


class ThreadDeduplicator:
    """Deduplicate content across messages in an email thread.

    Processes messages chronologically and removes lines that appeared
    in earlier messages. This prevents the same content from being
    embedded multiple times when replies quote previous messages.
    """

    def __init__(self) -> None:
        self._seen_lines: set[str] = set()

    def reset(self) -> None:
        """Clear the seen lines set for a new thread."""
        self._seen_lines.clear()

    def deduplicate_body(self, body: str) -> str:
        """Remove lines that have been seen in earlier messages.

        Args:
            body: Cleaned message body text.

        Returns:
            Body with duplicate lines removed. The seen set is updated
            with new lines for subsequent calls.
        """
        if not body:
            return ""

        new_lines: list[str] = []

        for line in body.splitlines():
            stripped = line.strip()

            # Always preserve blank lines for paragraph structure
            if not stripped:
                new_lines.append("")
                continue

            # Always preserve short lines and common phrases
            if _should_preserve(line):
                new_lines.append(line)
                continue

            # Check if we've seen this line before
            normalized = _normalize_for_comparison(line)
            if normalized and normalized not in self._seen_lines:
                new_lines.append(line)
                self._seen_lines.add(normalized)
            # If seen, skip the line (don't add to new_lines)

        # Clean up result: remove leading/trailing blank lines,
        # collapse multiple consecutive blank lines
        result_lines: list[str] = []
        prev_blank = True  # Start true to skip leading blanks
        for line in new_lines:
            is_blank = not line.strip()
            if is_blank:
                if not prev_blank:
                    result_lines.append("")
            else:
                result_lines.append(line)
            prev_blank = is_blank

        # Remove trailing blank
        while result_lines and not result_lines[-1].strip():
            result_lines.pop()

        return "\n".join(result_lines)


def deduplicate_thread_messages(
    messages: list[GmailMessage],
    cleaned_bodies: dict[str, str],
) -> dict[str, str]:
    """Deduplicate cleaned bodies across all messages in a thread.

    Args:
        messages: List of GmailMessage objects (used for ordering by timestamp).
        cleaned_bodies: Mapping of message_id -> cleaned body text.

    Returns:
        Mapping of message_id -> deduplicated body text.
    """
    deduplicator = ThreadDeduplicator()
    deduplicated: dict[str, str] = {}

    # Process in chronological order
    sorted_messages = sorted(messages, key=lambda m: m.timestamp)

    for msg in sorted_messages:
        cleaned = cleaned_bodies.get(msg.id, "")
        deduplicated[msg.id] = deduplicator.deduplicate_body(cleaned)

    return deduplicated
