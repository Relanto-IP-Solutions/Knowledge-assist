"""Slack discovery/connect using universal bot token from settings."""

from __future__ import annotations

from typing import Annotated

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

from configs.settings import get_settings
from src.services.database_manager.models.auth_models import Opportunity, OpportunitySource, User
from src.services.database_manager.opportunity_state import STATUS_DISCOVERED
from src.services.database_manager.orm import get_db, get_engine
from src.services.storage import Storage
from src.services.plugins.slack_plugin import _oid_to_slack_channel_prefix, sync_slack_source
from src.utils.logger import get_logger
from src.utils.opportunity_id import find_opportunity_oid, normalize_opportunity_oid


logger = get_logger(__name__)
router = APIRouter(prefix="/slack", tags=["slack"])
integrations_slack_router = APIRouter(prefix="/integrations/slack", tags=["slack"])
SLACK_API_BASE = "https://slack.com/api"


def _slack_bot_token() -> str:
    token = (get_settings().slack.bot_token or "").strip()
    if not token:
        raise HTTPException(
            status_code=503,
            detail="SLACK_BOT_TOKEN is not configured.",
        )
    return token


def _default_owner(db: Session) -> User:
    email = (get_settings().slack.slack_connector_user_email or "").strip().lower()
    if email:
        u = db.query(User).filter(User.email == email).first()
        if u:
            return u
    u = db.query(User).order_by(User.id.asc()).first()
    if not u:
        raise HTTPException(
            status_code=400,
            detail="No users available to assign discovered Slack opportunities.",
        )
    return u

def _list_all_channels(token: str) -> list[dict]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    out: list[dict] = []
    cursor = None
    with httpx.Client(timeout=60.0) as client:
        while True:
            params: dict = {
                "types": "public_channel,private_channel",
                "exclude_archived": "true",
                "limit": 200,
            }
            if cursor:
                params["cursor"] = cursor
            r = client.get(
                f"{SLACK_API_BASE}/conversations.list", headers=headers, params=params
            )
            if r.status_code != 200:
                raise HTTPException(
                    status_code=502,
                    detail=f"Slack conversations.list HTTP {r.status_code}",
                )
            data = r.json()
            if not data.get("ok"):
                err = str(data.get("error") or "unknown")
                if err in {"not_in_channel", "bot_not_in_channel"}:
                    raise HTTPException(
                        status_code=403,
                        detail=(
                            "Slack bot is not in required channel(s). Add the bot to "
                            "channels and retry."
                        ),
                    )
                if err == "missing_scope":
                    raise HTTPException(
                        status_code=403,
                        detail=(
                            "Slack token missing required scopes. Re-authorize Slack app "
                            "with channels/groups read+history scopes."
                        ),
                    )
                raise HTTPException(
                    status_code=502,
                    detail=f"Slack API error: {err}",
                )
            out.extend(data.get("channels") or [])
            cursor = (data.get("response_metadata") or {}).get("next_cursor")
            if not cursor:
                break
    return out


def _oid_from_channel_name(name: str) -> str | None:
    """Return canonical opportunities.opportunity_id if the channel name contains an opportunity id token."""
    return find_opportunity_oid(name or "")


def _channel_matches_oid_plugin(name: str, oid: str) -> bool:
    """Same filter as slack_plugin: name must contain alphanumeric oid prefix."""
    prefix = _oid_to_slack_channel_prefix(oid)
    if not prefix:
        return False
    return prefix in (name or "").lower()


class SlackDiscoverResponse(BaseModel):
    channels_total: int
    channels_matched: int
    opportunities_created: int
    opportunity_sources_created: int
    skipped: list[str] = Field(
        default_factory=list,
        description="Channel names with no opportunity id token, or name does not match plugin prefix for parsed id.",
    )


class SlackDiscoverStartRequest(BaseModel):
    redirect_uri: str | None = Field(default=None)
    return_url: str | None = Field(default=None)
    user_email: str | None = Field(default=None)
    user_id: int | None = Field(default=None)


class SlackConnectRequest(BaseModel):
    # Accepted for compatibility; no OAuth fields required with bot-token mode.
    note: str | None = Field(default=None)


def discover_slack_channels(db: Session) -> SlackDiscoverResponse:
    """List Slack channels with bot token; upsert opportunities + pending slack sources."""
    token = _slack_bot_token()
    owner = _default_owner(db)

    channels = _list_all_channels(token)
    created_opps = 0
    created_sources = 0
    matched = 0
    skipped: list[str] = []

    seen_oids: set[str] = set()

    for ch in channels:
        name = (ch.get("name") or "").strip()
        oid = _oid_from_channel_name(name)
        if not oid:
            if name:
                skipped.append(name)
            continue
        if not _channel_matches_oid_plugin(name, oid):
            skipped.append(name)
            continue

        matched += 1
        if oid in seen_oids:
            continue
        seen_oids.add(oid)

        # Ensure canonical storage in DB even if token variants are used.
        oid = normalize_opportunity_oid(oid)
        opp = db.query(Opportunity).filter(Opportunity.opportunity_id == oid).first()
        if not opp:
            opp = Opportunity(
                opportunity_id=oid,
                name=name or oid,
                owner_id=owner.id,
                status=STATUS_DISCOVERED,
                total_documents=0,
                processed_documents=0,
            )
            db.add(opp)
            db.flush()
            created_opps += 1
            logger.info("Slack discover created opportunity oid={} id={}", oid, opp.id)
        else:
            if not opp.owner_id:
                opp.owner_id = owner.id
            if not (opp.name or "").strip():
                opp.name = name or oid

        src = (
            db
            .query(OpportunitySource)
            .filter(
                OpportunitySource.opportunity_id == opp.id,
                OpportunitySource.source_type == "slack",
            )
            .first()
        )
        if not src:
            db.add(
                OpportunitySource(
                    opportunity_id=opp.id,
                    source_type="slack",
                    status="PENDING_AUTHORIZATION",
                )
            )
            created_sources += 1
            logger.info(
                "Slack discover created slack source for opportunity_id={}", opp.id
            )

    db.commit()

    return SlackDiscoverResponse(
        channels_total=len(channels),
        channels_matched=matched,
        opportunities_created=created_opps,
        opportunity_sources_created=created_sources,
        skipped=skipped,
    )


def discover_slack_channels_impl(db: Session) -> SlackDiscoverResponse:
    """Non-HTTP helper for orchestration (same as POST /slack/discover)."""
    return discover_slack_channels(db=db)


@router.post("/discover", response_model=SlackDiscoverResponse)
def discover_slack_channels_endpoint(db: Annotated[Session, Depends(get_db)]):
    """Discover channels whose names include an opportunity id token; upsert DB rows for Slack sync.

    After this, run ``POST /sync/trigger`` or ``POST /sync/run`` to push messages to GCS.
    """
    return discover_slack_channels(db)


def _ensure_slack_source(db: Session, opp: Opportunity) -> OpportunitySource:
    source = (
        db.query(OpportunitySource)
        .filter(
            OpportunitySource.opportunity_id == opp.id,
            OpportunitySource.source_type == "slack",
        )
        .first()
    )
    if source:
        return source
    source = OpportunitySource(
        opportunity_id=opp.id,
        source_type="slack",
        status="PENDING_AUTHORIZATION",
    )
    db.add(source)
    db.flush()
    return source


async def _run_slack_sync_background(oid: str) -> None:
    with Session(get_engine()) as db:
        opp = db.query(Opportunity).filter(Opportunity.opportunity_id == oid).first()
        if not opp:
            logger.warning("Slack sync_start skipped: oid={} not found", oid)
            return
        source = (
            db.query(OpportunitySource)
            .options(
                joinedload(OpportunitySource.opportunity).joinedload(Opportunity.owner)
            )
            .filter(
                OpportunitySource.opportunity_id == opp.id,
                OpportunitySource.source_type == "slack",
            )
            .first()
        )
        if not source:
            logger.warning("Slack sync_start skipped: no source row for oid={}", oid)
            return
        await sync_slack_source(db, source)


@integrations_slack_router.post("/discover")
async def slack_discover_start_integrations(
    body: SlackDiscoverStartRequest,
    db: Annotated[Session, Depends(get_db)],
):
    """Service-account mode: run discovery immediately when bot token is configured."""
    _ = body  # compatibility payload; ignored in bot-token mode
    result = discover_slack_channels(db)
    logger.info("Slack discover_start: action=discover result=completed")
    return {
        "requires_oauth": False,
        "message": "Slack bot token active; discovery completed.",
        "discovery_result": result.model_dump(),
    }


@integrations_slack_router.post("/authorize/{oid}")
async def slack_connect_integrations(
    oid: str,
    body: SlackConnectRequest,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
):
    """Service-account mode: activate source and start sync immediately."""
    _ = body
    _slack_bot_token()
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
    source = _ensure_slack_source(db, opp)
    source.status = "ACTIVE"
    db.commit()
    logger.info(
        "Slack connect_start: action=connect oid={} result=activated",
        normalized_oid,
    )
    background_tasks.add_task(_run_slack_sync_background, normalized_oid)
    return {
        "requires_oauth": False,
        "message": "Slack bot token active; sync started.",
        "oid": normalized_oid,
        "status": "ACTIVE",
        "sync_started": True,
    }


@integrations_slack_router.get("/authorize-info/{oid}")
def slack_connect_info_integrations(
    oid: str,
    db: Annotated[Session, Depends(get_db)],
):
    """Return frontend Slack status based on bot token + source state."""
    _slack_bot_token()
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
        db.query(OpportunitySource)
        .filter(
            OpportunitySource.opportunity_id == opp.id,
            OpportunitySource.source_type == "slack",
        )
        .first()
    )
    if source and (source.status or "").strip().upper() == "ACTIVE":
        return {
            "oid": normalized_oid,
            "status": "ACTIVE",
            "requires_oauth": False,
            "has_required_scopes": True,
            "message": "Slack bot token is active and this opportunity is connected.",
            "activation_warning": (
                "Please Note: This connection is currently active. KnowledgeAssist is "
                "automatically ingesting messages for this channel."
            ),
        }
    return {
        "oid": normalized_oid,
        "status": "DISCOVERED",
        "requires_oauth": False,
        "has_required_scopes": True,
        "message": "Slack bot token is active; connect to start sync for this opportunity.",
        "activation_warning": (
            "Privacy Note: Activating this data source allows KnowledgeAssist to read, store, "
            "and analyze all historical and future messages inside this channel. Please ensure "
            "no highly sensitive personal information is present before syncing."
        ),
    }


@integrations_slack_router.get("/metrics/{oid}")
def slack_metrics_for_opportunity(
    oid: str,
    db: Annotated[Session, Depends(get_db)],
):
    """Return Slack ingestion metrics for one opportunity."""
    _slack_bot_token()
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
        db.query(OpportunitySource)
        .filter(
            OpportunitySource.opportunity_id == opp.id,
            OpportunitySource.source_type == "slack",
        )
        .first()
    )
    if not source:
        raise HTTPException(
            status_code=404,
            detail=f"No slack opportunity source found for oid '{normalized_oid}'.",
        )

    storage = Storage()
    slack_objects = storage.list_objects("raw", normalized_oid, "slack")
    total_files = len(slack_objects)

    raw_status = source.status
    if raw_status is None or (isinstance(raw_status, str) and not raw_status.strip()):
        status_out = "DISCOVERED"
    else:
        status_out = raw_status.strip() if isinstance(raw_status, str) else str(raw_status)

    last_synced_out: str | None = None
    if source.last_synced_at is not None:
        last_synced_out = source.last_synced_at.isoformat()

    return {
        "total_files": total_files,
        "status": status_out,
        "last_synced_at": last_synced_out,
        "sync_checkpoint": source.sync_checkpoint,
    }
