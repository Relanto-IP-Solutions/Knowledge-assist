"""Gmail sliding-window chunking for RAG ingestion.

Takes formatted Gmail thread text and produces overlapping chunks using
a sliding window over messages. Each chunk includes a rich context header
so embeddings are self-contained.

Used by IngestionPipeline for source_type=gmail_messages.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from src.utils.logger import get_logger


if TYPE_CHECKING:
    from src.services.preprocessing.mail.formatter import GmailFormatter
    from src.services.preprocessing.mail.models import CleanedThread

logger = get_logger(__name__)

# Default configuration
DEFAULT_WINDOW_SIZE = 3  # Messages per chunk
DEFAULT_WINDOW_OVERLAP = 1  # Messages shared between adjacent chunks
DEFAULT_MAX_CHARS_PER_CHUNK = 4000  # Stay within embedding model limits

# Pattern to identify message headers in formatted text
# Matches: [timestamp] Name <email> OR [timestamp] Name (without email)
MESSAGE_HEADER_PATTERN = re.compile(
    r"^\[([^\]]+)\]\s+([^\n<]+?)(?:\s*<([^>]+)>)?$",
    re.MULTILINE,
)

# Pattern for thread header separator
THREAD_HEADER_SEPARATOR = "=" * 80


class GmailMessagesChunker:
    """Sliding-window chunker for Gmail threads.

    Produces overlapping chunks where each chunk contains multiple messages
    with a rich context header. This ensures:
    - Each chunk has enough context to stand alone
    - Overlap prevents information loss at boundaries
    - Retrieval returns coherent conversation segments
    """

    def __init__(
        self,
        window_size: int = DEFAULT_WINDOW_SIZE,
        window_overlap: int = DEFAULT_WINDOW_OVERLAP,
        max_chars_per_chunk: int = DEFAULT_MAX_CHARS_PER_CHUNK,
    ) -> None:
        """Initialize the chunker.

        Args:
            window_size: Number of messages per chunk (default 3).
            window_overlap: Messages shared between adjacent chunks (default 1).
            max_chars_per_chunk: Maximum characters per chunk (default 4000).
        """
        self.window_size = window_size
        self.window_overlap = window_overlap
        self.max_chars_per_chunk = max_chars_per_chunk

    def _extract_thread_header(self, formatted_text: str) -> str:
        """Extract the thread header from formatted text."""
        lines = formatted_text.split("\n")
        header_lines = []
        in_header = False

        for line in lines:
            if line.startswith("=" * 10):
                if in_header:
                    header_lines.append(line)
                    break
                in_header = True
                header_lines.append(line)
            elif in_header:
                header_lines.append(line)

        return "\n".join(header_lines) if header_lines else ""

    def _split_into_messages(self, formatted_text: str) -> list[dict]:
        """Split formatted text into individual messages.

        Returns:
            List of dicts with 'header', 'body', and 'full_text' for each message.
        """
        # Find all message header positions
        matches = list(MESSAGE_HEADER_PATTERN.finditer(formatted_text))
        if not matches:
            return []

        messages = []
        for i, match in enumerate(matches):
            start = match.start()
            # Find the end of this message (start of next message or end of text)
            if i + 1 < len(matches):
                end = matches[i + 1].start()
            else:
                end = len(formatted_text)

            message_text = formatted_text[start:end].strip()

            # Split into header and body
            lines = message_text.split("\n")
            header_end = 0
            for j, line in enumerate(lines):
                if line.startswith("─" * 10):
                    header_end = j + 1
                    break

            header = "\n".join(lines[:header_end])
            body = "\n".join(lines[header_end:]).strip()

            messages.append({
                "header": header,
                "body": body,
                "full_text": message_text,
                "timestamp": match.group(1),
                "sender_name": match.group(2).strip(),
                "sender_email": match.group(3) or "",  # May be None if no <email>
            })

        return messages

    def _build_context_header(
        self,
        thread_header: str,
        message_range: tuple[int, int],
        total_messages: int,
    ) -> str:
        """Build a context header for a chunk.

        Args:
            thread_header: The original thread header.
            message_range: (start, end) 1-based indices of messages in this chunk.
            total_messages: Total number of messages in the thread.

        Returns:
            Context header with chunk position indicator.
        """
        start, end = message_range

        # Parse and modify the thread header to add chunk position
        lines = thread_header.split("\n")
        result_lines = []
        for line in lines:
            result_lines.append(line)
            # Add chunk position after the last header line before the separator
            if line.startswith("Messages:"):
                result_lines.append(
                    f"[This chunk: messages {start}-{end} of {total_messages}]"
                )

        return "\n".join(result_lines)

    def _format_chunk_content(
        self,
        messages: list[dict],
        start_idx: int,
    ) -> str:
        """Format the content portion of a chunk (messages without thread header)."""
        lines = []
        for msg in messages:
            lines.append("")  # Blank line before each message
            lines.append(msg["full_text"])
        return "\n".join(lines)

    def chunk(
        self,
        formatted_text: str,
        opportunity_id: str = "",
        thread_id: str = "",
    ) -> list[dict]:
        """Chunk formatted Gmail thread text using sliding window.

        Args:
            formatted_text: Formatted thread text from GmailFormatter.
            opportunity_id: Opportunity ID for log correlation.
            thread_id: Thread ID for metadata.

        Returns:
            List of chunk dicts with keys:
                - text: Full chunk text (context header + messages)
                - thread_id: Gmail thread ID
                - message_range: "start-end" string
                - chunk_index: 0-based index
                - message_count: Number of messages in this chunk
        """
        extras = {"opportunity_id": opportunity_id}
        logger.bind(**extras).info("Gmail chunker: starting sliding window chunking")

        # Extract components
        thread_header = self._extract_thread_header(formatted_text)
        messages = self._split_into_messages(formatted_text)

        if not messages:
            logger.bind(**extras).warning("Gmail chunker: no messages found")
            return []

        total_messages = len(messages)
        chunks: list[dict] = []
        chunk_index = 0

        # Sliding window
        step = self.window_size - self.window_overlap
        if step <= 0:
            step = 1

        i = 0
        while i < total_messages:
            # Get window of messages
            window_end = min(i + self.window_size, total_messages)
            window_messages = messages[i:window_end]

            # Build chunk
            start_idx = i + 1  # 1-based
            end_idx = window_end  # 1-based (inclusive)

            context_header = self._build_context_header(
                thread_header, (start_idx, end_idx), total_messages
            )
            content = self._format_chunk_content(window_messages, i)
            full_text = f"{context_header}\n{content}"

            # Check if chunk exceeds max size
            if len(full_text) > self.max_chars_per_chunk:
                # Split this window further by paragraphs
                sub_chunks = self._split_large_chunk(
                    context_header, window_messages, start_idx, total_messages
                )
                for sub in sub_chunks:
                    sub["chunk_index"] = chunk_index
                    sub["thread_id"] = thread_id
                    chunks.append(sub)
                    chunk_index += 1
            else:
                chunks.append({
                    "text": full_text,
                    "thread_id": thread_id,
                    "message_range": f"{start_idx}-{end_idx}",
                    "chunk_index": chunk_index,
                    "message_count": len(window_messages),
                })
                chunk_index += 1

            # Move window
            i += step

            # Ensure we don't miss the last messages if window doesn't align
            if i >= total_messages and window_end < total_messages:
                i = total_messages - self.window_size
                if i < 0:
                    break

        logger.bind(**extras).info(
            "Gmail chunker: produced %d chunks from %d messages",
            len(chunks),
            total_messages,
        )
        return chunks

    def _split_large_chunk(
        self,
        context_header: str,
        messages: list[dict],
        start_idx: int,
        total_messages: int,
    ) -> list[dict]:
        """Split a large chunk into smaller parts while preserving context.

        When a window of messages exceeds max_chars_per_chunk, split
        at message boundaries or paragraph boundaries within messages.
        """
        chunks = []
        current_text = context_header
        current_messages: list[dict] = []
        part = 1

        for msg in messages:
            msg_text = f"\n\n{msg['full_text']}"
            potential_text = current_text + msg_text

            if len(potential_text) <= self.max_chars_per_chunk:
                current_text = potential_text
                current_messages.append(msg)
            else:
                # Save current chunk if not empty
                if current_messages:
                    end_idx = start_idx + len(current_messages) - 1
                    chunks.append({
                        "text": current_text,
                        "message_range": f"{start_idx}-{end_idx}",
                        "message_count": len(current_messages),
                    })
                    part += 1

                # Start new chunk with this message
                start_idx = start_idx + len(current_messages)
                current_text = context_header + msg_text
                current_messages = [msg]

                # If single message is still too large, truncate
                if len(current_text) > self.max_chars_per_chunk:
                    truncated = (
                        current_text[: self.max_chars_per_chunk - 50]
                        + "\n\n[truncated]"
                    )
                    chunks.append({
                        "text": truncated,
                        "message_range": f"{start_idx}",
                        "message_count": 1,
                    })
                    current_text = context_header
                    current_messages = []
                    start_idx += 1

        # Add remaining
        if current_messages:
            end_idx = start_idx + len(current_messages) - 1
            chunks.append({
                "text": current_text,
                "message_range": f"{start_idx}-{end_idx}",
                "message_count": len(current_messages),
            })

        return chunks

    def chunk_from_cleaned_thread(
        self,
        thread: CleanedThread,
        formatter: GmailFormatter,
    ) -> list[dict]:
        """Chunk directly from a CleanedThread object.

        This method allows chunking without going through the text formatting
        step, which can be more efficient for the ingestion pipeline.

        Args:
            thread: Cleaned thread from preprocessing.
            formatter: GmailFormatter instance for context headers.

        Returns:
            List of chunk dicts.
        """
        formatted_text = formatter.format_thread(thread)
        return self.chunk(
            formatted_text,
            opportunity_id=thread.opportunity_id,
            thread_id=thread.thread_id,
        )
