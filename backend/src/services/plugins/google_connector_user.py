"""Resolve which ``users`` row should authorize Drive/Gmail sync.
STRICT PRIVACY: FALLBACKS DISABLED.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from src.services.database_manager.models.auth_models import Opportunity, User
from src.services.database_manager.user_connection_utils import get_active_connection


def resolve_google_user_for_sync(
    db: Session, opportunity: Opportunity, provider: str = "gmail"
) -> User | None:
    """Return opportunity owner only when they have an active Google connection."""
    provider_key = (provider or "gmail").strip().lower()
    owner = opportunity.owner
    if owner and get_active_connection(db, owner.id, provider_key):
        return owner
    return None
