"""Thread-safe in-memory hub for SSE notifications (single-worker deployments).

Uses ``queue.Queue`` so sync FastAPI route handlers can publish while async
generators consume via ``asyncio.to_thread``.
"""

from __future__ import annotations

import json
import queue
import threading
import uuid
from typing import Any

from src.utils.logger import get_logger

logger = get_logger(__name__)

_lock = threading.Lock()
_by_user: dict[int, list[queue.Queue[bytes]]] = {}
_admin_queues: list[queue.Queue[bytes]] = []


def format_sse(data: dict[str, Any], event: str | None = None) -> bytes:
    payload = json.dumps(data, separators=(",", ":"), default=str)
    lines: list[str] = []
    if event:
        lines.append(f"event: {event}")
    lines.append(f"data: {payload}")
    lines.append("")
    return ("\n".join(lines) + "\n").encode("utf-8")


def subscribe(user_id: int, *, is_admin: bool) -> queue.Queue[bytes]:
    q: queue.Queue[bytes] = queue.Queue(maxsize=50)
    with _lock:
        _by_user.setdefault(user_id, []).append(q)
        if is_admin:
            _admin_queues.append(q)
        n_user = len(_by_user.get(user_id, []))
        n_adm = len(_admin_queues)
    logger.info(
        "notifications hub subscribe user_id={} is_admin={} queues_for_user={} total_admin_queues={}",
        user_id,
        is_admin,
        n_user,
        n_adm,
    )
    return q


def unsubscribe(user_id: int, q: queue.Queue[bytes], *, is_admin: bool) -> None:
    with _lock:
        if is_admin and q in _admin_queues:
            _admin_queues.remove(q)
        lst = _by_user.get(user_id)
        if not lst:
            return
        if q in lst:
            lst.remove(q)
        if not lst:
            del _by_user[user_id]


def _put_all(targets: list[queue.Queue[bytes]], frame: bytes) -> None:
    for q in targets:
        try:
            q.put_nowait(frame)
        except queue.Full:
            pass


def publish_all_admins(payload: dict[str, Any]) -> None:
    frame = format_sse(payload, event="notification")
    with _lock:
        targets = list(_admin_queues)
    logger.info(
        "notifications hub publish_all_admins type={} admin_connections={}",
        payload.get("type"),
        len(targets),
    )
    _put_all(targets, frame)


def publish_user(user_id: int, payload: dict[str, Any]) -> None:
    frame = format_sse(payload, event="notification")
    with _lock:
        targets = list(_by_user.get(user_id, []))
    logger.info(
        "notifications hub publish_user user_id={} type={} connections={}",
        user_id,
        payload.get("type"),
        len(targets),
    )
    _put_all(targets, frame)


def publish_opportunity_request_created(
    *,
    request_id: uuid.UUID | str,
    submitter_user_id: int,
    organization_name: str,
    opportunity_title: str,
    opportunity_id: str,
) -> None:
    publish_all_admins(
        {
            "type": "opportunity_request.created",
            "request_id": str(request_id),
            "submitter_user_id": int(submitter_user_id),
            "organization_name": organization_name,
            "opportunity_title": opportunity_title,
            "opportunity_id": opportunity_id,
        }
    )


def publish_opportunity_request_reviewed(
    *,
    requester_user_id: int,
    request_id: uuid.UUID | str,
    status: str,
    opportunity_title: str,
    admin_remarks: str | None = None,
    opportunity_id: str | None = None,
) -> None:
    publish_user(
        int(requester_user_id),
        {
            "type": "opportunity_request.reviewed",
            "request_id": str(request_id),
            "status": status,
            "opportunity_title": opportunity_title,
            "admin_remarks": admin_remarks,
            "opportunity_id": opportunity_id,
        },
    )
