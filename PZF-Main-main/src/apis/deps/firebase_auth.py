"""Firebase ID token auth for protected routes.

Flow (``get_firebase_user``): (1) read ``Authorization: Bearer`` token; (2) **verify** the JWT
(signature, ``iss``, ``aud``, ``exp``) — not decode-only; (3) read Firebase UID from claims
(``sub`` / ``user_id`` / ``uid``); (4) load ``users`` where ``firebase_uid`` matches, or one-time
link by verified email if ``firebase_uid`` is null; (5) return the ORM ``User`` so route handlers
run normal RBAC (owner / team / admin) on ``user.id`` / ``user.roles_assigned``.
"""

from __future__ import annotations

from typing import Annotated

import threading
import time
import firebase_admin
from fastapi import Depends, HTTPException, Request
from firebase_admin import auth
from sqlalchemy import func, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from configs.settings import get_settings
from src.services.auth.firebase_init import ensure_firebase_initialized
from src.services.auth.firebase_public_verify import verify_firebase_id_token_public
from src.services.database_manager.models.auth_models import User
from src.services.database_manager.connection import get_db_connection
from src.services.database_manager.orm import get_db
from src.utils.logger import get_logger


logger = get_logger(__name__)

_TOKEN_CACHE_LOCK = threading.Lock()
_TOKEN_CACHE: dict[str, tuple[dict, float]] = {}
_TOKEN_CACHE_MAX = 512

_USER_CACHE_LOCK = threading.Lock()
_USER_CACHE: dict[str, tuple[dict, float]] = {}
_USER_CACHE_TTL_S = 300.0


def _raw_user_lookup_by_firebase_uid(uid: str) -> tuple[int, str, str | None, list[str] | None] | None:
    """Lookup `users` by firebase_uid using the pooled raw connection.

    This avoids SQLAlchemy session checkout issues on transient pg8000 network resets.
    Returns tuple(id, email, name, roles_assigned) or None.
    """
    last_exc: Exception | None = None
    for attempt in range(2):
        try:
            con = get_db_connection()
            try:
                cur = con.cursor()
                # Bound execution time; Cloud SQL can occasionally stall.
                try:
                    cur.execute("SET statement_timeout TO 20000")
                except Exception:
                    pass
                cur.execute(
                    """
                    SELECT id, email, name, roles_assigned
                    FROM users
                    WHERE firebase_uid = %s
                    LIMIT 1
                    """,
                    (uid,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return int(row[0]), str(row[1]), row[2], row[3]
            finally:
                # close() returns to pool; if the connection is broken, driver close may fail
                try:
                    con.close()
                except Exception:
                    pass
        except Exception as exc:
            last_exc = exc
            # Retry once on transient failures.
            continue
    if last_exc is not None:
        raise last_exc
    return None


def get_bearer_token(request: Request) -> str:
    """Return the raw JWT from ``Authorization: Bearer <token>``."""
    raw = (request.headers.get("Authorization") or "").strip()
    if not raw.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid Authorization header (expected Bearer token).",
        )
    token = raw[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token.")
    return token


def _extract_roles_assigned_from_claims(decoded: dict) -> list[str] | None:
    """Extract multi-role RBAC from Firebase claims.

    Supports:
    - ``roles``: list[str] or comma-separated str
    - ``role``: single str

    Returns ``None`` when absent/empty (so DB stays NULL by default).
    """
    raw = decoded.get("roles")
    if raw is None:
        raw = decoded.get("role")

    items: list[str] = []
    if isinstance(raw, str):
        # Allow either a single role or a comma-separated list.
        parts = [p.strip() for p in raw.replace(";", ",").split(",")]
        items = [p for p in parts if p]
    elif isinstance(raw, (list, tuple, set)):
        items = [str(r).strip() for r in raw if str(r).strip()]
    elif raw is None:
        items = []
    else:
        items = [str(raw).strip()] if str(raw).strip() else []

    normed: list[str] = []
    seen: set[str] = set()
    for r in items:
        ru = r.strip().upper()
        if not ru:
            continue
        if ru in seen:
            continue
        seen.add(ru)
        normed.append(ru)

    return normed or None


def _extract_user_name_from_claims(decoded: dict, email: str | None) -> str | None:
    """Best-effort display name from Firebase claims.

    Returns None if unavailable (so DB stays NULL).
    """
    raw = decoded.get("name") or decoded.get("display_name") or decoded.get("displayName")
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s.lower() == "none" or s.lower() == "null":
        return None
    return s


def _fetch_firebase_display_name(uid: str) -> str | None:
    """Fetch displayName directly from Firebase Auth (Admin SDK)."""
    try:
        u = auth.get_user(uid)
    except Exception:
        return None
    dn = getattr(u, "display_name", None)
    if dn is None:
        return None
    s = str(dn).strip()
    if not s or s.lower() in {"none", "null"}:
        return None
    return s


def verify_firebase_token(token: str) -> dict:
    """Verify a Firebase ID token and return decoded claims.

    Uses the Admin SDK when ``FIREBASE_SERVICE_ACCOUNT_PATH`` is configured; otherwise
    verifies via Google's public x509 keys when ``FIREBASE_PROJECT_ID`` is set (no key file).
    """
    # Hot path optimization: cache verified tokens until their `exp`.
    # This avoids repeated public key fetch / signature verification cost.
    now = time.time()
    with _TOKEN_CACHE_LOCK:
        hit = _TOKEN_CACHE.get(token)
        if hit and hit[1] > now:
            return hit[0]

    settings = get_settings().firebase_auth
    project_id = (settings.project_id or "").strip()

    t0 = time.perf_counter()
    ensure_firebase_initialized()
    try:
        firebase_admin.get_app()
    except ValueError:
        pass
    else:
        try:
            decoded = auth.verify_id_token(token)
            # Cache until exp (minus a small safety buffer).
            exp = float(decoded.get("exp") or 0)
            ttl_until = max(now + 1.0, exp - 5.0) if exp else (now + 30.0)
            with _TOKEN_CACHE_LOCK:
                if len(_TOKEN_CACHE) >= _TOKEN_CACHE_MAX:
                    _TOKEN_CACHE.clear()
                _TOKEN_CACHE[token] = (decoded, ttl_until)
            logger.info(
                "auth timing | verify_ms={} path=admin_sdk",
                int((time.perf_counter() - t0) * 1000),
            )
            return decoded
        except Exception as exc:
            logger.debug("Firebase verify_id_token failed: {}", exc)
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired token.",
            ) from None

    if project_id:
        try:
            decoded = verify_firebase_id_token_public(token, project_id)
            exp = float(decoded.get("exp") or 0)
            ttl_until = max(now + 1.0, exp - 5.0) if exp else (now + 30.0)
            with _TOKEN_CACHE_LOCK:
                if len(_TOKEN_CACHE) >= _TOKEN_CACHE_MAX:
                    _TOKEN_CACHE.clear()
                _TOKEN_CACHE[token] = (decoded, ttl_until)
            logger.info(
                "auth timing | verify_ms={} path=public_keys",
                int((time.perf_counter() - t0) * 1000),
            )
            return decoded
        except ValueError as exc:
            logger.debug("Public-key Firebase verify failed: {}", exc)
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired token.",
            ) from None

    raise HTTPException(
        status_code=503,
        detail=(
            "Firebase authentication is not configured: set FIREBASE_SERVICE_ACCOUNT_PATH "
            "and/or FIREBASE_PROJECT_ID (project ID enables verification without a key file)."
        ),
    )


def _parse_email_allowlist(raw: str) -> frozenset[str]:
    parts = (raw or "").split(",")
    return frozenset(p.strip().lower() for p in parts if p.strip())


def get_firebase_user(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """Resolve ``User`` after verifying the token and matching Firebase UID to ``users``.

    - **Verify** the ID token, then read the Firebase user id (same as ``users.firebase_uid``).
    - **Match:** ``users.firebase_uid = <uid>`` — if a row exists, use it for RBAC.
    - **UID not in DB yet:** if no row has this ``firebase_uid``, but the token includes
      ``email``, look up ``users`` by that email. If found and ``firebase_uid`` is empty/null
      (or already this ``uid``), **save** ``firebase_uid = <uid>`` and commit. If ``firebase_uid``
      is set to a **different** uid → 403.
    - **No row:** 403 ``User not registered``.
    - Optional ``AUTH_EMAIL_ALLOWLIST``: if set, token email must be in the list.
    """
    t_req0 = time.perf_counter()
    token = get_bearer_token(request)
    decoded = verify_firebase_token(token)
    uid = (
        (decoded.get("uid") or decoded.get("sub") or decoded.get("user_id") or "")
        .strip()
    )
    if not uid:
        raise HTTPException(status_code=401, detail="Invalid token: missing uid.")

    email_raw = decoded.get("email")
    email = (email_raw or "").strip().lower() or None
    log_ctx = {"firebase_uid": uid, "email": email}

    fa = get_settings().firebase_auth
    allowlist = _parse_email_allowlist(fa.email_allowlist)
    if allowlist:
        if not email or email not in allowlist:
            logger.bind(**log_ctx).warning(
                "Auth rejected: email not in allowlist (size={})",
                len(allowlist),
            )
            raise HTTPException(status_code=403, detail="Email not allowed.")

    now_s = time.time()
    with _USER_CACHE_LOCK:
        cached = _USER_CACHE.get(uid)
        if cached and cached[1] > now_s:
            snap = cached[0]
            u = User()
            u.id = snap["id"]
            u.email = snap["email"]
            u.name = snap.get("name")
            u.firebase_uid = uid
            u.roles_assigned = snap.get("roles_assigned")
            return u

    t0 = time.perf_counter()
    try:
        tup = _raw_user_lookup_by_firebase_uid(uid)
    except Exception as exc:
        logger.bind(**log_ctx).warning("Auth user lookup failed: {}", exc)
        raise HTTPException(
            status_code=503,
            detail="Database unavailable while validating user.",
        ) from None
    ms = int((time.perf_counter() - t0) * 1000)
    hit = bool(tup)
    logger.info(
        "auth timing | user_lookup_ms={} hit={} total_ms={}",
        ms,
        hit,
        int((time.perf_counter() - t_req0) * 1000),
    )
    if tup:
        u = User()
        u.id = int(tup[0])
        u.email = str(tup[1])
        u.name = tup[2]
        u.firebase_uid = uid
        u.roles_assigned = tup[3]

        snap = {
            "id": u.id,
            "email": u.email,
            "name": u.name,
            "roles_assigned": u.roles_assigned,
        }
        with _USER_CACHE_LOCK:
            if len(_USER_CACHE) >= _TOKEN_CACHE_MAX:
                _USER_CACHE.clear()
            _USER_CACHE[uid] = (snap, now_s + _USER_CACHE_TTL_S)
        return u

    # Token uid not stored yet: link by verified email and persist firebase_uid on users row.
    if email:
        by_email = db.query(User).filter(func.lower(User.email) == email).first()
        if by_email:
            existing = (by_email.firebase_uid or "").strip()
            if existing and existing != uid:
                logger.bind(**log_ctx).warning(
                    "Auth rejected: email linked to different uid (existing_uid={})",
                    existing,
                )
                raise HTTPException(
                    status_code=403,
                    detail="This account is linked to a different sign-in.",
                )
            if not existing or existing != uid:
                by_email.firebase_uid = uid

                # On first link, persist roles into roles_assigned (do not default a role).
                roles_assigned = _extract_roles_assigned_from_claims(decoded)
                if roles_assigned is not None:
                    by_email.roles_assigned = roles_assigned

                # Backfill name if it's still empty.
                if not (getattr(by_email, "name", None) or "").strip():
                    nm = _extract_user_name_from_claims(decoded, email) or _fetch_firebase_display_name(uid)
                    if nm is not None:
                        by_email.name = nm

                db.commit()
                db.refresh(by_email)
            return by_email

        # No existing user row: create on first login (generic / Google / Microsoft via Firebase).
        # Roles are optional; keep NULL by default (no implicit SALES_REP).
        user_name = _extract_user_name_from_claims(decoded, email) or _fetch_firebase_display_name(uid)
        roles_assigned = _extract_roles_assigned_from_claims(decoded)

        # IMPORTANT: do not pass `role` at all on insert. In some DBs it's a Postgres enum
        # (user_role); SQLAlchemy/pg8000 will emit a VARCHAR-typed NULL for `role`, which
        # Postgres rejects. Keeping it out of the INSERT avoids the type error.
        new_user = User(
            email=email,
            name=user_name,
            firebase_uid=uid,
            roles_assigned=roles_assigned,
        )
        db.add(new_user)
        try:
            db.commit()
            db.refresh(new_user)
            return new_user
        except DBAPIError:
            # Idempotency: another request (or /api/auth/register) may have created the row
            # concurrently, causing unique violations on firebase_uid/email. Roll back and
            # load the existing user instead of failing the request.
            db.rollback()
            existing2 = db.query(User).filter(User.firebase_uid == uid).first()
            if existing2:
                return existing2
            if email:
                by_email2 = db.query(User).filter(func.lower(User.email) == email).first()
                if by_email2:
                    return by_email2
            raise

    logger.bind(**log_ctx).warning("Auth rejected: user not registered")
    raise HTTPException(status_code=403, detail="User not registered.")


def get_existing_firebase_user(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> User:
    """Strict variant of ``get_firebase_user``.

    - Verifies the Firebase ID token.
    - Requires an existing ``users`` row with ``firebase_uid = <uid>``.
    - Does **not** link by email and does **not** auto-create users.
    """
    t_req0 = time.perf_counter()
    token = get_bearer_token(request)
    decoded = verify_firebase_token(token)
    uid = ((decoded.get("uid") or decoded.get("sub") or decoded.get("user_id") or "").strip())
    if not uid:
        raise HTTPException(status_code=401, detail="Invalid token: missing uid.")

    email_raw = decoded.get("email")
    email = (email_raw or "").strip().lower() or None
    log_ctx = {"firebase_uid": uid, "email": email}

    fa = get_settings().firebase_auth
    allowlist = _parse_email_allowlist(fa.email_allowlist)
    if allowlist:
        if not email or email not in allowlist:
            logger.bind(**log_ctx).warning(
                "Auth rejected: email not in allowlist (size={})",
                len(allowlist),
            )
            raise HTTPException(status_code=403, detail="Email not allowed.")

    now_s = time.time()
    with _USER_CACHE_LOCK:
        cached = _USER_CACHE.get(uid)
        if cached and cached[1] > now_s:
            snap = cached[0]
            u = User()
            u.id = snap["id"]
            u.email = snap["email"]
            u.name = snap.get("name")
            u.firebase_uid = uid
            u.roles_assigned = snap.get("roles_assigned")
            return u

    t0 = time.perf_counter()
    try:
        tup = _raw_user_lookup_by_firebase_uid(uid)
    except Exception as exc:
        logger.bind(**log_ctx).warning("Auth strict lookup failed: {}", exc)
        raise HTTPException(
            status_code=503,
            detail="Database unavailable while validating user.",
        ) from None

    ms = int((time.perf_counter() - t0) * 1000)
    hit = bool(tup)
    logger.info(
        "auth timing | user_lookup_ms={} hit={} total_ms={}",
        ms,
        hit,
        int((time.perf_counter() - t_req0) * 1000),
    )
    if not tup:
        logger.bind(**log_ctx).warning("Auth rejected: user not found")
        raise HTTPException(status_code=404, detail="User not found.")

    u = User()
    u.id = int(tup[0])
    u.email = str(tup[1])
    u.name = tup[2]
    u.firebase_uid = uid
    u.roles_assigned = tup[3]

    snap = {
        "id": u.id,
        "email": u.email,
        "name": u.name,
        "roles_assigned": u.roles_assigned,
    }
    with _USER_CACHE_LOCK:
        if len(_USER_CACHE) >= _TOKEN_CACHE_MAX:
            _USER_CACHE.clear()
        _USER_CACHE[uid] = (snap, now_s + _USER_CACHE_TTL_S)
    return u
