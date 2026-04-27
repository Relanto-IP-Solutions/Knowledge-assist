"""Slack discovery/connect using universal bot token from settings."""

from __future__ import annotations

import re
from typing import Annotated

import httpx
from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload

from configs.settings import get_settings
from src.services.database_manager.models.auth_models import Opportunity, OpportunitySource, User
from src.services.database_manager.opportunity_state import STATUS_DISCOVERED
from src.services.database_manager.orm import get_db, get_engine
from src.services.storage import Storage
from src.services.plugins.slack_plugin import sync_slack_source
from src.utils.logger import get_logger
from src.utils.opportunity_id import (
    find_opportunity_oid,
    gcs_opportunity_prefix,
    normalize_opportunity_oid,
)


logger = get_logger(__name__)
router = APIRouter(prefix="/slack", tags=["slack"])
integrations_slack_router = APIRouter(prefix="/integrations/slack", tags=["slack"])
SLACK_API_BASE = "https://slack.com/api"
STRICT_OID_IN_CHANNEL_RE = re.compile(r"(?:^|[^a-z0-9])(oid\d+)(?=[^a-z0-9]|$)", re.IGNORECASE)


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
    """Return canonical opportunities.opportunity_id when strict oid#### token is present."""
    raw_name = (name or "").strip().lower()
    if not raw_name:
        return None
    match = STRICT_OID_IN_CHANNEL_RE.search(raw_name)
    if not match:
        return None
    return find_opportunity_oid(match.group(1))


def _channel_matches_oid_plugin(name: str, oid: str) -> bool:
    """Strict matcher: channel must contain exact oid#### token equal to oid."""
    parsed_oid = _oid_from_channel_name(name)
    if not parsed_oid:
        return False
    return parsed_oid == normalize_opportunity_oid(oid)


def _normalize_channel_name(name: str) -> str:
    return (name or "").strip().lower()


def _find_channel_by_exact_name(channels: list[dict], channel_name: str) -> dict | None:
    target = _normalize_channel_name(channel_name)
    if not target:
        return None
    for ch in channels:
        current = _normalize_channel_name(ch.get("name") or "")
        if current == target:
            return ch
    return None


def _create_channel(token: str, channel_name: str) -> dict:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    with httpx.Client(timeout=60.0) as client:
        r = client.post(
            f"{SLACK_API_BASE}/conversations.create",
            headers=headers,
            json={"name": channel_name, "is_private": True},
        )
    if r.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Slack conversations.create HTTP {r.status_code}",
        )
    data = r.json()
    if not data.get("ok"):
        err = str(data.get("error") or "unknown")
        raise HTTPException(status_code=502, detail=f"Slack API error: {err}")
    return data.get("channel") or {}


def _join_channel(token: str, channel_id: str) -> bool:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    with httpx.Client(timeout=30.0) as client:
        r = client.post(
            f"{SLACK_API_BASE}/conversations.join",
            headers=headers,
            json={"channel": channel_id},
        )
    return r.json().get("ok", False)


def _batch_invite_members(token: str, channel_id: str, member_ids: list[str]) -> int:
    unique_ids = sorted({str(m).strip() for m in member_ids if str(m).strip()})
    if not unique_ids:
        return 0
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }

    def try_invite():
        with httpx.Client(timeout=60.0) as client:
            return client.post(
                f"{SLACK_API_BASE}/conversations.invite",
                headers=headers,
                json={"channel": channel_id, "users": ",".join(unique_ids)},
            )

    r = try_invite()
    if r.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Slack conversations.invite HTTP {r.status_code}",
        )
    data = r.json()
    if not data.get("ok"):
        err = str(data.get("error") or "unknown")

        if err == "not_in_channel":
            # Attempt to join and retry
            if _join_channel(token, channel_id):
                r = try_invite()
                data = r.json()
                if data.get("ok"):
                    return len(unique_ids)

            # If still fails or join failed, explain the likely Private Channel issue
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Slack Bot not in channel '{channel_id}'. If this is a PRIVATE channel "
                    "created by another user, please manually invite this bot to the channel first."
                ),
            )

        if err != "already_in_channel":
            raise HTTPException(status_code=502, detail=f"Slack API error: {err}")
    return len(unique_ids)


def _lookup_slack_id_by_email(token: str, email: str) -> str | None:
    normalized_email = (email or "").strip().lower()
    if not normalized_email:
        return None

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    with httpx.Client(timeout=60.0) as client:
        r = client.get(
            f"{SLACK_API_BASE}/users.lookupByEmail",
            headers=headers,
            params={"email": normalized_email},
        )

    if r.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Slack users.lookupByEmail HTTP {r.status_code}",
        )

    data = r.json()
    if not data.get("ok"):
        err = str(data.get("error") or "unknown")
        if err == "users_not_found":
            return None
        raise HTTPException(status_code=502, detail=f"Slack API error: {err}")

    user = data.get("user") or {}
    user_id = (user.get("id") or "").strip()
    return user_id or None


def _get_channel_info(token: str, channel_id: str) -> dict | None:
    cid = (channel_id or "").strip()
    if not cid:
        return None
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    with httpx.Client(timeout=30.0) as client:
        r = client.get(
            f"{SLACK_API_BASE}/conversations.info",
            headers=headers,
            params={"channel": cid},
        )
    if r.status_code != 200:
        return None
    data = r.json()
    if not data.get("ok"):
        return None
    ch = data.get("channel") or {}
    return ch if isinstance(ch, dict) else None


class SlackDiscoverResponse(BaseModel):
    channels_total: int
    channels_matched: int
    opportunities_created: int
    opportunity_sources_created: int
    skipped: list[str] = Field(
        default_factory=list,
        description="Channel names with no opportunity id token, or name does not match plugin prefix for parsed id.",
    )


class SlackMetricsChannelItem(BaseModel):
    """One Slack opportunity source (channel) linked to the project."""

    id: str
    name: str
    last_synced_at: str | None = None


class SlackOpportunityMetricsResponse(BaseModel):
    """Aggregated Slack ingestion metrics; ``total_files`` is across all project Slack sources."""

    total_files: int
    status: str
    last_synced_at: str | None = None
    sync_checkpoint: str | None = None
    channels: list[SlackMetricsChannelItem]


class SlackProfessionalConnectResponse(BaseModel):
    """Synchronous professional ingestion: discovery → ACTIVE → Slack → GCS, with immediate counts."""

    oid: str
    status: str = "ACTIVE"
    total_files: int
    messages_synced: int
    discovery_result: SlackDiscoverResponse
    requires_oauth: bool = False
    message: str = "Slack discovery, activation, and ingestion completed."


class SlackDiscoverStartRequest(BaseModel):
    redirect_uri: str | None = Field(default=None)
    return_url: str | None = Field(default=None)
    user_email: str | None = Field(default=None)
    user_id: int | None = Field(default=None)


class SlackConnectRequest(BaseModel):
    """Bot-token authorize; `active` defaults true so `{}` or omitted body validates."""

    active: bool = Field(default=True)
    note: str | None = Field(default=None)


class SlackOrchestrateRequest(BaseModel):
    custom_channel_name: str | None = Field(default=None)
    team_emails: list[str] = Field(default_factory=list)


class SlackOrchestrateResponse(BaseModel):
    message: str
    oid: str
    opportunity_created: bool
    source_created: bool
    channel_created: bool
    channel_name: str
    channel_id: str
    invited_count: int


def discover_slack_channels(
    db: Session,
    *,
    oid_filter: str | None = None,
) -> SlackDiscoverResponse:
    """List Slack channels with bot token; upsert opportunities + pending slack sources.

    When ``oid_filter`` is set (canonical opportunity id, e.g. ``oid123``), only channels
    whose names parse to that oid are considered. Other channels are ignored (no upserts),
    so discovery side effects are scoped to a single project.
    """
    token = _slack_bot_token()
    owner = _default_owner(db)

    normalized_filter: str | None = None
    if oid_filter is not None:
        trimmed = (oid_filter or "").strip()
        if not trimmed:
            raise ValueError("oid_filter must be non-empty when provided")
        normalized_filter = normalize_opportunity_oid(trimmed)

    channels = _list_all_channels(token)
    created_opps = 0
    created_sources = 0
    matched = 0
    skipped: list[str] = []

    for ch in channels:
        name = (ch.get("name") or "").strip()
        oid = _oid_from_channel_name(name)
        if not oid:
            if not normalized_filter and name:
                skipped.append(name)
            continue

        try:
            oid = normalize_opportunity_oid(oid)
        except ValueError:
            if not normalized_filter and name:
                skipped.append(name)
            continue

        if normalized_filter is not None and oid != normalized_filter:
            continue

        if not _channel_matches_oid_plugin(name, oid):
            if normalized_filter is None or oid == normalized_filter:
                skipped.append(name)
            continue

        matched += 1

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

        channel_id = (ch.get("id") or "").strip()
        if not channel_id:
            logger.debug(
                "Slack discover: matched channel has no id (name={}); skip source row",
                name,
            )
            continue

        src = (
            db.query(OpportunitySource)
            .filter(
                OpportunitySource.opportunity_id == opp.id,
                OpportunitySource.source_type == "slack",
                OpportunitySource.channel_id == channel_id,
            )
            .first()
        )
        if not src:
            unfilled = (
                db.query(OpportunitySource)
                .filter(
                    OpportunitySource.opportunity_id == opp.id,
                    OpportunitySource.source_type == "slack",
                    OpportunitySource.channel_id.is_(None),
                )
                .first()
            )
            if unfilled is not None:
                unfilled.channel_id = channel_id
                logger.info(
                    "Slack discover: backfilled channel_id for opportunity_id={} ch={}",
                    opp.id,
                    channel_id,
                )
            else:
                db.add(
                    OpportunitySource(
                        opportunity_id=opp.id,
                        source_type="slack",
                        channel_id=channel_id,
                        status="PENDING_AUTHORIZATION",
                    )
                )
                created_sources += 1
                logger.info(
                    "Slack discover: created slack source opportunity_id={} channel_id={}",
                    opp.id,
                    channel_id,
                )

    db.commit()

    return SlackDiscoverResponse(
        channels_total=len(channels),
        channels_matched=matched,
        opportunities_created=created_opps,
        opportunity_sources_created=created_sources,
        skipped=skipped,
    )


def discover_slack_channels_impl(
    db: Session,
    *,
    oid_filter: str | None = None,
) -> SlackDiscoverResponse:
    """Non-HTTP helper for orchestration (same as POST /slack/discover when unfiltered)."""
    return discover_slack_channels(db=db, oid_filter=oid_filter)


@router.post("/discover", response_model=SlackDiscoverResponse)
def discover_slack_channels_endpoint(db: Annotated[Session, Depends(get_db)]):
    """Discover channels whose names include an opportunity id token; upsert DB rows for Slack sync.

    After this, run ``POST /sync/trigger`` or ``POST /sync/run`` to push messages to GCS.
    """
    return discover_slack_channels(db)


def _slack_raw_file_count(storage: Storage, opportunity_id: str) -> int:
    """Count objects under ``{gcs_prefix}/raw/slack/`` for ingestion metrics."""
    prefix = gcs_opportunity_prefix(opportunity_id)
    return len(storage.list_objects("raw", prefix, "slack"))


def _opportunity_source_status_str(raw: object) -> str:
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return "DISCOVERED"
    return raw.strip() if isinstance(raw, str) else str(raw)


def _aggregate_slack_sources_status(sources: list) -> str:
    """If any source is ACTIVE, return ACTIVE; else if all match, that value; else the first."""
    if not sources:
        return "DISCOVERED"
    norms = [_opportunity_source_status_str(s.status) for s in sources]
    if any(n.upper() == "ACTIVE" for n in norms):
        return "ACTIVE"
    if len(set(norms)) == 1:
        return norms[0]
    return norms[0]


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


def _ensure_opportunity_and_source_for_channel(
    db: Session,
    *,
    oid: str,
    channel_id: str,
) -> tuple[Opportunity, OpportunitySource, bool, bool]:
    opp = db.query(Opportunity).filter(Opportunity.opportunity_id == oid).first()
    opportunity_created = False
    source_created = False

    if not opp:
        owner = _default_owner(db)
        opp = Opportunity(
            opportunity_id=oid,
            name=oid,
            owner_id=owner.id,
            status=STATUS_DISCOVERED,
            total_documents=0,
            processed_documents=0,
        )
        db.add(opp)
        db.flush()
        opportunity_created = True

    source = (
        db.query(OpportunitySource)
        .filter(
            OpportunitySource.opportunity_id == opp.id,
            OpportunitySource.source_type == "slack",
            OpportunitySource.channel_id == channel_id,
        )
        .first()
    )
    if not source:
        unfilled = (
            db.query(OpportunitySource)
            .filter(
                OpportunitySource.opportunity_id == opp.id,
                OpportunitySource.source_type == "slack",
                OpportunitySource.channel_id.is_(None),
            )
            .first()
        )
        if unfilled is not None:
            unfilled.channel_id = channel_id
            source = unfilled
        else:
            source = OpportunitySource(
                opportunity_id=opp.id,
                source_type="slack",
                channel_id=channel_id,
                status="PENDING_AUTHORIZATION",
            )
            db.add(source)
            db.flush()
            source_created = True

    return opp, source, opportunity_created, source_created


async def _run_slack_sync_background(oid: str) -> None:
    with Session(get_engine()) as db:
        opp = db.query(Opportunity).filter(Opportunity.opportunity_id == oid).first()
        if not opp:
            logger.warning("Slack sync_start skipped: oid={} not found", oid)
            return
        sources = (
            db.query(OpportunitySource)
            .options(
                joinedload(OpportunitySource.opportunity).joinedload(Opportunity.owner)
            )
            .filter(
                OpportunitySource.opportunity_id == opp.id,
                OpportunitySource.source_type == "slack",
            )
            .order_by(OpportunitySource.id.asc())
            .all()
        )
        if not sources:
            logger.warning("Slack sync_start skipped: no source row for oid={}", oid)
            return
        for source in sources:
            await sync_slack_source(db, source)


@integrations_slack_router.post("/orchestrate/{oid}", response_model=SlackOrchestrateResponse)
def orchestrate_slack_channel(
    oid: str,
    body: Annotated[SlackOrchestrateRequest, Body(default_factory=SlackOrchestrateRequest)],
    db: Annotated[Session, Depends(get_db)],
):
    token = _slack_bot_token()
    try:
        normalized_oid = normalize_opportunity_oid(oid)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Validate and resolve authorized members first so channel creation only happens
    # after we have at least one confirmed @relanto.ai Slack user.
    raw_emails = []
    for item in body.team_emails:
        raw_emails.extend(str(item).split(","))
    valid_relanto_emails = sorted(
        {
            email.strip().lower()
            for email in raw_emails
            if email.strip().lower().endswith("@relanto.ai")
        }
    )
    if not valid_relanto_emails:
        raise HTTPException(
            status_code=400,
            detail="No authorized team members found. Provide at least one @relanto.ai email.",
        )

    resolved_member_ids: list[str] = []
    for email in valid_relanto_emails:
        slack_id = _lookup_slack_id_by_email(token, email)
        if slack_id:
            resolved_member_ids.append(slack_id)
    if not resolved_member_ids:
        raise HTTPException(
            status_code=400,
            detail="No authorized team members found...",
        )

    requested_name = (body.custom_channel_name or normalized_oid).strip().lower()
    parsed_oid = _oid_from_channel_name(requested_name)
    if not parsed_oid or parsed_oid != normalized_oid:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Channel name must include strict signature '{normalized_oid}' "
                "using oid + digits format."
            ),
        )

    channels = _list_all_channels(token)
    existing = _find_channel_by_exact_name(channels, requested_name)
    channel_created = False
    channel = existing or {}
    if not existing:
        channel = _create_channel(token, requested_name)
        channel_created = True

    channel_id = (channel.get("id") or "").strip()
    if not channel_id:
        raise HTTPException(status_code=502, detail="Slack channel ID missing from API response.")

    invited_count = _batch_invite_members(token, channel_id, resolved_member_ids)
    _, source, opp_created, src_created = _ensure_opportunity_and_source_for_channel(
        db,
        oid=normalized_oid,
        channel_id=channel_id,
    )
    source.channel_id = channel_id
    db.commit()

    if channel_created:
        msg = f"New private channel '{requested_name}' created and team invited successfully."
    else:
        msg = f"Existing channel '{requested_name}' matched; bot verified membership and invited team."

    return SlackOrchestrateResponse(
        message=msg,
        oid=normalized_oid,
        opportunity_created=opp_created,
        source_created=src_created,
        channel_created=channel_created,
        channel_name=requested_name,
        channel_id=channel_id,
        invited_count=invited_count,
    )


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
    body: Annotated[SlackConnectRequest, Body(default_factory=SlackConnectRequest)],
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
    sources = (
        db.query(OpportunitySource)
        .filter(
            OpportunitySource.opportunity_id == opp.id,
            OpportunitySource.source_type == "slack",
        )
        .all()
    )
    if not sources:
        _ensure_slack_source(db, opp)
        sources = (
            db.query(OpportunitySource)
            .filter(
                OpportunitySource.opportunity_id == opp.id,
                OpportunitySource.source_type == "slack",
            )
            .all()
        )
    for source in sources:
        source.status = "ACTIVE"
    db.commit()
    logger.info(
        "Slack connect_start: action=connect oid={} result=activated sources={}",
        normalized_oid,
        len(sources),
    )
    background_tasks.add_task(_run_slack_sync_background, normalized_oid)
    return {
        "requires_oauth": False,
        "message": "Slack bot token active; sync started.",
        "oid": normalized_oid,
        "status": "ACTIVE",
        "sync_started": True,
    }


@integrations_slack_router.post("/connect/{oid}", response_model=SlackProfessionalConnectResponse)
async def slack_professional_connect_integrations(
    oid: str,
    body: Annotated[SlackConnectRequest, Body(default_factory=SlackConnectRequest)],
    db: Annotated[Session, Depends(get_db)],
):
    """Professional ingestion: strict single-OID discovery, link channel → project, ACTIVE, sync (awaited).

    Runs discovery only for the path ``oid`` (no upserts for other opportunity ids), sets
    ``opportunity_sources.status`` to ``ACTIVE``, runs Slack → GCS sync in the request,
    and returns immediate raw-tier file counts plus persisted ``ACTIVE`` status.
    """
    _ = body
    _slack_bot_token()
    try:
        normalized_oid = normalize_opportunity_oid(oid)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    discovery_result = discover_slack_channels(db, oid_filter=normalized_oid)

    opp = db.query(Opportunity).filter(Opportunity.opportunity_id == normalized_oid).first()
    if not opp:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No opportunity found for '{normalized_oid}'. "
                "Create the project or ensure a Slack channel name includes this oid."
            ),
        )

    sources = (
        db.query(OpportunitySource)
        .filter(
            OpportunitySource.opportunity_id == opp.id,
            OpportunitySource.source_type == "slack",
        )
        .all()
    )
    if not sources:
        _ensure_slack_source(db, opp)
        sources = (
            db.query(OpportunitySource)
            .filter(
                OpportunitySource.opportunity_id == opp.id,
                OpportunitySource.source_type == "slack",
            )
            .all()
        )
    for s in sources:
        s.status = "ACTIVE"
    db.commit()

    sources = (
        db.query(OpportunitySource)
        .options(joinedload(OpportunitySource.opportunity))
        .filter(
            OpportunitySource.opportunity_id == opp.id,
            OpportunitySource.source_type == "slack",
        )
        .order_by(OpportunitySource.id.asc())
        .all()
    )
    if not sources or not sources[0].opportunity:
        raise HTTPException(
            status_code=500,
            detail="Slack source row missing after connect; retry discovery.",
        )

    messages_synced = 0
    for source in sources:
        messages_synced += await sync_slack_source(db, source)

    storage = Storage()
    total_files = _slack_raw_file_count(storage, opp.opportunity_id)

    logger.info(
        "Slack professional connect: oid={} status=ACTIVE total_files={} messages_synced={}",
        normalized_oid,
        total_files,
        messages_synced,
    )

    return SlackProfessionalConnectResponse(
        oid=normalized_oid,
        status="ACTIVE",
        total_files=total_files,
        messages_synced=messages_synced,
        discovery_result=discovery_result,
        requires_oauth=False,
        message="Slack discovery, activation, and ingestion completed.",
    )


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
    sources = (
        db.query(OpportunitySource)
        .filter(
            OpportunitySource.opportunity_id == opp.id,
            OpportunitySource.source_type == "slack",
        )
        .all()
    )
    if any((s.status or "").strip().upper() == "ACTIVE" for s in sources):
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


@integrations_slack_router.get(
    "/metrics/{oid}",
    response_model=SlackOpportunityMetricsResponse,
)
def slack_metrics_for_opportunity(
    oid: str,
    db: Annotated[Session, Depends(get_db)],
):
    """Return Slack ingestion metrics for one opportunity (all linked Slack channel sources)."""
    token = _slack_bot_token()
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

    sources = (
        db.query(OpportunitySource)
        .filter(
            OpportunitySource.opportunity_id == opp.id,
            OpportunitySource.source_type == "slack",
        )
        .order_by(OpportunitySource.id.asc())
        .all()
    )
    if not sources:
        raise HTTPException(
            status_code=404,
            detail=f"No slack opportunity source found for oid '{normalized_oid}'.",
        )

    channels: list[SlackMetricsChannelItem] = []
    for source in sources:
        raw_cid = (source.channel_id or "").strip()
        if raw_cid:
            info = _get_channel_info(token, raw_cid)
            ch_name = (info or {}).get("name") or raw_cid
            ch_id = raw_cid
        else:
            ch_id = f"unlinked:{source.id}"
            ch_name = "Unknown"
        ch_last: str | None = None
        if source.last_synced_at is not None:
            ch_last = source.last_synced_at.isoformat()
        channels.append(
            SlackMetricsChannelItem(
                id=ch_id,
                name=ch_name,
                last_synced_at=ch_last,
            )
        )

    storage = Storage()
    total_files = _slack_raw_file_count(storage, opp.opportunity_id)

    status_out = _aggregate_slack_sources_status(sources)

    last_ts = [s.last_synced_at for s in sources if s.last_synced_at is not None]
    max_last = max(last_ts) if last_ts else None
    last_synced_out: str | None = max_last.isoformat() if max_last is not None else None

    first_ck: str | None = None
    for s in sources:
        if s.sync_checkpoint:
            first_ck = s.sync_checkpoint
            break

    return SlackOpportunityMetricsResponse(
        total_files=total_files,
        status=status_out,
        last_synced_at=last_synced_out,
        sync_checkpoint=first_ck,
        channels=channels,
    )
