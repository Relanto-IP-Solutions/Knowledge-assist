"""Gmail sync engine: fetch threads for an OID and write GmailThread JSON to GCS."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Any

from bs4 import BeautifulSoup
from googleapiclient.discovery import build
from sqlalchemy.orm import Session

from configs.settings import get_settings
from src.services.database_manager.models.auth_models import (
    Opportunity,
    OpportunitySource,
    User,
)
from src.services.database_manager.orm import get_engine
from src.services.database_manager.user_connection_utils import (
    get_active_connection,
)
from src.services.plugins.gmail_plugin import _build_thread_json, _get_credentials
from src.services.plugins.google_connector_user import resolve_google_user_for_sync
from src.services.preprocessing.mail.models import GmailThread
from src.services.storage.service import Storage
from src.utils.logger import get_logger
from src.utils.opportunity_id import gcs_opportunity_prefix, normalize_opportunity_oid

logger = get_logger(__name__)


def resolve_gmail_discovery_user(
    db: Session, user_email: str | None = None
) -> User | None:
    """Resolve discovery mailbox user from explicit email only.

    Accept both isolated ``gmail`` and legacy ``google`` provider rows.
    """
    if user_email:
        email = user_email.strip().lower()
        user = db.query(User).filter(User.email == email).first()
        if not user:
            return None
        if get_active_connection(db, user.id, "gmail") or get_active_connection(
            db, user.id, "google"
        ):
            return user
        return None
    return None


def clean_body(html: str) -> str:
    """Strip scripts/styles from HTML while preserving logical newlines."""
    if not html or not str(html).strip():
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return soup.get_text(separator="\n")


def _apply_clean_body_to_messages(thread_json: dict[str, Any]) -> None:
    for msg in thread_json.get("messages") or []:
        if not isinstance(msg, dict):
            continue
        bh = msg.get("body_html")
        if isinstance(bh, str) and bh.strip():
            cleaned = clean_body(bh)
            if cleaned.strip():
                msg["body_text"] = cleaned


def _sync_opportunity_impl(oid: str) -> dict[str, Any]:
    normalized = normalize_opportunity_oid(oid)
    o = get_settings().oauth_plugin
    client_id = (o.google_client_id or "").strip()
    client_secret = (o.google_client_secret or "").strip()

    with Session(get_engine()) as db:
        opp = (
            db.query(Opportunity)
            .filter(Opportunity.opportunity_id == normalized)
            .first()
        )
        if not opp:
            raise ValueError(f"Opportunity not found for oid '{normalized}'.")

        source = (
            db.query(OpportunitySource)
            .filter(
                OpportunitySource.opportunity_id == opp.id,
                OpportunitySource.source_type == "gmail",
            )
            .first()
        )
        if not source:
            raise ValueError(f"No gmail opportunity source for oid '{normalized}'.")

        user = resolve_google_user_for_sync(db, opp)
        if not user:
            logger.warning(
                "GmailSyncService: no user with active Google connection for oid={}",
                normalized,
            )
            return {"ok": False, "threads_synced": 0, "error": "no_google_user"}

        creds = _get_credentials(db, user, client_id, client_secret)
        if not creds:
            return {"ok": False, "threads_synced": 0, "error": "credentials"}

        service = build("gmail", "v1", credentials=creds, cache_discovery=False)

        gcs_prefix = gcs_opportunity_prefix(str(opp.opportunity_id))
        strict_query = f"(subject:{normalized} OR body:{normalized})"
        list_resp = (
            service.users().threads().list(userId="me", q=strict_query, maxResults=100).execute()
        )
        threads: list[dict[str, Any]] = list_resp.get("threads") or []
        if threads:
            logger.info(
                "GmailSyncService: strict query matched thread_count={} oid={} query={!r}",
                len(threads),
                normalized,
                strict_query,
            )

        if not threads:
            logger.warning(
                "GmailSyncService: no threads for oid={} with strict query={!r}",
                normalized,
                strict_query,
            )
            return {"ok": True, "threads_synced": 0}

        storage = Storage()
        threads_synced = 0

        for thread_meta in threads:
            thread_id = thread_meta.get("id", "")
            if not thread_id:
                continue

            thread_data = (
                service.users()
                .threads()
                .get(userId="me", id=thread_id, format="full")
                .execute()
            )

            thread_json = _build_thread_json(
                thread_data,
                gcs_prefix,
                connector_user_email=(user.email or "").strip().lower() or None,
                connector_user_id=int(user.id) if getattr(user, "id", None) else None,
            )
            _apply_clean_body_to_messages(thread_json)

            try:
                GmailThread.model_validate(thread_json)
            except Exception as exc:
                logger.warning(
                    "GmailSyncService: GmailThread validation failed thread_id={}: {}",
                    thread_id,
                    exc,
                )
                continue

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
                "GmailSyncService: wrote raw/gmail/{}/thread.json ({} messages)",
                thread_id,
                thread_json.get("message_count", 0),
            )

        if threads_synced:
            now = datetime.now(UTC)
            source.last_synced_at = now
            source.sync_checkpoint = now.strftime("%Y/%m/%d")
            db.commit()

        return {"ok": True, "threads_synced": threads_synced}


class GmailSyncService:
    """Orchestrate Gmail thread fetch + GCS write for one opportunity."""

    async def sync_opportunity(self, oid: str) -> dict[str, Any]:
        """Search Gmail by OID in subject, fetch full threads, save ``GmailThread`` JSON to GCS."""
        return await asyncio.to_thread(_sync_opportunity_impl, oid)
