"""Gmail discovery: scan mailbox for thread subjects containing opportunity ids → DB upsert.

Uses the same opportunity-id parser as Slack/Drive discovery. Threads are found via Gmail search
``q`` (see ``GMAIL_DISCOVER_QUERY``). For each distinct OID, upserts ``opportunities``
and ``opportunity_sources`` (``source_type='gmail'``).

After discovery, ``sync_gmail_source`` searches with phrase + token queries (``subject:"oid…"``,
``subject:oid…``, ``in:sent`` / ``in:anywhere``) so natural subjects like
"Update on opportunity id oid1112" still match.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import quote_plus
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
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
from src.services.database_manager.user_connection_utils import (
    get_active_connection,
    has_google_scopes,
)
from src.services.plugins import oauth_service
from src.services.gmail.sync_service import (
    GmailSyncService,
    resolve_gmail_discovery_user,
)
from src.services.storage import Storage
from src.utils.logger import get_logger
from src.utils.opportunity_id import find_opportunity_oid, normalize_opportunity_oid


logger = get_logger(__name__)

router = APIRouter(prefix="/gmail", tags=["gmail"])

_GMAIL_READONLY = "https://www.googleapis.com/auth/gmail.readonly"
_GOOGLE_PROVIDER = "gmail"


def gmail_success_html(authenticated_email: str) -> str:
    """Styled HTML success page for Gmail OAuth callback fallback."""
    safe_email = authenticated_email or "your account"
    dashboard_url = get_settings().app.dashboard_url

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Login Successful</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg1: #ffffff;
      --bg2: #f3f4f6;
      --card: rgba(255,255,255,0.82);
      --text: #0f172a;
      --muted: #64748b;
      --success: #16a34a;
      --button: #2b59ff;
      --button-hover: #1f48e0;
      --border: rgba(255,255,255,0.7);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      padding: 24px;
      font-family: Inter, Arial, sans-serif;
      background: linear-gradient(135deg, var(--bg1) 0%, var(--bg2) 100%);
      color: var(--text);
    }}
    .card {{
      width: 100%;
      max-width: 640px;
      padding: 40px 32px;
      border-radius: 24px;
      background: var(--card);
      backdrop-filter: blur(14px);
      border: 1px solid var(--border);
      box-shadow:
        0 20px 60px rgba(15, 23, 42, 0.08),
        inset 0 1px 0 rgba(255,255,255,0.6);
      text-align: center;
    }}
    .check {{
      width: 88px;
      height: 88px;
      margin: 0 auto 20px;
      border-radius: 999px;
      display: grid;
      place-items: center;
      background: rgba(22,163,74,0.1);
      animation: pop 500ms ease;
    }}
    .check svg {{
      width: 48px;
      height: 48px;
      stroke: var(--success);
      stroke-width: 2.5;
      fill: none;
      stroke-linecap: round;
      stroke-linejoin: round;
    }}
    h1 {{
      margin: 0 0 12px;
      font-size: 32px;
      line-height: 1.1;
      font-weight: 800;
    }}
    p {{
      margin: 0;
      font-size: 16px;
      line-height: 1.7;
      color: var(--muted);
    }}
    .body {{
      margin-bottom: 10px;
    }}
    .secondary {{
      margin-top: 10px;
      margin-bottom: 28px;
    }}
    .email {{
      color: var(--text);
      font-weight: 700;
    }}
    .button {{
      display: inline-block;
      min-width: 240px;
      padding: 14px 22px;
      border-radius: 14px;
      background: var(--button);
      color: white;
      text-decoration: none;
      font-weight: 700;
      font-size: 16px;
      box-shadow: 0 10px 24px rgba(43,89,255,0.22);
      transition: transform 120ms ease, background 120ms ease;
    }}
    .button:hover {{
      background: var(--button-hover);
      transform: translateY(-1px);
    }}
    .fallback {{
      margin-top: 18px;
      font-size: 13px;
      color: var(--muted);
    }}
    .fallback a {{
      color: var(--button);
    }}
    @keyframes pop {{
      0% {{ transform: scale(0.8); opacity: 0; }}
      100% {{ transform: scale(1); opacity: 1; }}
    }}
  </style>
</head>
<body>
  <div class="card">
    <div class="check" aria-hidden="true">
      <svg viewBox="0 0 24 24">
        <path d="M20 6L9 17l-5-5"/>
      </svg>
    </div>

    <h1>Gmail Login Successful</h1>

    <p class="body">
      You have successfully authenticated your Gmail account:
      <span class="email">{safe_email}</span>.
    </p>

    <p class="secondary">
      You can now safely return to your dashboard. Your messages are being scanned in the background.
    </p>

    <a class="button" href="{dashboard_url}">Back to Dashboard</a>

    <div class="fallback">
      If the button doesn't work, use this link:
      <a href="{dashboard_url}">{dashboard_url}</a>
    </div>
  </div>
</body>
</html>"""


class GmailConnectRequest(BaseModel):
    redirect_uri: str = Field(
        ...,
        min_length=1,
        description="Google OAuth callback redirect URI for Gmail connector.",
    )
    return_url: str | None = Field(
        default=None,
        description="Optional frontend return URL after OAuth callback.",
    )
    user_email: str | None = Field(
        default=None,
        description="Mailbox identity used for Gmail connect authorization.",
    )
    redirect_oid: str | None = Field(
        default=None,
        description="Optional OID to preserve project context through OAuth state.",
    )


class GmailDiscoverStartRequest(BaseModel):
    oid: str = Field(
        ...,
        min_length=1,
        description="Opportunity ID for strict targeted Gmail discovery.",
    )
    redirect_uri: str = Field(
        ...,
        min_length=1,
        description="Google OAuth callback redirect URI for Gmail discovery flow.",
    )
    return_url: str | None = Field(
        default=None,
        description="Optional frontend return URL after OAuth callback.",
    )
    user_email: str | None = Field(
        default=None,
        description="Optional mailbox user email for personalized discovery.",
    )
    redirect_oid: str | None = Field(
        default=None,
        description="Optional OID to preserve project context through OAuth state.",
    )


def _oauth_state_secret() -> str:
    oauth = get_settings().oauth_plugin
    return (
        (oauth.google_oauth_state_secret or "").strip()
        or (oauth.google_client_secret or "").strip()
    )


def _build_signed_oauth_state(
    oid: str | None,
    redirect_uri: str,
    return_url: str | None = None,
    mode: str = "connect",
    user_email: str | None = None,
    redirect_oid: str | None = None,
) -> str:
    secret = _oauth_state_secret()
    if not secret:
        raise HTTPException(
            status_code=503,
            detail=(
                "Google OAuth state signing secret is not configured. Set "
                "GOOGLE_OAUTH_STATE_SECRET (or GOOGLE_CLIENT_SECRET)."
            ),
        )
    payload = {
        "mode": mode,
        "nonce": secrets.token_urlsafe(16),
        "issued_at": int(time.time()),
        "redirect_uri": redirect_uri,
    }
    if oid:
        payload["oid"] = oid
    if user_email:
        payload["user_email"] = user_email.strip().lower()
    if return_url:
        payload["return_url"] = return_url
    if redirect_oid:
        payload["redirect_oid"] = normalize_opportunity_oid(redirect_oid)
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )
    payload_b64 = base64.urlsafe_b64encode(payload_bytes).decode("ascii")
    sig = hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256)
    sig_b64 = base64.urlsafe_b64encode(sig.digest()).decode("ascii")
    return f"{payload_b64}.{sig_b64}"


def _parse_and_validate_oauth_state(state: str) -> dict[str, Any]:
    secret = _oauth_state_secret()
    if not state or "." not in state:
        raise HTTPException(status_code=400, detail="Invalid OAuth state.")
    if not secret:
        raise HTTPException(
            status_code=503,
            detail=(
                "Google OAuth state signing secret is not configured. Set "
                "GOOGLE_OAUTH_STATE_SECRET (or GOOGLE_CLIENT_SECRET)."
            ),
        )

    payload_b64, sig_b64 = state.split(".", 1)
    expected_sig = hmac.new(
        secret.encode("utf-8"), payload_b64.encode("ascii"), hashlib.sha256
    )
    expected_sig_b64 = base64.urlsafe_b64encode(expected_sig.digest()).decode("ascii")
    if not hmac.compare_digest(expected_sig_b64, sig_b64):
        raise HTTPException(status_code=400, detail="Invalid OAuth state signature.")

    try:
        payload_raw = base64.urlsafe_b64decode(payload_b64.encode("ascii"))
        payload = json.loads(payload_raw.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid OAuth state payload.") from exc

    issued_at = int(payload.get("issued_at") or 0)
    ttl = int(get_settings().oauth_plugin.google_oauth_state_ttl_seconds or 600)
    if issued_at <= 0 or int(time.time()) - issued_at > max(60, ttl):
        raise HTTPException(status_code=400, detail="OAuth state expired. Try again.")
    mode = (payload.get("mode") or "connect").strip().lower()
    if mode not in {"connect", "discover"}:
        raise HTTPException(status_code=400, detail="OAuth state has invalid mode.")
    if mode == "connect" and not (payload.get("oid") or "").strip():
        raise HTTPException(status_code=400, detail="OAuth state missing opportunity id.")
    if not (payload.get("redirect_uri") or "").strip():
        raise HTTPException(status_code=400, detail="OAuth state missing redirect uri.")
    if (payload.get("redirect_oid") or "").strip():
        payload["redirect_oid"] = normalize_opportunity_oid(payload["redirect_oid"])
    return payload


def _get_gmail_connector_user(
    db: Session,
    user_email: str | None = None,
) -> User:
    """Resolve explicit Gmail discovery user only (no connector/default fallback)."""
    explicit_user = resolve_gmail_discovery_user(db, user_email=user_email)
    if explicit_user:
        return explicit_user
    if not user_email:
        raise HTTPException(
            status_code=400,
            detail="Missing user_email for Gmail discovery.",
        )
    user = db.query(User).filter(User.email == user_email.strip().lower()).first()
    if not user:
        raise HTTPException(
            status_code=404,
            detail=f"User not found for user_email={user_email!r}.",
        )
    raise HTTPException(
        status_code=400,
        detail=(
            f"No active Google OAuth connection found for user_email={user_email!r}. "
            "Connect Google OAuth with Gmail scope first."
        ),
    )


def _resolve_gmail_identity(
    db: Session, user_email: str | None
) -> tuple[User | None, str]:
    """Resolve explicit Gmail identity by email only (allowing missing users for OAuth)."""
    req_email = (user_email or "").strip().lower() or None
    if not req_email:
        raise HTTPException(status_code=400, detail="Missing user_email.")
    target_user = db.query(User).filter(User.email == req_email).first()
    return target_user, req_email


def _gmail_service_for_user(db: Session, user: User) -> Any:
    s = get_settings().oauth_plugin
    if (
        not (s.google_client_id or "").strip()
        or not (s.google_client_secret or "").strip()
    ):
        raise HTTPException(
            status_code=400,
            detail="GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET are required.",
        )
    conn = get_active_connection(db, user.id, "gmail") or get_active_connection(
        db, user.id, "google"
    )
    if not conn or not (conn.refresh_token or "").strip():
        raise HTTPException(
            status_code=400,
            detail=(
                f"User {user.email!r} has no active Google OAuth connection with a refresh token."
            ),
        )
    creds = Credentials(
        token=None,
        refresh_token=conn.refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=s.google_client_id,
        client_secret=s.google_client_secret,
        scopes=[_GMAIL_READONLY],
    )
    try:
        creds.refresh(GoogleRequest())
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"Failed to refresh Gmail credentials: {exc}"
        ) from exc
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _gmail_oid_query(oid: str) -> str:
    normalized_oid = normalize_opportunity_oid(oid)
    return f"(subject:{normalized_oid} OR body:{normalized_oid})"


def _has_valid_google_gmail_refresh_connection(db: Session, user: User | None) -> bool:
    if not user:
        return False
    conn = get_active_connection(db, user.id, "gmail")
    if not conn:
        conn = get_active_connection(db, user.id, "google")
    return bool(conn and (conn.refresh_token or "").strip())


def _thread_subject_for_discovery(service: Any, thread_id: str) -> str:
    """Fetch lightweight thread metadata and return subject only for OID parsing."""
    t = (
        service
        .users()
        .threads()
        .get(
            userId="me",
            id=thread_id,
            format="metadata",
            metadataHeaders=["Subject"],
        )
        .execute()
    )
    msgs = t.get("messages") or []
    subject = ""
    for msg in msgs:
        headers = (msg.get("payload") or {}).get("headers") or []
        for h in headers:
            if (h.get("name") or "").lower() == "subject":
                value = (h.get("value") or "").strip()
                if value:
                    subject = value
                    break
        if subject:
            break
    return subject


def _gmail_query_candidates() -> list[str]:
    """Dynamic OID discovery query order without hardcoded OID values."""
    fallbacks = [
        "in:inbox subject:oid",
        "in:inbox subject:OID",
        "in:inbox subject:(oid OR OID)",
        "in:anywhere subject:oid",
        "in:anywhere subject:OID",
        "in:anywhere subject:(oid OR OID)",
    ]
    out: list[str] = []
    seen: set[str] = set()
    for q in fallbacks:
        if q and q not in seen:
            out.append(q)
            seen.add(q)
    return out


def _gmail_secondary_query_candidates() -> list[str]:
    """Bounded secondary generic queries (no hardcoded OIDs)."""
    candidates = [
        "in:inbox oid",
        "in:anywhere oid",
    ]
    out: list[str] = []
    seen: set[str] = set()
    for q in candidates:
        if q and q not in seen:
            out.append(q)
            seen.add(q)
    return out


def _union_thread_ids(
    service: Any, queries: list[str], max_threads: int
) -> tuple[list[str], str]:
    """Run multiple Gmail searches and union thread ids (order preserved, deduped).

    Each query gets a fair share of the global ``max_threads`` budget. Previously the first
    query could consume the entire cap, so later fallbacks (e.g. ``in:inbox oid``) never ran
    and threads like ``oid0123: …`` were never discovered.
    """
    seen_order: list[str] = []
    seen_set: set[str] = set()
    used: list[str] = []
    nq = max(1, len(queries))
    per_q = max(1, max_threads // nq)
    for q in queries:
        if len(seen_order) >= max_threads:
            break
        batch = _list_thread_ids(
            service, q, min(per_q, max_threads - len(seen_order))
        )
        n_new = 0
        for tid in batch:
            if tid not in seen_set:
                seen_set.add(tid)
                seen_order.append(tid)
                n_new += 1
        if batch:
            used.append(q)
            logger.info(
                "Gmail discover: query {!r} returned {} thread id(s) ({} new unique; total unique {})",
                q,
                len(batch),
                n_new,
                len(seen_order),
            )
    label = " | ".join(used) if used else (queries[0] if queries else "")
    return seen_order[:max_threads], label


def _list_thread_ids(service: Any, q: str, max_threads: int) -> list[str]:
    """Paginate users.threads.list and collect thread ids (deduped)."""
    out: list[str] = []
    page_token: str | None = None
    while len(out) < max_threads:
        req = (
            service
            .users()
            .threads()
            .list(
                userId="me",
                q=q,
                maxResults=min(100, max_threads - len(out)),
                pageToken=page_token,
            )
        )
        resp = req.execute()
        for th in resp.get("threads") or []:
            tid = th.get("id")
            if tid:
                out.append(tid)
            if len(out) >= max_threads:
                break
        page_token = (resp.get("nextPageToken") or "").strip() or None
        if not page_token:
            break
    return out


class GmailDiscoverResponse(BaseModel):
    connector_user_email: str
    gmail_search_query: str
    gmail_queries_used: str = Field(
        default="",
        description="Queries that returned at least one thread (union). See gmail_search_query for primary from env.",
    )
    threads_scanned: int
    threads_with_oid: int
    opportunities_created: int
    opportunity_sources_created: int
    skipped_thread_ids: list[str] = Field(
        default_factory=list,
        description="Thread ids with no opportunity id token in subject (first page of metadata).",
    )


def _list_recent_inbox_thread_ids(service: Any, max_threads: int) -> list[str]:
    """Deterministic fallback when OID queries return nothing."""
    return _list_thread_ids(service=service, q="in:inbox", max_threads=max_threads)


def discover_gmail_threads(
    db: Session,
    user_email: str | None = None,
    oid: str | None = None,
) -> GmailDiscoverResponse:
    """List threads via generic OID subject search; upsert opportunities + gmail sources."""
    gs = get_settings().gmail
    max_threads = max(1, min(gs.gmail_discover_max_threads, 500))

    connector = _get_gmail_connector_user(db, user_email=user_email)
    service = _gmail_service_for_user(db, connector)

    target_oid = normalize_opportunity_oid(oid) if oid else None
    if target_oid:
        # Project-first strict targeted discovery mode.
        strict_query = _gmail_oid_query(target_oid)
        thread_ids = _list_thread_ids(service, strict_query, max_threads)
        queries_used_label = strict_query
        query_list = [strict_query]
        secondary_queries: list[str] = []
        logger.info(
            "Gmail discover: targeted mode mailbox={} oid={} query={!r} thread_ids={}",
            connector.email,
            target_oid,
            strict_query,
            len(thread_ids),
        )
    else:
        # Primary: strict subject-token queries with bounded cap.
        query_list = _gmail_query_candidates()
        thread_ids, queries_used_label = _union_thread_ids(service, query_list, max_threads)
        secondary_queries = _gmail_secondary_query_candidates()
        if not thread_ids:
            logger.info(
                "Gmail discover: primary subject-only queries returned 0 for mailbox={} "
                "— running secondary generic fallback.",
                connector.email,
            )
            thread_ids, secondary_label = _union_thread_ids(
                service, secondary_queries, max_threads
            )
            queries_used_label = secondary_label or queries_used_label

        # Keep broad inbox fallback only for non-targeted discover.
        if not thread_ids:
            thread_ids = _list_recent_inbox_thread_ids(service, max_threads)
            if thread_ids:
                queries_used_label = "in:inbox (fallback scan)"
                logger.info(
                    "Gmail discover: OID queries returned 0; using recent inbox scan for mailbox={}",
                    connector.email
                )

    if not thread_ids:
        logger.warning(
            "Gmail discover: queries returned 0 threads for connector {} "
            "(tried: {}). Check mail is in this mailbox.",
            connector.email,
            query_list[:8],
        )
        try:
            prof = service.users().getProfile(userId="me").execute()
            logger.info(
                "Gmail discover: API getProfile OK — authenticated mailbox={}",
                prof.get("emailAddress"),
            )
        except Exception as exc:
            logger.warning("Gmail discover: getProfile failed (auth issue?): {}", exc)
        return GmailDiscoverResponse(
            connector_user_email=connector.email,
            gmail_search_query=" | ".join(query_list),
            gmail_queries_used="none",
            threads_scanned=0,
            threads_with_oid=0,
            opportunities_created=0,
            opportunity_sources_created=0,
        )
    created_opps = 0
    created_sources = 0
    matched = 0
    skipped_ids: list[str] = []
    malformed_subject_count = 0
    seen_oids: set[str] = set()

    for tid in thread_ids:
        try:
            subj = _thread_subject_for_discovery(service, tid)
        except Exception as exc:
            logger.warning(
                "Gmail discover: failed metadata for thread {}: {}", tid, exc
            )
            skipped_ids.append(tid)
            continue
        if not (subj or "").strip():
            malformed_subject_count += 1
            skipped_ids.append(tid)
            continue
        if target_oid:
            oid = target_oid
        else:
            oid = find_opportunity_oid(subj)
            if not oid:
                skipped_ids.append(tid)
                continue
            oid = normalize_opportunity_oid(oid)
        matched += 1
        if oid in seen_oids:
            continue
        seen_oids.add(oid)

        opp = db.query(Opportunity).filter(Opportunity.opportunity_id == oid).first()
        if not opp:
            opp = Opportunity(
                opportunity_id=oid,
                name=subj or oid,
                owner_id=connector.id,
                status=STATUS_DISCOVERED,
                total_documents=0,
                processed_documents=0,
            )
            db.add(opp)
            db.flush()
            created_opps += 1
            logger.info("Gmail discover created opportunity oid={} id={}", oid, opp.id)
        else:
            if not opp.owner_id:
                opp.owner_id = connector.id
            if not (opp.name or "").strip():
                opp.name = subj or oid

        src = (
            db
            .query(OpportunitySource)
            .filter(
                OpportunitySource.opportunity_id == opp.id,
                OpportunitySource.source_type == "gmail",
            )
            .first()
        )
        if not src:
            db.add(
                OpportunitySource(
                    opportunity_id=opp.id,
                    source_type="gmail",
                    status="PENDING_AUTHORIZATION",
                )
            )
            created_sources += 1
            logger.info(
                "Gmail discover created gmail source for opportunity_id={}", opp.id
            )

    db.commit()

    logger.info(
        "Gmail discover: DB commit OK — connector={} primary_queries_attempted={} "
        "secondary_queries_attempted={} "
        "threads_scanned={} threads_with_oid={} opportunities_created={} "
        "opportunity_sources_created={} skipped_threads={} malformed_or_empty_subjects={}",
        connector.email,
        len(query_list),
        len(secondary_queries),
        len(thread_ids),
        matched,
        created_opps,
        created_sources,
        len(skipped_ids),
        malformed_subject_count,
    )

    return GmailDiscoverResponse(
        connector_user_email=connector.email,
        gmail_search_query=(
            _gmail_oid_query(target_oid) if target_oid else "subject:oid (generic)"
        ),
        gmail_queries_used=queries_used_label or " | ".join(query_list),
        threads_scanned=len(thread_ids),
        threads_with_oid=matched,
        opportunities_created=created_opps,
        opportunity_sources_created=created_sources,
        skipped_thread_ids=skipped_ids,
    )


def discover_gmail_threads_impl(
    db: Session,
    user_email: str | None = None,
    oid: str | None = None,
) -> GmailDiscoverResponse:
    """Non-HTTP helper for orchestration (same as POST /gmail/discover)."""
    return discover_gmail_threads(db=db, user_email=user_email, oid=oid)


@router.post("/discover", response_model=GmailDiscoverResponse)
def discover_gmail_threads_endpoint(
    db: Annotated[Session, Depends(get_db)],
    user_email: str | None = Query(default=None),
    oid: str | None = Query(default=None),
):
    """Discover Gmail threads matching ``GMAIL_DISCOVER_QUERY``; upsert DB rows for Gmail sync.

    Then run ``POST /sync/trigger`` or ``POST /sync/run`` to pull threads to GCS raw/gmail/.
    """
    return discover_gmail_threads(db, user_email=user_email, oid=oid)


@router.post("/discover/me", response_model=GmailDiscoverResponse)
def discover_gmail_threads_me(
    db: Annotated[Session, Depends(get_db)],
    user_email: str | None = Query(default=None),
    oid: str | None = Query(default=None),
):
    """Discover Gmail threads for a specific user's mailbox (personalized discovery)."""
    if not user_email:
        raise HTTPException(
            status_code=400,
            detail="Provide user_email for personalized discovery.",
        )
    return discover_gmail_threads(db, user_email=user_email, oid=oid)


integrations_gmail_router = APIRouter(prefix="/integrations/gmail", tags=["gmail"])


async def _run_gmail_sync_background(oid: str) -> None:
    await GmailSyncService().sync_opportunity(oid)


async def _run_gmail_sync_now(oid: str) -> dict[str, Any]:
    return await GmailSyncService().sync_opportunity(oid)


def _run_gmail_discovery_background_sync(user_email: str) -> None:
    """Helper to run discovery in the background to avoid blocking OAuth redirects."""
    from src.services.database_manager.orm import SessionLocal
    with SessionLocal() as db:
        try:
            logger.info("Starting background discovery for {}", user_email)
            discover_gmail_threads(db, user_email=user_email)
            logger.info("Background discovery completed for {}", user_email)
        except Exception as exc:
            logger.error("Background discovery failed for {}: {}", user_email, exc)


def _ensure_gmail_source(db: Session, opp: Opportunity) -> OpportunitySource:
    source = (
        db.query(OpportunitySource)
        .filter(
            OpportunitySource.opportunity_id == opp.id,
            OpportunitySource.source_type == "gmail",
        )
        .first()
    )
    if source:
        return source
    source = OpportunitySource(
        opportunity_id=opp.id,
        source_type="gmail",
        status="PENDING_AUTHORIZATION",
    )
    db.add(source)
    db.flush()
    return source


@integrations_gmail_router.post("/discover")
async def gmail_discover_start_integrations(
    body: GmailDiscoverStartRequest,
    db: Annotated[Session, Depends(get_db)],
):
    """Strict OID-targeted discover flow; OAuth only when gmail token missing."""
    target_user, target_email = _resolve_gmail_identity(db, body.user_email)
    normalized_oid = normalize_opportunity_oid(body.oid)

    has_scope = bool(
        _has_valid_google_gmail_refresh_connection(db, target_user)
        and target_user
        and has_google_scopes(db, target_user.id, [_GMAIL_READONLY])
    )
    if has_scope:
        logger.info(
            "Gmail discover: targeted direct-discover for user={} oid={}",
            target_email,
            normalized_oid,
        )
        discovery = discover_gmail_threads(
            db,
            user_email=target_email,
            oid=normalized_oid,
        )
        return {
            "requires_oauth": False,
            "oid": normalized_oid,
            "message": "Gmail already authorized; targeted discovery completed.",
            "discovery_result": discovery.model_dump(),
        }

    logger.info(
        "Gmail discover: oauth-required for user={} (scope missing).",
        target_email or "unknown",
    )
    signed_state = _build_signed_oauth_state(
        oid=normalized_oid,
        redirect_uri=body.redirect_uri.strip(),
        return_url=(body.return_url or "").strip() or None,
        mode="discover",
        user_email=target_email,
        redirect_oid=body.redirect_oid or normalized_oid,
    )
    auth_url = await oauth_service.get_google_auth_url(
        redirect_uri=body.redirect_uri.strip(),
        provider="gmail",
        state=signed_state,
    )
    return {
        "requires_oauth": True,
        "auth_url": auth_url,
        "oid": normalized_oid,
        "message": "Google OAuth required before targeted discovery.",
    }


@integrations_gmail_router.post("/connect/{oid}")
async def gmail_connect_integrations(
    oid: str,
    body: GmailConnectRequest,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
):
    """Run deep synchronous ingestion when Gmail token exists."""
    _ = background_tasks
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

    source = _ensure_gmail_source(db, opp)
    target_user, target_email = _resolve_gmail_identity(db, body.user_email)
    identity_user = target_user
    has_scope = bool(
        _has_valid_google_gmail_refresh_connection(db, identity_user)
        and identity_user
        and has_google_scopes(db, identity_user.id, [_GMAIL_READONLY])
    )

    if has_scope:
        if not identity_user:
            raise HTTPException(
                status_code=403,
                detail="No gmail connection found for this user. Connect Gmail first.",
            )
        discovery = discover_gmail_threads(
            db,
            user_email=target_email,
            oid=normalized_oid,
        )
        if identity_user and opp.owner_id != identity_user.id:
            opp.owner_id = identity_user.id
        if (source.status or "").strip().upper() != "ACTIVE":
            source.status = "ACTIVE"
        db.commit()
        sync_result = await _run_gmail_sync_now(normalized_oid)
        metrics = gmail_metrics_integrations(
            oid=normalized_oid,
            db=db,
            user_email=target_email,
        )
        return {
            "requires_oauth": False,
            "message": "Already authorized for Gmail; deep sync completed.",
            "oid": normalized_oid,
            "status": "ACTIVE",
            "sync_started": False,
            "sync_completed": True,
            "discovery_result": discovery.model_dump(),
            "sync_result": sync_result,
            "metrics": metrics,
        }

    signed_state = _build_signed_oauth_state(
        oid=normalized_oid,
        redirect_uri=body.redirect_uri.strip(),
        return_url=(body.return_url or "").strip() or None,
        mode="connect",
        user_email=target_email,
        redirect_oid=body.redirect_oid or normalized_oid,
    )
    logger.info(
        "Gmail connect: oauth-required for oid={} user_email={} (scope missing).",
        normalized_oid,
        target_email,
    )
    auth_url = await oauth_service.get_google_auth_url(
        redirect_uri=body.redirect_uri.strip(),
        provider="gmail",
        state=signed_state,
    )
    db.commit()
    return {
        "requires_oauth": True,
        "auth_url": auth_url,
        "oid": normalized_oid,
    }


@integrations_gmail_router.get("/callback")
async def gmail_callback_integrations(
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
):
    """Complete Gmail OAuth, activate source for OID, and trigger background sync."""
    parsed_state: dict[str, Any] | None = None
    return_url: str | None = None
    mode = "connect"
    try:
        if not code:
            raise HTTPException(status_code=400, detail="Missing OAuth code.")
        if not state:
            raise HTTPException(status_code=400, detail="Missing OAuth state.")

        parsed_state = _parse_and_validate_oauth_state(state)
        mode = (parsed_state.get("mode") or "connect").strip().lower()
        return_url = (parsed_state.get("return_url") or "").strip() or None
        redirect_uri = (parsed_state.get("redirect_uri") or "").strip()

        result = await oauth_service.exchange_google_code(
            code, redirect_uri, db, provider="gmail"
        )
        email = (result.get("email") or "").strip().lower()
        if not email:
            raise HTTPException(status_code=400, detail="Google callback did not return email.")
        state_user_email = (parsed_state.get("user_email") or "").strip().lower() or None
        if not state_user_email:
            raise HTTPException(
                status_code=400,
                detail="OAuth state missing user_email.",
            )
        if state_user_email and state_user_email != email:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Authorized Google account {email!r} does not match requested mailbox "
                    f"{state_user_email!r}. Please login with the requested Gmail account."
                ),
            )
        user = db.query(User).filter(User.email == email).first()
        user_created = False
        if not user:
            logger.info("Gmail callback: creating new user for email={}", email)
            user = User(email=email, full_name=email.split("@")[0])
            db.add(user)
            db.flush()
            user_created = True
        if not has_google_scopes(db, user.id, [_GMAIL_READONLY]):
            raise HTTPException(
                status_code=400,
                detail="Reconnect and grant Gmail permission.",
            )

        # --- MODE: DISCOVER ---
        if mode == "discover":
            redirect_oid = (parsed_state.get("redirect_oid") or "").strip() or None
            if redirect_oid:
                normalized_oid = normalize_opportunity_oid(redirect_oid)
                discover_gmail_threads(db, user_email=email, oid=normalized_oid)
                await _run_gmail_sync_now(normalized_oid)
                if return_url:
                    sep = "&" if "?" in return_url else "?"
                    return RedirectResponse(
                        url=f"{return_url}{sep}gmail_login=success&email={email}&mode=discover&oid={normalized_oid}",
                        status_code=302,
                    )
                return RedirectResponse(
                    url=f"http://localhost:5173/gmail-result?oid={normalized_oid}&gmailConnect=1",
                    status_code=302,
                )

            # No project OID: preserve existing discover behavior.
            background_tasks.add_task(_run_gmail_discovery_background_sync, email)
            if return_url:
                sep = "&" if "?" in return_url else "?"
                return RedirectResponse(
                    url=f"{return_url}{sep}gmail_login=success&email={email}&mode=discover",
                    status_code=302,
                )
            return HTMLResponse(
                content=gmail_success_html(email),
                status_code=200,
            )

        # --- MODE: CONNECT ---
        normalized_oid = normalize_opportunity_oid(
            (parsed_state.get("redirect_oid") or parsed_state["oid"])
        )
        opp = db.query(Opportunity).filter(Opportunity.opportunity_id == normalized_oid).first()
        if not opp:
            raise HTTPException(status_code=404, detail=f"Opportunity {normalized_oid} not found.")
        
        source = _ensure_gmail_source(db, opp)
        if opp.owner_id != user.id:
            opp.owner_id = user.id
        source.status = "ACTIVE"
        db.commit()
        discover_gmail_threads(db, user_email=email, oid=normalized_oid)
        await _run_gmail_sync_now(normalized_oid)
        if return_url:
            sep = "&" if "?" in return_url else "?"
            return RedirectResponse(
                url=f"{return_url}{sep}gmail_login=success&email={email}&mode=connect&oid={normalized_oid}",
                status_code=302,
            )
        return RedirectResponse(
            url=f"http://localhost:5173/gmail-result?oid={normalized_oid}&gmailConnect=1",
            status_code=302,
        )

        return {
            "ok": True,
            "message": "Connection successful; background sync started.",
            "mode": "connect",
            "oid": normalized_oid,
            "email": email,
            "user_created": user_created,
            "status": "ACTIVE",
        }
    except Exception as exc:
        logger.exception("Gmail OAuth callback failed: {}", exc)
        detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
        if return_url:
            sep = "&" if "?" in return_url else "?"
            event = "gmail_discover" if mode == "discover" else "gmail_connect"
            return RedirectResponse(
                url=f"{return_url}{sep}{event}=error&error={quote_plus(str(detail))}",
                status_code=302,
            )
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=400, detail=str(detail)) from exc


@integrations_gmail_router.get("/connect-info/{oid}")
def gmail_connect_info_integrations(
    oid: str,
    db: Annotated[Session, Depends(get_db)],
):
    """Dashboard: Google token + gmail source status for an OID."""
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

    owner = db.query(User).filter(User.id == opp.owner_id).first() if opp.owner_id else None
    owner_conn = (
        (get_active_connection(db, owner.id, _GOOGLE_PROVIDER) or get_active_connection(db, owner.id, "google"))
        if owner
        else None
    )
    has_gmail_scope = bool(
        owner
        and owner_conn
        and has_google_scopes(db, owner.id, [_GMAIL_READONLY])
        and (owner_conn.refresh_token or "").strip()
    )

    source = (
        db.query(OpportunitySource)
        .filter(
            OpportunitySource.opportunity_id == opp.id,
            OpportunitySource.source_type == "gmail",
        )
        .first()
    )
    if not has_gmail_scope:
        return {
            "oid": normalized_oid,
            "status": "UNAUTHORIZED",
            "requires_oauth": True,
            "has_gmail_scope": False,
            "message": "Connect Gmail to grant read-only Gmail permission.",
        }
    if source and (source.status or "").strip().upper() == "ACTIVE":
        return {
            "oid": normalized_oid,
            "status": "ACTIVE",
            "requires_oauth": False,
            "has_gmail_scope": True,
            "message": "Gmail is connected and active for this opportunity.",
        }
    return {
        "oid": normalized_oid,
        "status": "DISCOVERED",
        "requires_oauth": False,
        "has_gmail_scope": True,
        "message": "Gmail permission is available; authorize to start syncing this opportunity.",
    }


@integrations_gmail_router.post("/authorize/{oid}")
async def gmail_authorize_integrations(
    oid: str,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
):
    """Activate gmail source and run a full sync in the background."""
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
            OpportunitySource.source_type == "gmail",
        )
        .first()
    )
    if not source:
        source = OpportunitySource(opportunity_id=opp.id, source_type="gmail")
        db.add(source)
        db.flush()

    source.status = "ACTIVE"
    db.commit()

    background_tasks.add_task(_run_gmail_sync_background, normalized_oid)
    return {"message": "Gmail sync started in the background.", "oid": normalized_oid}


@integrations_gmail_router.get("/metrics/{oid}")
def gmail_metrics_integrations(
    oid: str,
    db: Annotated[Session, Depends(get_db)],
    user_email: str | None = Query(default=None),
):
    """Count synchronized Gmail thread JSON files with mailbox-aware breakdown."""
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

    storage = Storage()
    names = storage.list_objects("raw", normalized_oid, "gmail")
    thread_names = [n for n in names if n.endswith("thread.json")]
    total_threads = len(thread_names)
    requested_mailbox = (user_email or "").strip().lower() or None
    by_mailbox: dict[str, int] = {}
    unknown_mailbox_threads = 0
    malformed_threads = 0

    for object_name in thread_names:
        try:
            payload = storage.read("raw", normalized_oid, "gmail", object_name)
            data = json.loads(payload.decode("utf-8"))
            meta = data.get("metadata") if isinstance(data, dict) else None
            mailbox = ""
            if isinstance(meta, dict):
                mailbox = str(meta.get("connector_user_email") or "").strip().lower()
            if mailbox:
                by_mailbox[mailbox] = by_mailbox.get(mailbox, 0) + 1
            else:
                unknown_mailbox_threads += 1
        except Exception as exc:
            malformed_threads += 1
            logger.warning(
                "Gmail metrics: malformed thread json oid={} object={} error={}",
                normalized_oid,
                object_name,
                exc,
            )

    by_mailbox_list = [
        {"user_email": mailbox, "thread_count": count}
        for mailbox, count in sorted(by_mailbox.items())
    ]
    requested_count = (
        by_mailbox.get(requested_mailbox, 0) if requested_mailbox else None
    )
    logger.info(
        "Gmail metrics: oid={} total_threads={} requested_mailbox={} "
        "mailboxes={} unknown_mailbox_threads={} malformed_threads={}",
        normalized_oid,
        total_threads,
        requested_mailbox,
        len(by_mailbox_list),
        unknown_mailbox_threads,
        malformed_threads,
    )

    response: dict[str, Any] = {
        "oid": normalized_oid,
        "total_threads": total_threads,
        "by_mailbox": by_mailbox_list,
        "unknown_mailbox_threads": unknown_mailbox_threads,
        "malformed_threads": malformed_threads,
    }
    if requested_mailbox:
        response["requested_mailbox"] = requested_mailbox
        response["threads_for_requested_mailbox"] = requested_count
    return response


dashboard_gmail_router = APIRouter(tags=["gmail-dashboard"])


@dashboard_gmail_router.get("/metrics/gmail/{oid}")
def gmail_metrics(
    oid: str,
    db: Annotated[Session, Depends(get_db)],
):
    normalized_oid = normalize_opportunity_oid(oid)
    opp = db.query(Opportunity).filter(Opportunity.opportunity_id == normalized_oid).first()
    if not opp:
        raise HTTPException(status_code=404, detail=f"Opportunity not found for '{normalized_oid}'.")

    source = (
        db.query(OpportunitySource)
        .filter(
            OpportunitySource.opportunity_id == opp.id,
            OpportunitySource.source_type == "gmail",
        )
        .first()
    )
    
    # Count unique threads in GCS raw/gmail/{oid}
    names = Storage().list_objects("raw", normalized_oid, "gmail")
    # Filter for only actual thread files
    thread_files = [n for n in names if n.endswith("thread.json")]
    unique_threads = {n.split("/")[0] for n in thread_files if "/" in n}

    return {
        "oid": normalized_oid,
        "total_files": len(unique_threads),
        "last_synced_at": (
            source.last_synced_at.isoformat() if source and source.last_synced_at else None
        ),
        "status": (source.status if source else "PENDING_AUTHORIZATION"),
    }


@dashboard_gmail_router.get("/authorize-info/gmail/{oid}")
def gmail_authorize_info(
    oid: str,
    db: Annotated[Session, Depends(get_db)],
):
    normalized_oid = normalize_opportunity_oid(oid)
    opp = db.query(Opportunity).filter(Opportunity.opportunity_id == normalized_oid).first()
    source = None
    if opp:
        source = (
            db.query(OpportunitySource)
            .filter(
                OpportunitySource.opportunity_id == opp.id,
                OpportunitySource.source_type == "gmail",
            )
            .first()
        )

    connector = resolve_gmail_discovery_user(db)
    has_conn = bool(
        connector and get_active_connection(db, connector.id, "gmail")
    )

    return {
        "oid": normalized_oid,
        "status": (source.status if source else "PENDING_AUTHORIZATION"),
        "has_gmail_connection": has_conn,
        "connector_user_email": (connector.email if connector else None),
        "message": (
            f"Connecting will automatically fetch all email threads with '{normalized_oid}' "
            "in the subject line. This ensures all context for this deal is available to the AI."
        ),
    }


@dashboard_gmail_router.post("/authorize/gmail/{oid}")
async def gmail_authorize(
    oid: str,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
):
    normalized_oid = normalize_opportunity_oid(oid)
    opp = db.query(Opportunity).filter(Opportunity.opportunity_id == normalized_oid).first()

    # Self-onboarding: Run targeted discovery if deal is missing
    if not opp:
        logger.info("Gmail authorize: OID {} not in DB; running targeted discovery.", normalized_oid)
        discovery = discover_gmail_threads(db)
        # Check if discovery created it
        opp = db.query(Opportunity).filter(Opportunity.opportunity_id == normalized_oid).first()
        if not opp:
            raise HTTPException(
                status_code=404,
                detail=f"No email threads found for '{normalized_oid}' in Gmail. Please ensure the deal ID is in the subject line."
            )

    # Ensure source exists
    source = _ensure_gmail_source(db, opp)

    # Check for OAuth
    connector = resolve_gmail_discovery_user(db)
    if not connector or not get_active_connection(db, connector.id, "gmail"):
        raise HTTPException(
            status_code=400,
            detail="Gmail account not authorized. Please log in via the Admin Settings first."
        )

    source.status = "ACTIVE"
    db.commit()
    from src.apis.routes.gmail_routes import _run_gmail_sync_background
    background_tasks.add_task(_run_gmail_sync_background, normalized_oid)

    return {
        "oid": normalized_oid,
        "status": "ACTIVE",
        "sync_started": True,
        "message": "Gmail source activated; sync started.",
    }
