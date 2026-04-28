from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import func, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from src.apis.deps.firebase_auth import (
    get_bearer_token,
    get_firebase_user,
    verify_firebase_token,
)
from configs.settings import get_settings
from src.services.database_manager.orm import get_db
from src.services.database_manager.models.auth_models import User, UserConnection
from src.services.plugins import oauth_service
from src.utils.logger import get_logger
from src.utils.opportunity_id import normalize_opportunity_oid


logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])
# Non-prefixed auth endpoints that must match existing redirect URLs / clients.
external_router = APIRouter(tags=["auth"])


class AuthCodeRequest(BaseModel):
    code: str
    redirect_uri: str
    provider: str | None = None
    user_email: str = (
        None  # Needed specifically to attach Slack tokens to an existing user
    )


class UpdateProfileRequest(BaseModel):
    # Accept common FE keys; we will store into users.name.
    name: str | None = None
    displayName: str | None = None
    display_name: str | None = None
    displayname: str | None = None


def _build_microsoft_oauth_state(oid: str | None, user_email: str | None) -> str | None:
    oid_clean = (oid or "").strip().lower()
    email_clean = (user_email or "").strip().lower()
    if oid_clean and email_clean:
        return f"{oid_clean}|{email_clean}"
    return oid_clean or email_clean or None


def _parse_microsoft_oauth_state(state: str | None) -> tuple[str | None, str | None]:
    raw = (state or "").strip()
    if not raw:
        return None, None
    if "|" in raw:
        left, right = raw.split("|", 1)
        return (left.strip().lower() or None), (right.strip().lower() or None)
    token = raw.lower()
    if "@" in token:
        return None, token
    return token, None


@router.post("/me")
async def update_my_profile(
    body: UpdateProfileRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_firebase_user)],
):
    """Persist user profile fields provided by the frontend after login/signup.

    Frontend should send the Firebase ID token as:
    Authorization: Bearer <token>
    """
    # Store exactly what FE sends (no trimming). Treat whitespace-only as NULL.
    raw_name = body.name
    if raw_name is None:
        raw_name = body.displayName
    if raw_name is None:
        raw_name = body.display_name
    if raw_name is None:
        raw_name = body.displayname

    if raw_name is None:
        user.name = None
    else:
        s = str(raw_name)
        user.name = None if s.strip() == "" else s
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"status": "success", "id": user.id, "email": user.email, "name": user.name}


@router.get("/google/url")
async def google_url(
    redirect_uri: str,
    db: Annotated[Session, Depends(get_db)],
    provider: str | None = Query(
        default=None,
        description="Optional: 'gmail' or 'drive' to request only that Google API scope.",
    ),
    oid: str | None = Query(
        default=None,
        description="Optional project oid; encoded in OAuth state (e.g. drive:oid560) for redirect after login.",
    ),
    user_email: str | None = Query(
        default=None,
        description="Optional user email for smart already-connected check.",
    ),
):
    if oid and not provider:
        raise HTTPException(
            status_code=400,
            detail="Query parameter 'provider' is required when 'oid' is set.",
        )

    email = (user_email or "").strip().lower()
    if email:
        user = db.query(User).filter(User.email == email).first()
        if user:
            provider_key = (provider or "").strip().lower()
            if provider_key in {"gmail", "drive", "google"}:
                providers = [provider_key]
            else:
                providers = ["gmail", "drive", "google"]

            existing_conn = (
                db.query(UserConnection)
                .filter(
                    UserConnection.user_id == user.id,
                    UserConnection.provider.in_(providers),
                    UserConnection.refresh_token.is_not(None),
                    UserConnection.refresh_token != "",
                )
                .order_by(UserConnection.id.desc())
                .first()
            )
            if existing_conn:
                return {"auth_url": None, "already_connected": True}

    try:
        state = oauth_service.build_google_oauth_state(provider, oid)
        url = await oauth_service.get_google_auth_url(
            redirect_uri, provider=provider, state=state
        )
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"auth_url": url, "already_connected": False}


@router.post("/google/callback")
async def google_callback(
    req: AuthCodeRequest, db: Annotated[Session, Depends(get_db)]
):
    try:
        # If provider is not specified in the body, try to infer it or default to gmail.
        provider = (req.provider or "gmail").strip().lower()
        result = await oauth_service.exchange_google_code(
            req.code, req.redirect_uri, db, provider=provider
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/slack/url")
async def slack_url(redirect_uri: str, user_email: str | None = None):
    """``user_email`` is sent as OAuth ``state`` and returned on GET ``/oauth/slack/callback``."""
    url = await oauth_service.get_slack_auth_url(redirect_uri, state=user_email)
    return {"auth_url": url}


@router.get("/microsoft/url")
async def microsoft_url(
    redirect_uri: str,
    db: Annotated[Session, Depends(get_db)],
    oid: str | None = Query(
        default=None,
        description="Optional project oid encoded in OAuth state.",
    ),
    user_email: str | None = Query(
        default=None,
        description="Optional user email encoded in OAuth state for callback token binding.",
    ),
):
    email = (user_email or "").strip().lower()
    if email and not email.endswith("@relanto.ai"):
        raise HTTPException(
            status_code=403,
            detail="Unauthorized: Only @relanto.ai accounts are permitted.",
        )
    if email:
        user = db.query(User).filter(User.email == email).first()
        if user:
            existing_conn = (
                db.query(UserConnection)
                .filter(
                    UserConnection.user_id == user.id,
                    UserConnection.provider == "onedrive",
                    UserConnection.refresh_token.is_not(None),
                    UserConnection.refresh_token != "",
                )
                .order_by(UserConnection.id.desc())
                .first()
            )
            if existing_conn:
                return {"auth_url": None, "already_connected": True}

    state = _build_microsoft_oauth_state(oid=oid, user_email=user_email)
    try:
        url = await oauth_service.get_microsoft_auth_url(redirect_uri, state=state)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"auth_url": url, "already_connected": False}


@router.post("/slack/callback")
async def slack_callback(req: AuthCodeRequest, db: Annotated[Session, Depends(get_db)]):
    if not req.user_email:
        raise HTTPException(
            status_code=400, detail="user_email required to attach slack token."
        )
    try:
        result = await oauth_service.exchange_slack_code(
            req.code, req.redirect_uri, db, req.user_email
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/microsoft/callback")
async def microsoft_callback(req: AuthCodeRequest, db: Annotated[Session, Depends(get_db)]):
    if not req.user_email:
        raise HTTPException(
            status_code=400, detail="user_email required to attach microsoft token."
        )
    try:
        return await oauth_service.exchange_microsoft_code(
            req.code, req.redirect_uri, db, req.user_email
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@external_router.get("/oauth/microsoft/callback")
async def microsoft_oauth_browser_callback(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    if error:
        return JSONResponse({"ok": False, "error": error}, status_code=400)
    if not code:
        return JSONResponse({"ok": False, "error": "missing code"}, status_code=400)

    oid_from_state, user_email = _parse_microsoft_oauth_state(state)
    normalized_oid: str | None = None
    if oid_from_state:
        try:
            normalized_oid = normalize_opportunity_oid(oid_from_state)
        except ValueError:
            normalized_oid = None
    if not user_email:
        return JSONResponse(
            {
                "ok": False,
                "error": (
                    "missing state (user_email). Start OAuth with "
                    "/auth/microsoft/url?redirect_uri=ENCODED_URL&user_email=you@company.com"
                ),
            },
            status_code=400,
        )
    if not user_email.endswith("@relanto.ai"):
        return JSONResponse(
            {
                "ok": False,
                "error": "Unauthorized: Only @relanto.ai accounts are permitted.",
            },
            status_code=403,
        )

    forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    path = request.url.path
    if not path.startswith("/api/"):
        path = f"/api{path}"
    redirect_uri = f"{forwarded_proto}://{request.url.netloc}{path}"
    try:
        await oauth_service.exchange_microsoft_code(code, redirect_uri, db, user_email)
    except ValueError as exc:
        logger.warning("Microsoft OAuth exchange failed: {}", exc)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)

    settings = get_settings()
    frontend_base = (settings.app.frontend_app_url or "").strip().rstrip("/")
    if normalized_oid:
        return RedirectResponse(
            url=f"{frontend_base}/dashboard/opportunities/{normalized_oid}?connected=onedrive",
            status_code=302,
        )
    return RedirectResponse(url=f"{frontend_base}/dashboard?connected=onedrive", status_code=302)


@external_router.get("/oauth/slack/callback")
async def slack_oauth_browser_callback(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    """Browser redirect endpoint for Slack OAuth (GET ?code=&state=)."""
    if error:
        return JSONResponse({"ok": False, "error": error}, status_code=400)
    if not code:
        return JSONResponse({"ok": False, "error": "missing code"}, status_code=400)
    user_email = (state or "").strip()
    if not user_email:
        return JSONResponse(
            {
                "ok": False,
                "error": (
                    "missing state (user_email). Start OAuth with "
                    "/auth/slack/url?redirect_uri=ENCODED_URL&user_email=you@company.com"
                ),
            },
            status_code=400,
        )
    forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    path = request.url.path
    if not path.startswith("/api/"):
        path = f"/api{path}"
    redirect_uri = f"{forwarded_proto}://{request.url.netloc}{path}"
    try:
        result = await oauth_service.exchange_slack_code(code, redirect_uri, db, user_email)
        return JSONResponse({"ok": True, **result})
    except ValueError as exc:
        logger.warning("Slack OAuth exchange failed: {}", exc)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


class RegisterRequest(BaseModel):
    name: str | None = None


def _sync_users_id_sequence(db: Session) -> None:
    """Best-effort: align users.id sequence to MAX(id)."""
    seq_name = db.execute(text("SELECT pg_get_serial_sequence('users', 'id') AS seq")).scalar()
    if not seq_name:
        return
    db.execute(
        text(
            """
            SELECT setval(
                :seq::regclass,
                (SELECT COALESCE(MAX(id), 1) FROM users)
            )
            """
        ),
        {"seq": str(seq_name)},
    )


@external_router.post("/api/auth/register")
async def register(
    request: Request,
    body: RegisterRequest,
    db: Annotated[Session, Depends(get_db)],
):
    token = get_bearer_token(request)
    decoded = verify_firebase_token(token)

    uid = ((decoded.get("uid") or decoded.get("sub") or decoded.get("user_id") or "").strip())
    if not uid:
        raise HTTPException(status_code=401, detail="Invalid token: missing uid.")

    email_raw = decoded.get("email")
    email = (email_raw or "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Token is missing email.")

    existing = db.query(User).filter(User.firebase_uid == uid).first()
    if existing:
        return {
            "ok": True,
            "user": {
                "id": existing.id,
                "firebase_uid": existing.firebase_uid,
                "email": existing.email,
                "name": existing.name,
                "roles_assigned": getattr(existing, "roles_assigned", None),
            },
        }

    # If the user exists by email, link firebase_uid (if empty) instead of duplicating rows.
    by_email = db.query(User).filter(func.lower(User.email) == email).first()
    if by_email:
        linked = (by_email.firebase_uid or "").strip()
        if linked and linked != uid:
            if not bool(decoded.get("email_verified")):
                raise HTTPException(
                    status_code=403,
                    detail=(
                        "This email is linked to a different sign-in. "
                        "Verify the email on the Firebase account before registering."
                    ),
                )

        if not linked or linked != uid:
            by_email.firebase_uid = uid
            if body.name and not (by_email.name or "").strip():
                by_email.name = body.name
            db.commit()
            db.refresh(by_email)
        return {
            "ok": True,
            "user": {
                "id": by_email.id,
                "firebase_uid": by_email.firebase_uid,
                "email": by_email.email,
                "name": by_email.name,
                "roles_assigned": getattr(by_email, "roles_assigned", None),
            },
        }

    # Insert a new DB user row. RBAC uses users.roles_assigned; do not touch legacy users.role.
    insert_sql = text(
        """
        INSERT INTO users (firebase_uid, email, name, roles_assigned)
        VALUES (:firebase_uid, :email, :name, :roles_assigned)
        ON CONFLICT (email) DO UPDATE
          SET firebase_uid = EXCLUDED.firebase_uid,
              name = COALESCE(users.name, EXCLUDED.name)
        RETURNING id, firebase_uid, email, name, roles_assigned
        """
    )
    insert_params = {
        "firebase_uid": uid,
        "email": email,
        "name": body.name,
        "roles_assigned": None,
    }

    try:
        created = db.execute(insert_sql, insert_params).mappings().first()
        db.commit()
    except DBAPIError as exc:
        db.rollback()
        pg = getattr(exc, "orig", None)
        code = getattr(pg, "args", None)
        pg_code = None
        if isinstance(code, tuple) and code and isinstance(code[0], dict):
            pg_code = code[0].get("C")
        if pg_code == "23505" and "users_pkey" in str(exc):
            _sync_users_id_sequence(db)
            created = db.execute(insert_sql, insert_params).mappings().first()
            db.commit()
        else:
            raise

    if not created:
        raise HTTPException(status_code=500, detail="Failed to register user.")

    return {"ok": True, "user": dict(created)}
