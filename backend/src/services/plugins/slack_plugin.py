"""Slack plugin: fetch channel history and write GCS raw layout expected by GcsPipeline.

Writes, per opportunity:
  {opportunity_id}/raw/slack/slack_metadata.json
      → { "channels": [ { "id", "name", "members": [ {"id", "name"}, ... ] }, ... ] }
  {opportunity_id}/raw/slack/{channel_id}/slack_messages.json
      → JSON array of message objects (Slack API–like: channel, user, text, type, ts, …)

Channel selection: Slack channel *name* must start with the alphanumeric-lowercase prefix
derived from ``opportunities.opportunity_id`` (see ``_oid_to_slack_channel_prefix``).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
from sqlalchemy.orm import Session

from configs.settings import get_settings
from src.services.database_manager.models.auth_models import OpportunitySource
from src.services.storage.service import Storage
from src.utils.logger import get_logger
from src.utils.opportunity_id import gcs_opportunity_prefix, gcs_path_prefix_candidates


logger = get_logger(__name__)
SLACK_API_BASE = "https://slack.com/api"


def _get_headers() -> dict | None:
    bot_token = (get_settings().slack.bot_token or "").strip()
    if not bot_token:
        return None
    return {
        "Authorization": f"Bearer {bot_token}",
        "Content-Type": "application/json; charset=utf-8",
    }


def _oid_to_slack_channel_prefix(oid: str) -> str:
    """Format OID to a safe slack channel prefix (e.g. OID/1023 -> oid1023)."""
    return "".join(c for c in str(oid) if c.isalnum()).lower()


def _utc_fetched_at() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


def _to_export_message(channel_id: str, msg: dict, fetched_at: str) -> dict | None:
    """Map Slack API history row to poller-style export dict; skip non-text noise."""
    if msg.get("type") != "message":
        return None
    if msg.get("subtype") in ("channel_join", "channel_leave", "channel_archive"):
        return None
    text = (msg.get("text") or "").strip()
    if not text and not (msg.get("blocks")):
        return None
    uid = msg.get("user") or ""
    if not uid and msg.get("bot_id"):
        uid = msg.get("bot_id", "")
    out: dict = {
        "channel": channel_id,
        "fetched_at": fetched_at,
        "user": uid,
        "type": "message",
        "ts": msg.get("ts"),
        "text": text,
    }
    if msg.get("thread_ts"):
        out["thread_ts"] = msg["thread_ts"]
    if msg.get("subtype"):
        out["subtype"] = msg["subtype"]
    if msg.get("blocks"):
        out["blocks"] = msg["blocks"]
    if msg.get("team"):
        out["team"] = msg["team"]
    return out


def _merge_by_ts(existing: list[dict], fresh: list[dict]) -> list[dict]:
    """Merge two message lists keyed by ts (string); keep chronological order."""
    by_ts: dict[str, dict] = {}
    for m in existing:
        ts = m.get("ts")
        if ts is not None:
            by_ts[str(ts)] = m
    for m in fresh:
        ts = m.get("ts")
        if ts is not None:
            by_ts[str(ts)] = m
    merged = list(by_ts.values())
    merged.sort(key=lambda x: float(x["ts"]))
    return merged


async def _slack_user_name(client: httpx.AsyncClient, headers: dict, uid: str) -> str:
    if not uid:
        return "unknown"
    try:
        r = await client.get(
            f"{SLACK_API_BASE}/users.info",
            headers=headers,
            params={"user": uid},
        )
        if r.status_code == 200 and r.json().get("ok"):
            u = r.json().get("user") or {}
            prof = u.get("profile") or {}
            return (
                prof.get("real_name") or u.get("real_name") or u.get("name") or uid
            ).strip() or uid
    except Exception:
        pass
    return uid


async def _list_channel_member_ids(
    client: httpx.AsyncClient,
    headers: dict,
    channel_id: str,
) -> list[str]:
    ids: list[str] = []
    cursor = None
    while True:
        params: dict = {"channel": channel_id, "limit": 200}
        if cursor:
            params["cursor"] = cursor
        r = await client.get(
            f"{SLACK_API_BASE}/conversations.members",
            headers=headers,
            params=params,
        )
        if r.status_code != 200 or not r.json().get("ok"):
            break
        data = r.json()
        ids.extend(data.get("members") or [])
        cursor = (data.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    return ids


async def _fetch_channel_history(
    client: httpx.AsyncClient,
    headers: dict,
    channel_id: str,
) -> list[dict]:
    """Return messages oldest-first (matches slack_poller / preprocessor expectations)."""
    pages: list[dict] = []
    cursor = None
    while True:
        params: dict = {"channel": channel_id, "limit": 200}
        if cursor:
            params["cursor"] = cursor
        r = await client.get(
            f"{SLACK_API_BASE}/conversations.history",
            headers=headers,
            params=params,
        )
        if r.status_code != 200 or not r.json().get("ok"):
            break
        data = r.json()
        pages.extend(data.get("messages") or [])
        cursor = (data.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    pages.reverse()
    return pages


async def _get_channel_info(
    client: httpx.AsyncClient,
    headers: dict,
    channel_id: str,
) -> dict | None:
    r = await client.get(
        f"{SLACK_API_BASE}/conversations.info",
        headers=headers,
        params={"channel": channel_id},
    )
    if r.status_code != 200:
        return None
    data = r.json()
    if not data.get("ok"):
        return None
    return data.get("channel")


def _load_existing_channel_export(
    storage: Storage,
    db_opportunity_id: str,
    channel_id: str,
) -> list[dict]:
    """Load merged messages; try canonical GCS prefix first, then legacy DB casing."""
    for oid in gcs_path_prefix_candidates(db_opportunity_id):
        try:
            raw = storage.read("raw", oid, "slack", f"{channel_id}/slack_messages.json")
            parsed = json.loads(raw.decode("utf-8"))
            return parsed if isinstance(parsed, list) else []
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            continue
    return []


async def sync_slack_source(db: Session, source: OpportunitySource) -> int:
    """Sync Slack → GCS raw/slack in GcsPipeline-compatible layout."""
    opp = source.opportunity
    headers = _get_headers()
    if not headers:
        logger.warning("No SLACK_BOT_TOKEN configured; skipping Slack sync.")
        return 0

    prefix = _oid_to_slack_channel_prefix(opp.opportunity_id)
    if not prefix:
        return 0
    preferred_channel_id = (source.channel_id or "").strip()

    # GCS object names are case-sensitive; always use canonical prefix (e.g. oid1023) so we
    # never duplicate raw/slack under OID1023 vs oid1023 when DB casing varies.
    gcs_oid = gcs_opportunity_prefix(str(opp.opportunity_id))

    storage = Storage()
    fetched_at = _utc_fetched_at()
    max_ts: str | None = None

    async with httpx.AsyncClient(timeout=60.0) as client:
        channels: list[dict] = []
        cursor = None
        while True:
            params: dict = {
                "types": "public_channel,private_channel",
                "exclude_archived": "true",
                "limit": 200,
            }
            if cursor:
                params["cursor"] = cursor
            r = await client.get(
                f"{SLACK_API_BASE}/conversations.list",
                headers=headers,
                params=params,
            )
            if r.status_code != 200 or not r.json().get("ok"):
                break
            data = r.json()
            channels.extend(data.get("channels") or [])
            cursor = (data.get("response_metadata") or {}).get("next_cursor")
            if not cursor:
                break

        matching: list[dict] = []
        if preferred_channel_id:
            preferred = next((c for c in channels if (c.get("id") or "") == preferred_channel_id), None)
            if not preferred:
                preferred = await _get_channel_info(client, headers, preferred_channel_id)
            if preferred:
                matching = [preferred]
            else:
                logger.warning(
                    "Stored Slack channel_id {} not found for opportunity {}; falling back to prefix match.",
                    preferred_channel_id,
                    opp.opportunity_id,
                )

        if not matching:
            matching = [c for c in channels if prefix in (c.get("name") or "").lower()]
        if not matching:
            logger.info(
                "No Slack channels match prefix {} for opportunity {}",
                repr(prefix),
                opp.opportunity_id,
            )
            return 0

        meta_channels: list[dict] = []
        total_written = 0

        for ch in matching:
            ch_id = ch.get("id")
            ch_name = ch.get("name", "")
            if not ch_id:
                continue

            member_ids = await _list_channel_member_ids(client, headers, ch_id)
            members_meta: list[dict] = []
            for mid in member_ids:
                display = await _slack_user_name(client, headers, mid)
                members_meta.append({"id": mid, "name": display})

            meta_channels.append({
                "id": ch_id,
                "name": ch_name,
                "members": members_meta,
            })

            # Auto-join public channels so salespeople never have to type /invite
            try:
                await client.post(
                    f"{SLACK_API_BASE}/conversations.join",
                    headers=headers,
                    json={"channel": ch_id},
                )
            except Exception as e:
                logger.debug("Slack auto-join skipped for channel {}: {}", ch_name, e)

            history = await _fetch_channel_history(client, headers, ch_id)
            fresh_export: list[dict] = []
            for msg in history:
                row = _to_export_message(ch_id, msg, fetched_at)
                if row:
                    fresh_export.append(row)

            existing = _load_existing_channel_export(storage, opp.opportunity_id, ch_id)
            existing_ts = {str(m["ts"]) for m in existing if m.get("ts") is not None}
            new_ts = {
                str(m["ts"])
                for m in fresh_export
                if m.get("ts") is not None and str(m["ts"]) not in existing_ts
            }
            merged = _merge_by_ts(existing, fresh_export)

            for m in merged:
                ts = m.get("ts")
                if ts is not None and (max_ts is None or float(ts) > float(max_ts)):
                    max_ts = str(ts)

            body = json.dumps(merged, ensure_ascii=False, indent=2)
            storage.write(
                tier="raw",
                opportunity_id=gcs_oid,
                source="slack",
                object_name=f"{ch_id}/slack_messages.json",
                content=body,
                content_type="application/json",
            )
            total_written += len(merged)
            logger.info(
                "Slack channel {} ({}): messages in GCS after merge={}, "
                "new ts this run={}, previously stored={}",
                ch_name,
                ch_id,
                len(merged),
                len(new_ts),
                len(existing_ts),
            )

            if not source.channel_id:
                source.channel_id = ch_id

        meta_doc = {"channels": meta_channels}
        storage.write(
            tier="raw",
            opportunity_id=gcs_oid,
            source="slack",
            object_name="slack_metadata.json",
            content=json.dumps(meta_doc, ensure_ascii=False, indent=2),
            content_type="application/json",
        )

        # The loop below was previously trying to read-back from GCS.
        # We now have the max_ts calculated directly while syncing.

    source.last_synced_at = datetime.now(UTC).replace(tzinfo=None)
    source.sync_checkpoint = max_ts
    db.commit()

    logger.info(
        "Slack sync finished for {}: {} channel(s); total messages in merged exports={} "
        "(see per-channel lines for new message timestamps this run)",
        opp.opportunity_id,
        len(matching),
        total_written,
    )
    return total_written
