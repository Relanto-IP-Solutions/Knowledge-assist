"""Resolve which ``users`` row should authorize Drive/Gmail sync for an opportunity."""

from __future__ import annotations

from sqlalchemy.orm import Session

from configs.settings import get_settings
from src.services.database_manager.models.auth_models import Opportunity, User
from src.services.database_manager.user_connection_utils import (
    get_active_connection,
    query_users_with_active_provider,
)
from src.utils.logger import get_logger


logger = get_logger(__name__)


def resolve_google_user_for_sync(
    db: Session, opportunity: Opportunity, provider: str = "gmail"
) -> User | None:
    """Return the Google OAuth user to use for Drive/Gmail sync.

    Discover for Slack sets ``opportunities.owner_id`` to the **Slack** connector, who often
    has **no** active Google ``user_connections`` row. Drive/Gmail data lives under the **Google**
    connector (same account as ``/drive/discover`` / ``/gmail/discover``), so when the owner lacks
    Google OAuth we fall back to ``GMAIL_CONNECTOR_USER_EMAIL``, then
    ``DRIVE_CONNECTOR_USER_EMAIL``, then the first user with an active ``google`` connection.
    """
    provider_key = (provider or "gmail").strip().lower()
    owner = opportunity.owner
    if owner and get_active_connection(db, owner.id, provider_key):
        return owner

    gs = get_settings().gmail
    ds = get_settings().drive
    if provider_key == "drive":
        email = (ds.drive_connector_user_email or gs.gmail_connector_user_email or "").strip().lower()
    else:
        email = (gs.gmail_connector_user_email or ds.drive_connector_user_email or "").strip().lower()
    q = query_users_with_active_provider(db, provider_key)
    fallback: User | None = None
    if email:
        fallback = q.filter(User.email == email).first()
    if not fallback:
        fallback = q.order_by(User.id.asc()).first()

    if owner and fallback and owner.id != fallback.id:
        logger.info(
            "Google sync: opportunity owner {!r} has no active Google connection; "
            "using connector user {!r} for opportunity_id={!r}",
            getattr(owner, "email", None),
            fallback.email,
            opportunity.opportunity_id,
        )
    elif not owner and fallback:
        logger.info(
            "Google sync: using connector user {!r} for opportunity_id={!r}",
            fallback.email,
            opportunity.opportunity_id,
        )

    return fallback
