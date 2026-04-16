"""Zoom routes: webhook receiver + discovery upsert.

- Webhook endpoint remains: POST /integrations/zoom/webhook
- Discovery endpoint: POST /zoom/discover
"""

from __future__ import annotations

import asyncio
import json
from datetime import date, timedelta
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from configs.settings import get_settings
from src.services.database_manager.models.auth_models import (
    Opportunity,
    OpportunitySource,
    User,
)
from src.services.database_manager.opportunity_state import STATUS_DISCOVERED
from src.services.database_manager.orm import get_db
from src.services.storage import Storage
from src.services.zoom.client import ZoomClient
from src.services.zoom.sync_service import ZoomSyncService
from src.services.zoom.webhook_handler import ZoomWebhookHandler
from src.utils.logger import get_logger
from src.utils.opportunity_id import find_opportunity_oid, normalize_opportunity_oid


logger = get_logger(__name__)

router = APIRouter(tags=["zoom"])


@router.get("/integrations/zoom/connect-info/{oid}")
def zoom_connect_info(
    oid: str,
    db: Annotated[Session, Depends(get_db)],
):
    """Return permission/warning metadata and current Zoom connection status for an OID."""
    try:
        normalized_oid = normalize_opportunity_oid(oid)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    opp = db.query(Opportunity).filter(Opportunity.opportunity_id == normalized_oid).first()
    if not opp:
        raise HTTPException(
            status_code=404,
            detail=f"Opportunity not found for '{normalized_oid}'.",
        )

    source = (
        db
        .query(OpportunitySource)
        .filter(
            OpportunitySource.opportunity_id == opp.id,
            OpportunitySource.source_type == "zoom",
        )
        .first()
    )
    if not source:
        raise HTTPException(
            status_code=404,
            detail=f"No zoom opportunity source found for '{normalized_oid}'.",
        )

    return {
        "Please Note": (
            "This connection is currently active. Knowledge Assist is automatically "
            "ingesting recorded meetings for this opportunity using account-level permissions."
            if source.status == "ACTIVE"
            else (
                "Privacy Note: Turning on this connection allows Knowledge Assist to "
                "automatically ingest recorded meetings for this project (OID) using "
                "account-level permissions."
            )
        ),
        "status": source.status,
    }


def _get_zoom_connector_user(db: Session) -> User:
    """Pick the user who will own opportunities created via Zoom discovery."""
    email = (get_settings().zoom.zoom_connector_user_email or "").strip().lower()
    q = db.query(User)
    if email:
        u = q.filter(User.email == email).first()
        if not u:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"ZOOM_CONNECTOR_USER_EMAIL is set to {email!r} but no user row was found."
                ),
            )
        return u
    u = q.order_by(User.id.asc()).first()
    if not u:
        raise HTTPException(
            status_code=400,
            detail="No users found. Create at least one users row before Zoom discovery.",
        )
    return u


class ZoomAuthorizeBody(BaseModel):
    """Toggle Zoom sync for an opportunity."""

    active: bool


class ZoomUserScanSummary(BaseModel):
    email: str
    recordings_scanned: int
    recordings_with_oid: int
    opportunities_created: int
    opportunity_sources_created: int


class ZoomDiscoverResponse(BaseModel):
    days_lookback: int
    recordings_scanned: int
    recordings_with_oid: int
    opportunities_created: int
    opportunity_sources_created: int
    skipped_topics: list[str] = Field(
        default_factory=list,
        description="Meeting topics skipped (no opportunity id token like 'oid1234').",
    )
    users_scanned: list[ZoomUserScanSummary] = Field(
        default_factory=list,
        description="Breakdown of discovery results for each Zoom user scanned.",
    )


def _ensure_user_for_zoom_host(
    db: Session, host_email: str | None, fallback_user: User
) -> User:
    """Resolve or create local user for a Zoom host email."""
    email = (host_email or "").strip().lower()
    if not email:
        return fallback_user
    user = db.query(User).filter(User.email == email).first()
    if user:
        return user
    user = User(email=email, name=email.split("@")[0] if "@" in email else None)
    db.add(user)
    db.flush()
    return user


async def _list_recordings_by_user(days_lookback: int) -> list[tuple[str, list[dict[str, Any]]]]:
    """List cloud recordings for all users in the account (last N days), grouped by user email."""
    out_tuple: list[tuple[str, list[dict[str, Any]]]] = []
    # Zoom recordings list API accepts dates (YYYY-MM-DD) with max range limits.
    to_d = date.today()
    from_d = to_d - timedelta(days=days_lookback)
    acc = (get_settings().zoom.account_id or "").strip()
    cid = (get_settings().zoom.client_id or "").strip()
    csec = (get_settings().zoom.client_secret or "").strip()
    if not acc or not cid or not csec:
        raise HTTPException(
            status_code=400,
            detail=(
                "Zoom Server-to-Server OAuth is not configured. Set ZOOM_ACCOUNT_ID, "
                "ZOOM_CLIENT_ID, and ZOOM_CLIENT_SECRET (see configs/secrets/.env.example). "
                "Account ID is required for grant_type=account_credentials."
            ),
        )
    client = ZoomClient()
    users = await client.list_users()
    if not users:
        return out_tuple

    semaphore = asyncio.Semaphore(8)

    async def _list_for_user(u: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
        uid = (str(u.get("id") or "")).strip() or (u.get("email") or "").strip()
        email = u.get("email") or uid
        if not uid:
            return email, []
        async with semaphore:
            try:
                meetings = await client.list_recordings(
                    from_date=from_d.isoformat(),
                    to_date=to_d.isoformat(),
                    user_id=uid,
                )
            except Exception as exc:
                logger.warning(f"Zoom discover: failed listing recordings for user {email}: {exc}")
                return email, []
        for m in meetings:
            if isinstance(m, dict):
                m.setdefault("host_email", email)
        return email, meetings

    chunks = await asyncio.gather(
        *(_list_for_user(u) for u in users if isinstance(u, dict)),
        return_exceptions=True,
    )

    for c in chunks:
        if isinstance(c, Exception):
            logger.warning("Zoom discover: exception in gather: {}", c)
            continue
        email, meetings = c
        out_tuple.append((email, meetings))

    return out_tuple


@router.post("/zoom/discover", response_model=ZoomDiscoverResponse)
async def discover_zoom_recordings(
    db: Annotated[Session, Depends(get_db)],
    days_lookback: int = 14,
):
    """Discover Zoom recordings whose meeting topic includes an opportunity id and upsert DB rows.

    - Extracts canonical opportunity id (oid1234) from meeting topic.
    - Upserts opportunities(opportunity_id, name, owner_id)
    - Upserts opportunity_sources(opportunity_id, source_type='zoom')
    """
    days = max(1, min(int(days_lookback), 90))
    connector = _get_zoom_connector_user(db)

    try:
        grouped_recordings = await _list_recordings_by_user(days)
    except HTTPException:
        raise
    except httpx.HTTPStatusError as e:
        body = (e.response.text or "")[:800]
        logger.exception(
            "Zoom discover HTTP error: {} {} — {}",
            e.response.status_code,
            e.request.url,
            body,
        )
        scope_hint = ""
        if "scopes" in body or "scope" in body.lower():
            scope_hint = (
                " In Zoom Marketplace → your Server-to-Server OAuth app → Scopes, add "
                "Recording: e.g. ``cloud_recording:read:list_user_recordings`` (and admin "
                "variant if listing all users). Re-authorize the app after changing scopes."
            )
        raise HTTPException(
            status_code=502,
            detail=(
                f"Zoom API or OAuth token request failed ({e.response.status_code}). "
                f"Check ZOOM_ACCOUNT_ID, ZOOM_CLIENT_ID, ZOOM_CLIENT_SECRET.{scope_hint} "
                f"Response: {body}"
            ),
        ) from e
    except Exception as e:
        logger.exception("Zoom discover failed: {}", e)
        raise HTTPException(
            status_code=502,
            detail=f"Zoom discovery failed: {e!s}",
        ) from e

    created_opps = 0
    created_sources = 0
    matched = 0
    skipped: list[str] = []
    seen_oids: set[str] = set()

    total_scanned = 0
    users_scanned_summaries = []

    for email, user_recordings in grouped_recordings:
        user_scanned = 0
        user_matched = 0
        user_opps_created = 0
        user_sources_created = 0

        for rec in user_recordings:
            user_scanned += 1
            total_scanned += 1
            topic = (rec.get("topic") or "").strip()
            oid = find_opportunity_oid(topic)
            if not oid:
                if topic:
                    skipped.append(topic)
                continue
            oid = normalize_opportunity_oid(oid)
            user_matched += 1
            matched += 1
            if oid in seen_oids:
                continue
            seen_oids.add(oid)

            opp = db.query(Opportunity).filter(Opportunity.opportunity_id == oid).first()
            owner = _ensure_user_for_zoom_host(db, rec.get("host_email"), connector)
            if not opp:
                opp = Opportunity(
                    opportunity_id=oid,
                    name=topic or oid,
                    owner_id=owner.id,
                    status=STATUS_DISCOVERED,
                    total_documents=0,
                    processed_documents=0,
                )
                db.add(opp)
                db.flush()
                user_opps_created += 1
                created_opps += 1
            else:
                if not opp.owner_id:
                    opp.owner_id = owner.id
                if not (opp.name or "").strip():
                    opp.name = topic or oid

            src = (
                db
                .query(OpportunitySource)
                .filter(
                    OpportunitySource.opportunity_id == opp.id,
                    OpportunitySource.source_type == "zoom",
                )
                .first()
            )
            if not src:
                db.add(
                    OpportunitySource(
                        opportunity_id=opp.id,
                        source_type="zoom",
                        status="PENDING_AUTHORIZATION",
                    )
                )
                user_sources_created += 1
                created_sources += 1

        users_scanned_summaries.append(
            ZoomUserScanSummary(
                email=email,
                recordings_scanned=user_scanned,
                recordings_with_oid=user_matched,
                opportunities_created=user_opps_created,
                opportunity_sources_created=user_sources_created,
            )
        )

    db.commit()

    logger.info(
        "Zoom discover: DB commit — connector={} users_scanned={} recordings_scanned={} recordings_with_oid={} "
        "opportunities_created={} opportunity_sources_created={}",
        connector.email,
        len(users_scanned_summaries),
        total_scanned,
        matched,
        created_opps,
        created_sources,
    )

    return ZoomDiscoverResponse(
        days_lookback=days,
        recordings_scanned=total_scanned,
        recordings_with_oid=matched,
        opportunities_created=created_opps,
        opportunity_sources_created=created_sources,
        skipped_topics=skipped,
        users_scanned=users_scanned_summaries,
    )


async def _run_zoom_sync_background(oid: str) -> None:
    await ZoomSyncService().sync_opportunity(oid)


@router.post("/integrations/zoom/authorize/{oid}")
async def authorize_zoom_for_opportunity(
    oid: str,
    body: ZoomAuthorizeBody,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
):
    """Enable or disable Zoom sync for an opportunity; when enabling, kick off historical sync."""
    try:
        normalized_oid = normalize_opportunity_oid(oid)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    opp = db.query(Opportunity).filter(Opportunity.opportunity_id == normalized_oid).first()
    if not opp:
        raise HTTPException(
            status_code=404,
            detail=f"Opportunity not found for '{normalized_oid}'.",
        )

    source = (
        db
        .query(OpportunitySource)
        .filter(
            OpportunitySource.opportunity_id == opp.id,
            OpportunitySource.source_type == "zoom",
        )
        .first()
    )
    if not source:
        raise HTTPException(
            status_code=404,
            detail=f"No zoom opportunity source found for '{normalized_oid}'.",
        )

    if body.active:
        source.status = "ACTIVE"
        db.commit()
        background_tasks.add_task(_run_zoom_sync_background, normalized_oid)
        return {"message": "Zoom sync initialized in the background."}

    source.status = "INACTIVE"
    db.commit()
    return {"message": "Zoom sync deactivated."}


@router.get("/integrations/zoom/metrics/{oid}")
def zoom_metrics_for_opportunity(
    oid: str,
    db: Annotated[Session, Depends(get_db)],
):
    """Return Zoom ingestion metrics for one opportunity."""
    try:
        normalized_oid = normalize_opportunity_oid(oid)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    opp = db.query(Opportunity).filter(Opportunity.opportunity_id == normalized_oid).first()
    if not opp:
        raise HTTPException(
            status_code=404,
            detail=f"Opportunity not found for '{normalized_oid}'.",
        )

    source = (
        db
        .query(OpportunitySource)
        .filter(
            OpportunitySource.opportunity_id == opp.id,
            OpportunitySource.source_type == "zoom",
        )
        .first()
    )
    if not source:
        return {
            "total_files": 0,
            "vtt_count": 0,
            "status": "NOT_CONNECTED",
            "message": f"Zoom not connected for '{normalized_oid}'",
        }

    storage = Storage()
    zoom_objects = storage.list_objects("raw", normalized_oid, "zoom")
    total_files = len(zoom_objects)
    vtt_count = sum(1 for name in zoom_objects if name.lower().endswith(".vtt"))

    raw_status = source.status
    if raw_status is None or (
        isinstance(raw_status, str) and not raw_status.strip()
    ):
        status_out = "DISCOVERED"
    else:
        status_out = raw_status.strip() if isinstance(raw_status, str) else str(raw_status)

    last_synced_out: str | None = None
    if source.last_synced_at is not None:
        last_synced_out = source.last_synced_at.isoformat()

    return {
        "total_files": total_files,
        "vtt_count": vtt_count,
        "status": status_out,
        "last_synced_at": last_synced_out,
    }


@router.post("/integrations/zoom/webhook")
async def zoom_webhook(request: Request, background_tasks: BackgroundTasks):
    """Zoom Webhook Listener: handle url_verification and recording events."""
    try:
        # Read raw body once for signature verification and JSON parsing.
        raw = await request.body()
        body = json.loads(raw.decode("utf-8"))
    except Exception:
        return JSONResponse(content={"error": "Invalid JSON body"}, status_code=400)

    handler = ZoomWebhookHandler()
    event = body.get("event")
    logger.info("Received Zoom webhook event: {}", event)

    # 1. URL Verification Challenge (Setup phase)
    if event == "endpoint.url_validation":
        plain_token = body.get("payload", {}).get("plainToken")
        if not plain_token:
            return JSONResponse(
                content={"error": "Missing plainToken"}, status_code=400
            )
        encrypted_token = handler.handle_url_verification(plain_token)
        return {"plainToken": plain_token, "encryptedToken": encrypted_token}

    # 2. Security: Verify Signature for other events
    signature = request.headers.get("x-zm-signature")
    timestamp = request.headers.get("x-zm-request-timestamp")
    if signature and timestamp:
        message = f"v0:{timestamp}:{raw.decode('utf-8', errors='replace')}"
        if not handler.verify_signature(message, signature):
            return JSONResponse(content={"error": "Invalid signature"}, status_code=401)

    # 3. Process the Event (e.g., recording.completed)
    payload = body.get("payload", {})
    download_token = body.get("download_token")
    background_tasks.add_task(handler.process_event, event, payload, download_token)

    return {"status": "received", "queued": True}
