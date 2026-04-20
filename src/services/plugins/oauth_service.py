"""OAuth generic service logic for Slack, Google, and Zoom.

Reads client IDs/secrets from configs (ENV_FILES via get_settings), not raw os.environ
at import time, so values in configs/.env and configs/secrets/.env are visible here.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from urllib.parse import quote_plus

import httpx
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from configs.settings import get_settings
from src.services.database_manager.models.auth_models import User, UserConnection
from src.utils.opportunity_id import normalize_opportunity_oid


SLACK_SCOPES = "channels:read,channels:history,groups:read,groups:history,users:read"

# Optional Google API scopes keyed by integration name (used with base OIDC scopes).
GOOGLE_SCOPES = {
    "gmail": "https://www.googleapis.com/auth/gmail.readonly",
    "drive": "https://www.googleapis.com/auth/drive.readonly",
}

# Base OIDC + profile; provider-specific scope appended when ``provider`` is set.
_GOOGLE_BASE_SCOPES = "openid email profile"


def _oauth():
    return get_settings().oauth_plugin


def build_google_oauth_state(provider: str | None, oid: str | None = None) -> str | None:
    """Build OAuth ``state`` for Google: ``provider`` only, or ``provider:canonical_oid`` (e.g. ``drive:oid560``)."""
    if not provider:
        return None
    key = provider.strip().lower()
    if key not in {"gmail", "drive"}:
        raise ValueError("provider for Google OAuth state must be 'gmail' or 'drive'.")
    trimmed_oid = (oid or "").strip()
    if trimmed_oid:
        canon = normalize_opportunity_oid(trimmed_oid)
        return f"{key}:{canon}"
    return key


def parse_google_oauth_state(state: str | None) -> tuple[str, str | None]:
    """Parse Google OAuth state: plain ``gmail``/``drive`` or ``provider:oid123``."""
    raw = (state or "").strip()
    if not raw:
        return "gmail", None
    if ":" in raw:
        left, right = raw.split(":", 1)
        pk = left.strip().lower()
        rest = right.strip()
        if pk in {"gmail", "drive"}:
            oid_out: str | None = None
            if rest:
                try:
                    oid_out = normalize_opportunity_oid(rest)
                except ValueError:
                    oid_out = None
            return pk, oid_out
    s = raw.lower()
    if s in {"gmail", "drive"}:
        return s, None
    return "gmail", None


async def get_google_auth_url(
    redirect_uri: str, provider: str | None = None, state: str | None = None
) -> str:
    o = _oauth()
    cid = (o.google_client_id or "").strip()
    if not cid:
        raise ValueError(
            "GOOGLE_CLIENT_ID is empty. Set GOOGLE_CLIENT_ID (and GOOGLE_CLIENT_SECRET) in "
            "configs/.env or configs/secrets/.env, then restart the API."
        )
    scope_parts = [_GOOGLE_BASE_SCOPES]
    if provider:
        key = provider.strip().lower()
        extra = GOOGLE_SCOPES.get(key)
        if extra is None:
            raise ValueError(
                f"Unknown Google OAuth provider {provider!r}; "
                f"expected one of: {', '.join(sorted(GOOGLE_SCOPES))}."
            )
        scope_parts.append(extra)
    else:
        # Backward compatible: same combined scopes as before scope isolation.
        scope_parts.append(GOOGLE_SCOPES["gmail"])
        scope_parts.append(GOOGLE_SCOPES["drive"])
    scope_str = " ".join(scope_parts)
    encoded_redirect_uri = quote_plus(redirect_uri)
    encoded_scope = quote_plus(scope_str)
    url = (
        f"https://accounts.google.com/o/oauth2/v2/auth?"
        f"client_id={quote_plus(cid)}&"
        f"redirect_uri={encoded_redirect_uri}&"
        f"response_type=code&"
        f"scope={encoded_scope}&"
        f"access_type=offline&"
        f"prompt=consent"
    )
    if state:
        url += f"&state={quote_plus(state)}"
    return url


async def exchange_google_code(
    code: str, redirect_uri: str, db: Session, provider: str = "gmail"
) -> dict:
    """Exchange code for Google tokens; upsert ``user_connections`` row for isolated provider."""
    provider_key = (provider or "").strip().lower()
    if provider_key not in {"gmail", "drive"}:
        raise ValueError("Google OAuth provider must be 'gmail' or 'drive'.")
    o = _oauth()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": o.google_client_id,
                "client_secret": o.google_client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
        )
    if resp.status_code != 200:
        raise ValueError(f"Google Token Exchange Failed: {resp.text}")

    token_data = resp.json()
    id_token_str = token_data.get("id_token")
    if not id_token_str:
        raise ValueError("No ID token received from Google.")

    idinfo = id_token.verify_oauth2_token(
        id_token_str,
        google_requests.Request(),
        o.google_client_id,
        clock_skew_in_seconds=10,
    )
    email = idinfo.get("email")
    if not email:
        raise ValueError("No email in Google ID token.")

    user = db.query(User).filter(User.email == email).first()
    if not user:
        user = User(email=email, name=idinfo.get("name"))
        db.add(user)
        try:
            db.flush()
        except IntegrityError:
            # Another transaction may have inserted the same user concurrently,
            # or a stale DB sequence may have caused an insert collision.
            db.rollback()
            user = db.query(User).filter(User.email == email).first()
            if not user:
                raise

    access_token = (token_data.get("access_token") or "").strip()
    if not access_token:
        raise ValueError("No access token from Google.")

    refresh_token = (token_data.get("refresh_token") or "").strip()
    existing = (
        db.query(UserConnection)
        .filter(
            UserConnection.user_id == user.id,
            UserConnection.provider == provider_key,
        )
        .order_by(UserConnection.id.desc())
        .first()
    )
    if not refresh_token and existing:
        refresh_token = (existing.refresh_token or "").strip()
    if not refresh_token:
        raise ValueError(
            "No refresh token from Google. Revoke app access and sign in again, or "
            "ensure prompt=consent so a refresh token is issued."
        )

    scope_raw = (token_data.get("scope") or "").strip()
    granted_scopes = [s for s in scope_raw.split() if s] if scope_raw else None

    # Google access tokens expire in ~1 hour, but we hold a permanent refresh_token.
    # Setting expires_at=None prevents get_active_connection() from treating the
    # connection as dead once the short-lived access token expires.
    expires_at = None

    if existing:
        existing.access_token = access_token
        existing.refresh_token = refresh_token
        existing.granted_scopes = granted_scopes
        existing.expires_at = expires_at
        existing.status = "active"
    else:
        db.add(
            UserConnection(
                user_id=user.id,
                provider=provider_key,
                access_token=access_token,
                refresh_token=refresh_token,
                granted_scopes=granted_scopes,
                status="active",
                expires_at=expires_at,
            )
        )

    db.commit()
    return {
        "email": user.email,
        "message": "Google authentication successful",
        "provider": provider_key,
    }


async def get_slack_auth_url(redirect_uri: str, state: str | None = None) -> str:
    """Build Slack authorize URL. Pass ``state`` (e.g. user email); Slack returns it on callback GET."""
    o = _oauth()
    encoded_redirect_uri = quote_plus(redirect_uri)
    url = (
        "https://slack.com/oauth/v2/authorize?"
        f"client_id={o.slack_client_id}&"
        f"scope={quote_plus(SLACK_SCOPES)}&"
        f"redirect_uri={encoded_redirect_uri}"
    )
    if state:
        url += f"&state={quote_plus(state)}"
    return url


async def exchange_slack_code(
    code: str, redirect_uri: str, db: Session, user_email: str
) -> dict:
    """Exchange code for Slack bot token and attach to a specific user/tenant."""
    o = _oauth()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://slack.com/api/oauth.v2.access",
            data={
                "client_id": o.slack_client_id,
                "client_secret": o.slack_client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    data = resp.json()
    if not data.get("ok"):
        raise ValueError(f"Slack Token Exchange failed: {data.get('error')}")

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        raise ValueError(f"User {user_email} not found to attach Slack token to.")

    access_token = (data.get("access_token") or "").strip()
    if not access_token:
        raise ValueError("Slack OAuth did not return an access token.")
    scope_raw = (data.get("scope") or "").strip()
    granted_scopes = [s for s in scope_raw.split(",") if s.strip()] if scope_raw else None

    # Backward compatibility with existing Slack plugin reads.
    user.slack_access_token = access_token

    existing = (
        db.query(UserConnection)
        .filter(
            UserConnection.user_id == user.id,
            UserConnection.provider == "slack",
        )
        .order_by(UserConnection.id.desc())
        .first()
    )
    if existing:
        existing.access_token = access_token
        existing.refresh_token = access_token
        existing.granted_scopes = granted_scopes
        existing.status = "active"
        existing.expires_at = None
    else:
        db.add(
            UserConnection(
                user_id=user.id,
                provider="slack",
                access_token=access_token,
                refresh_token=access_token,
                granted_scopes=granted_scopes,
                status="active",
                expires_at=None,
            )
        )
    db.commit()
    return {
        "message": "Slack workspace connected securely.",
        "email": user.email,
        "granted_scopes": granted_scopes or [],
    }


async def get_zoom_s2s_token(
    account_id: str, client_id: str, client_secret: str
) -> str:
    """Fetch Zoom S2S OAuth token natively. Usually valid for 1 hour."""
    url = f"https://zoom.us/oauth/token?grant_type=account_credentials&account_id={account_id}"
    auth_str = f"{client_id}:{client_secret}"
    b64_auth = base64.b64encode(auth_str.encode()).decode()

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Basic {b64_auth}"},
        )
        if resp.status_code == 200:
            return resp.json().get("access_token", "")
        raise ValueError(f"Zoom token failed: {resp.text}")
