"""Pydantic models for Gmail thread preprocessing.

Models:
    Participant     - Email participant with name and domain
    GmailMessage    - Single email message within a thread
    GmailThread     - Complete email thread with all messages and metadata
    CleanedMessage  - Message after text cleaning and deduplication
    CleanedThread   - Thread ready for formatting and chunking
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, computed_field


class Participant(BaseModel):
    """Email participant (sender or recipient)."""

    email: str = Field(description="Email address")
    name: str | None = Field(default=None, description="Display name if available")

    @computed_field
    @property
    def domain(self) -> str:
        """Extract domain from email address."""
        if "@" in self.email:
            return self.email.split("@")[-1].lower()
        return ""


class GmailMessage(BaseModel):
    """Single email message within a thread (raw from connector)."""

    id: str = Field(description="Gmail message ID")
    timestamp: datetime = Field(description="Message sent timestamp (UTC)")
    sender: Participant = Field(alias="from", description="Message sender")
    to: list[Participant] = Field(default_factory=list, description="To recipients")
    cc: list[Participant] = Field(default_factory=list, description="CC recipients")
    in_reply_to: str | None = Field(
        default=None, description="ID of message this replies to"
    )
    body_text: str = Field(description="Plain text body")
    body_html: str | None = Field(default=None, description="HTML body if available")
    snippet: str | None = Field(
        default=None, description="Gmail snippet (preview text)"
    )

    model_config = {"populate_by_name": True}


class DateRange(BaseModel):
    """Date range for a thread."""

    first: datetime = Field(description="Earliest message timestamp")
    last: datetime = Field(description="Latest message timestamp")


class ThreadMetadata(BaseModel):
    """Metadata for a Gmail thread."""

    opportunity_id: str = Field(description="Associated opportunity ID")
    synced_at: datetime = Field(description="When the thread was synced")
    labels: list[str] = Field(default_factory=list, description="Gmail labels")


class GmailThread(BaseModel):
    """Complete email thread with all messages (raw from connector).

    This is the schema for raw/gmail/{thread_id}/thread.json
    """

    thread_id: str = Field(description="Gmail thread ID")
    subject: str = Field(description="Thread subject line")
    participants: list[Participant] = Field(description="All thread participants")
    message_count: int = Field(description="Number of messages in thread")
    date_range: DateRange = Field(description="Time span of the thread")
    messages: list[GmailMessage] = Field(
        description="All messages in chronological order"
    )
    metadata: ThreadMetadata = Field(description="Thread metadata")


class CleanedMessage(BaseModel):
    """Message after text cleaning and deduplication."""

    id: str = Field(description="Original message ID")
    timestamp: datetime = Field(description="Message timestamp")
    sender: Participant = Field(description="Message sender")
    to: list[Participant] = Field(default_factory=list, description="To recipients")
    cc: list[Participant] = Field(default_factory=list, description="CC recipients")
    body_cleaned: str = Field(
        description="Cleaned body text (signatures, disclaimers removed)"
    )
    body_deduplicated: str = Field(
        description="Deduplicated body (quoted content from earlier messages removed)"
    )
    is_empty_after_cleaning: bool = Field(
        default=False, description="True if message has no content after cleaning"
    )

    @computed_field
    @property
    def direction(self) -> str:
        """Determine if message is inbound or outbound based on sender domain.

        Note: Internal domains should be configured via environment/settings.
        Using placeholder domains here for development.
        """
        internal_domains = {
            "acme-corp.com",
            "acme-corp.net",
            "acme.io",
        }
        if self.sender.domain in internal_domains:
            return "outbound"
        return "inbound"


class CleanedThread(BaseModel):
    """Thread after cleaning and deduplication, ready for formatting and chunking."""

    thread_id: str = Field(description="Gmail thread ID")
    subject: str = Field(description="Cleaned subject line")
    participants: list[Participant] = Field(description="All thread participants")
    message_count: int = Field(description="Total messages (including empty ones)")
    content_message_count: int = Field(
        description="Messages with actual content after cleaning"
    )
    date_range: DateRange = Field(description="Time span of the thread")
    messages: list[CleanedMessage] = Field(description="Cleaned messages")
    opportunity_id: str = Field(description="Associated opportunity ID")

    @computed_field
    @property
    def participant_domains(self) -> list[str]:
        """Unique domains of all participants."""
        return list({p.domain for p in self.participants if p.domain})

    @computed_field
    @property
    def has_inbound(self) -> bool:
        """True if thread contains inbound messages."""
        return any(m.direction == "inbound" for m in self.messages)

    @computed_field
    @property
    def has_outbound(self) -> bool:
        """True if thread contains outbound messages."""
        return any(m.direction == "outbound" for m in self.messages)
