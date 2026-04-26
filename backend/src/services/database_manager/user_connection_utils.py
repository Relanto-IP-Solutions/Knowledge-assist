"""Resolve OAuth tokens from ``user_connections`` (per-provider, non-expired)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import or_
from sqlalchemy.orm import Query, Session

from src.services.database_manager.models.auth_models import User, UserConnection


def get_active_connection(
    db: Session, user_id: int, provider: str
) -> UserConnection | None:
    """Most recent non-expired connection for ``provider`` (``expires_at`` None = unknown)."""
    now = datetime.now(UTC)
    return (
        db.query(UserConnection)
        .filter(
            UserConnection.user_id == user_id,
            UserConnection.provider == provider,
            or_(
                UserConnection.expires_at.is_(None),
                UserConnection.expires_at > now,
                UserConnection.refresh_token.is_not(None),
            ),
        )
        .order_by(UserConnection.id.desc())
        .first()
    )


def query_users_with_active_provider(db: Session, provider: str) -> Query:
    """Distinct users with at least one active (non-expired) connection for ``provider``."""
    now = datetime.now(UTC)
    return (
        db.query(User)
        .join(UserConnection, User.id == UserConnection.user_id)
        .filter(
            UserConnection.provider == provider,
            or_(UserConnection.expires_at.is_(None), UserConnection.expires_at > now),
        )
        .distinct()
    )


def has_google_scopes(db: Session, user_id: int, required_scopes: list[str]) -> bool:
    """True when the user has an active Gmail/Google connection with all required scopes."""
    if not required_scopes:
        return True
    # Prefer isolated gmail provider; keep legacy fallback to google rows.
    conn = get_active_connection(db, user_id, "gmail") or get_active_connection(
        db, user_id, "google"
    )
    if not conn:
        return False
    granted = conn.granted_scopes
    if not isinstance(granted, list):
        return False
    granted_set = {str(s).strip() for s in granted if str(s).strip()}
    required_set = {str(s).strip() for s in required_scopes if str(s).strip()}
    return required_set.issubset(granted_set)


def has_provider_scopes(
    db: Session, user_id: int, provider: str, required_scopes: list[str]
) -> bool:
    """True when the user has an active provider connection with all required scopes."""
    if not required_scopes:
        return True
    conn = get_active_connection(db, user_id, provider)
    if not conn:
        return False
    granted = conn.granted_scopes
    if not isinstance(granted, list):
        return False
    granted_set = {str(s).strip() for s in granted if str(s).strip()}
    required_set = {str(s).strip() for s in required_scopes if str(s).strip()}
    return required_set.issubset(granted_set)
