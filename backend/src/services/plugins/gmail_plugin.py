"""Gmail Plugin service for fetching emails securely and writing to GCS.

Stores emails as thread-level JSON files for optimal RAG processing:
    - Path: raw/gmail/{thread_id}/thread.json
    - Schema matches src.services.preprocessing.mail.models.GmailThread
"""

import base64
import json
import re
from datetime import UTC, datetime
from email.utils import parseaddr, parsedate_to_datetime
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from sqlalchemy.orm import Session

from src.services.database_manager.models.auth_models import (
    OpportunitySource,
    User,
)
from src.services.database_manager.user_connection_utils import get_active_connection
from src.services.plugins.google_connector_user import resolve_google_user_for_sync
from src.services.storage.service import Storage
from src.utils.logger import get_logger
from src.utils.opportunity_id import gcs_opportunity_prefix


logger = get_logger(__name__)


def _get_credentials(
    db: Session, user: User, client_id: str, client_secret: str
) -> Credentials | None:
    if not client_id or not client_secret:
        return None
    conn = get_active_connection(db, user.id, "gmail") or get_active_connection(
        db, user.id, "google"
    )
    if not conn or not (conn.refresh_token or "").strip():
        return None
    creds = Credentials(
        token=None,
        refresh_token=conn.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    )
    try:
        creds.refresh(Request())
        return creds
    except Exception as e:
        logger.warning(f"Failed to refresh Gmail creds for user {user.id}: {e}")
        return None


def _decode_body(payload: dict) -> tuple[str, str | None]:
    """Extract plain text and HTML body from Gmail message payload.

    Returns:
        Tuple of (plain_text, html_text). html_text may be None.
    """
    plain_text = ""
    html_text = None

    if "body" in payload and payload["body"].get("data"):
        plain_text = base64.urlsafe_b64decode(payload["body"]["data"]).decode(
            "utf-8", errors="replace"
        )
        return plain_text, html_text

    for part in payload.get("parts", []):
        mime_type = part.get("mimeType", "")
        body_data = part.get("body", {}).get("data")

        if mime_type == "text/plain" and body_data and not plain_text:
            plain_text = base64.urlsafe_b64decode(body_data).decode(
                "utf-8", errors="replace"
            )
        elif mime_type == "text/html" and body_data:
            raw_html = base64.urlsafe_b64decode(body_data).decode(
                "utf-8", errors="replace"
            )
            html_text = raw_html

        # Handle nested multipart
        if "parts" in part:
            nested_plain, nested_html = _decode_body(part)
            if nested_plain and not plain_text:
                plain_text = nested_plain
            if nested_html and not html_text:
                html_text = nested_html

    # If no plain text found, convert HTML to plain text
    if not plain_text and html_text:
        plain_text = re.sub(r"<[^>]+>", " ", html_text)
        plain_text = re.sub(r"\s+", " ", plain_text).strip()

    return plain_text, html_text


def _get_header(headers: list[dict], name: str) -> str:
    for h in headers or []:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _parse_email_address(raw: str) -> dict[str, Any]:
    """Parse an email address string into name and email components."""
    name, email = parseaddr(raw)
    if not email:
        email = raw.strip()
    return {
        "email": email.lower() if email else "",
        "name": name or None,
    }


def _parse_date(date_str: str) -> datetime:
    """Parse an email date header into a datetime object."""
    if not date_str:
        return datetime.now(UTC)
    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        return datetime.now(UTC)


def _build_thread_json(
    thread_data: dict[str, Any],
    opportunity_id: str,
    connector_user_email: str | None = None,
    connector_user_id: int | None = None,
) -> dict[str, Any]:
    """Build a thread JSON structure matching GmailThread schema.

    Args:
        thread_data: Raw thread response from Gmail API.
        opportunity_id: Associated opportunity ID.

    Returns:
        Thread JSON matching the preprocessing schema.
    """
    thread_id = thread_data.get("id", "")
    raw_messages = thread_data.get("messages") or []

    # Process each message
    messages: list[dict[str, Any]] = []
    participants_seen: set[str] = set()
    participants: list[dict[str, Any]] = []
    subject = ""

    for msg in raw_messages:
        payload = msg.get("payload") or {}
        headers = payload.get("headers") or []

        # Extract headers
        msg_subject = _get_header(headers, "Subject")
        sender_raw = _get_header(headers, "From")
        to_raw = _get_header(headers, "To")
        cc_raw = _get_header(headers, "Cc")
        date_raw = _get_header(headers, "Date")
        in_reply_to = _get_header(headers, "In-Reply-To")
        _message_id_header = _get_header(headers, "Message-ID")

        # Parse sender
        sender = _parse_email_address(sender_raw)

        # Parse recipients
        to_list = []
        if to_raw:
            to_list.extend(
                _parse_email_address(addr.strip()) for addr in to_raw.split(",")
            )

        cc_list = []
        if cc_raw:
            cc_list.extend(
                _parse_email_address(addr.strip()) for addr in cc_raw.split(",")
            )

        # Extract body
        body_text, body_html = _decode_body(payload)

        # Parse date
        timestamp = _parse_date(date_raw)

        # Get snippet
        snippet = msg.get("snippet", "")

        # Build message structure
        message_json = {
            "id": msg.get("id", ""),
            "timestamp": timestamp.isoformat(),
            "from": sender,
            "to": to_list,
            "cc": cc_list,
            "in_reply_to": in_reply_to or None,
            "body_text": body_text,
            "body_html": body_html,
            "snippet": snippet,
        }
        messages.append(message_json)

        # Track participants
        if sender.get("email") and sender["email"] not in participants_seen:
            participants.append(sender)
            participants_seen.add(sender["email"])
        for recipient in to_list + cc_list:
            if recipient.get("email") and recipient["email"] not in participants_seen:
                participants.append(recipient)
                participants_seen.add(recipient["email"])

        # Use first non-empty subject
        if not subject and msg_subject:
            subject = msg_subject

    # Sort messages by timestamp
    messages.sort(key=lambda m: m.get("timestamp", ""))

    # Build date range
    if messages:
        first_ts = messages[0].get("timestamp", datetime.now(UTC).isoformat())
        last_ts = messages[-1].get("timestamp", datetime.now(UTC).isoformat())
    else:
        now = datetime.now(UTC).isoformat()
        first_ts = now
        last_ts = now

    # Build thread JSON
    thread_json = {
        "thread_id": thread_id,
        "subject": subject or "(no subject)",
        "participants": participants,
        "message_count": len(messages),
        "date_range": {
            "first": first_ts,
            "last": last_ts,
        },
        "messages": messages,
        "metadata": {
            "opportunity_id": opportunity_id,
            "synced_at": datetime.now(UTC).isoformat(),
            "labels": thread_data.get("labelIds", []),
            "connector_user_email": (connector_user_email or "").strip().lower() or None,
            "connector_user_id": connector_user_id,
        },
    }

    return thread_json


def _gmail_sync_query_list(
    gcs_prefix: str, raw_id: str, checkpoint: str | None
) -> list[str]:
    """Ordered Gmail ``q`` strings: phrase + token matches, Sent/Inbox/anywhere, then without ``after:``.

    Natural subjects like "Update on opportunity id oid1112" are matched via ``subject:{token}``
    and ``in:sent`` / ``in:anywhere`` fallbacks; incremental ``after:`` can hide older Sent mail.
    """
    g = gcs_prefix.strip()
    r = raw_id.strip()
    if g != r:
        core = (
            f'(subject:"{g}" OR subject:"{r}" OR subject:{g} OR subject:{r})'
        )
    else:
        core = f'(subject:"{g}" OR subject:{g})'
    wide = f"in:anywhere ({g} OR subject:{g})"
    sent = f"in:sent ({g} OR subject:{g})"
    inbox = f"in:inbox ({g} OR subject:{g})"
    variants = [core, wide, sent, inbox]

    ordered: list[str] = []
    if checkpoint:
        for v in variants:
            ordered.append(f"{v} after:{checkpoint}")
    for v in variants:
        ordered.append(v)

    seen: set[str] = set()
    out: list[str] = []
    for q in ordered:
        if q not in seen:
            seen.add(q)
            out.append(q)
    return out


def sync_gmail_source(
    db: Session, source: OpportunitySource, client_id: str, client_secret: str
) -> int:
    """Sync Gmail threads matching the opportunity OID and save as JSON to GCS raw/.

    Stores each thread as a single JSON file at:
        raw/gmail/{thread_id}/thread.json

    The JSON schema matches src.services.preprocessing.mail.models.GmailThread
    for seamless preprocessing.
    """
    opp = source.opportunity
    user = resolve_google_user_for_sync(db, opp)
    if not user:
        logger.warning("Sync skipped: User has not connected their Google account.")
        return 0
    creds = _get_credentials(db, user, client_id, client_secret)
    if not creds:
        logger.warning(
            "Gmail sync: failed to build credentials for user {} opportunity_id={}",
            user.id,
            opp.opportunity_id,
        )
        return 0

    try:
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    except Exception as e:
        logger.exception("Failed to build Gmail service: {}", e)
        return 0

    gcs_prefix = gcs_opportunity_prefix(str(opp.opportunity_id))
    if gcs_prefix != str(opp.opportunity_id).strip():
        logger.warning(
            "Gmail sync: DB opportunity_id %r differs from GCS path prefix %r",
            opp.opportunity_id,
            gcs_prefix,
        )

    raw_id = str(opp.opportunity_id)
    queries = _gmail_sync_query_list(
        gcs_prefix, raw_id, (source.sync_checkpoint or "").strip() or None
    )

    # Fetch threads
    threads_synced = 0
    try:
        threads: list[dict[str, Any]] = []
        for q in queries:
            list_resp = (
                service
                .users()
                .threads()
                .list(userId="me", q=q, maxResults=50)
                .execute()
            )
            batch = list_resp.get("threads") or []
            if batch:
                threads = batch
                logger.info(
                    "Gmail sync: listing threads google_user={} opportunity_id={} "
                    "matched_query={!r} thread_count={}",
                    user.email,
                    opp.opportunity_id,
                    q,
                    len(batch),
                )
                break

        if not threads:
            logger.warning(
                "Gmail sync: tried {} query variant(s); 0 threads for db_opp_id={} "
                "source_id={} sync_checkpoint={!r}. If mail exists, check mailbox user "
                "matches the sender, or clear sync_checkpoint and re-run.",
                len(queries),
                opp.opportunity_id,
                source.id,
                source.sync_checkpoint,
            )
            return 0

        storage = Storage()

        for thread_meta in threads:
            thread_id = thread_meta.get("id", "")
            if not thread_id:
                continue

            # Fetch full thread content
            thread_data = (
                service
                .users()
                .threads()
                .get(userId="me", id=thread_id, format="full")
                .execute()
            )

            # Build thread JSON
            thread_json = _build_thread_json(
                thread_data,
                gcs_prefix,
                connector_user_email=(user.email or "").strip().lower() or None,
                connector_user_id=int(user.id) if getattr(user, "id", None) else None,
            )

            # Write to GCS as thread-level file
            storage.write(
                tier="raw",
                opportunity_id=gcs_prefix,
                source="gmail",
                object_name=f"{thread_id}/thread.json",
                content=json.dumps(thread_json, ensure_ascii=False, indent=2),
                content_type="application/json",
            )

            threads_synced += 1
            logger.info(
                "Synced Gmail thread: %s (%d messages)",
                thread_id,
                thread_json["message_count"],
            )

    except Exception as e:
        logger.exception("Gmail fetch error: {}", e)
        return 0

    if threads_synced == 0:
        return 0

    # Update checkpoint
    now = datetime.now(UTC)
    source.last_synced_at = now
    source.sync_checkpoint = now.strftime("%Y/%m/%d")
    db.commit()

    logger.info(
        "Gmail sync: DB updated source_id={} opportunity_id={} threads_synced={} "
        "checkpoint={!r}",
        source.id,
        opp.opportunity_id,
        threads_synced,
        source.sync_checkpoint,
    )
    return threads_synced
