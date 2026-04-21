#!/usr/bin/env python3
"""Smoke: call each connector discover + sync/trigger against a running API.

Uses only the Python standard library for HTTP (no ``httpx`` / ``requests``).

Calls (in order)::

  POST /slack/discover
  POST /gmail/discover
  POST /drive/discover
  POST /zoom/discover?days_lookback=N
  POST /sync/trigger

Alternatively use ``--sync-run`` to match Cloud Scheduler: a single ``POST /sync/run``
(discover Slack + Gmail + Drive in order, then sync all sources). Zoom is **not**
included in ``/sync/run`` — run Zoom discover separately if needed.

Requires
--------
  - API reachable (local uvicorn or Cloud Run URL).
  - Same DB + env the app uses (Drive: ``DRIVE_ROOT_FOLDER_NAME``, OAuth tokens, etc.).

Examples
--------
  # Local
  uv run python scripts/tests_integration/smoke_connectors_discover_and_sync.py

  # Cloud Run (public invoker)
  uv run python scripts/tests_integration/smoke_connectors_discover_and_sync.py \\
    --base-url https://data-connectors-xxxxx.run.app

  # Cloud Run (authenticated)
  uv run python scripts/tests_integration/smoke_connectors_discover_and_sync.py \\
    --base-url https://data-connectors-xxxxx.run.app \\
    --identity-token

  # Save all HTTP JSON responses to a file (connector log lines still print on the API server)
  python scripts/tests_integration/smoke_connectors_discover_and_sync.py \\
    --base-url http://0.0.0.0:8080 --save-json output/discover_sync_report.json

  # After smoke, verify DB rows for one opportunity (same PG_* / CLOUDSQL_* as the API)
  uv run python scripts/tests_integration/smoke_connectors_discover_and_sync.py \\
    --base-url http://0.0.0.0:8080 --validate-oid oid1111 --save-json output/report.json

Why ``gcloud logging read`` can show nothing
---------------------------------------------
  - No log lines match the filter (job id / resource type differ).
  - Wrong project: add ``--project=YOUR_PROJECT_ID``.
  - Try: ``gcloud logging read 'resource.type=cloud_run_revision' --limit=20 --project=...``
    and narrow from there.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urljoin


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

try:
    from dotenv import load_dotenv

    if (_PROJECT_ROOT / "configs" / ".env").exists():
        load_dotenv(_PROJECT_ROOT / "configs" / ".env", override=False)
    if (_PROJECT_ROOT / "configs" / "secrets" / ".env").exists():
        load_dotenv(_PROJECT_ROOT / "configs" / "secrets" / ".env", override=True)
except ImportError:
    pass


def _gcloud_identity_token(
    impersonate_sa: str | None = None,
    audience: str | None = None,
) -> str:
    """User login: no --audiences. SA impersonation: pass impersonate_sa + audience."""
    exe = shutil.which("gcloud") or shutil.which("gcloud.cmd")
    if not exe:
        raise RuntimeError(
            "gcloud not found in PATH. Install Google Cloud SDK or use --token."
        )
    cmd = [exe, "auth", "print-identity-token"]
    if impersonate_sa:
        cmd.append(f"--impersonate-service-account={impersonate_sa}")
        if audience:
            cmd.append(f"--audiences={audience.rstrip('/')}")
    return subprocess.check_output(cmd, text=True, timeout=120).strip()


def _log(title: str, msg: str = "") -> None:
    bar = "=" * 72
    print(f"\n{bar}\n{title}\n{bar}")
    if msg:
        print(msg)


def _pretty(data: Any, limit: int = 12000) -> str:
    try:
        s = json.dumps(data, indent=2, default=str, ensure_ascii=False)
    except TypeError:
        s = str(data)
    if len(s) > limit:
        return s[:limit] + f"\n... [{len(s) - limit} more chars truncated]"
    return s


def _post_empty(
    url: str,
    headers: dict[str, str],
    timeout: float,
) -> tuple[int, Any]:
    """POST with empty body (discover/sync endpoints). Stdlib only."""
    h = dict(headers)
    h.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=b"", method="POST", headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        status = e.code
        raw = e.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as e:
        raise OSError(str(e)) from e
    try:
        body: Any = json.loads(raw) if raw.strip() else None
    except json.JSONDecodeError:
        body = raw
    return status, body


def main() -> int:
    p = argparse.ArgumentParser(
        description="POST discover for each connector, then POST /sync/trigger.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    default_base = (
        os.environ.get("SMOKE_API_BASE_URL")
        or os.environ.get("API_BASE_URL")
        or "http://0.0.0.0:8080"
    ).rstrip("/")
    p.add_argument(
        "--base-url",
        default=default_base,
        help=f"API root (no trailing slash). Default: {default_base!r}",
    )
    p.add_argument(
        "--token",
        default=os.environ.get("SMOKE_API_TOKEN", ""),
        help="Bearer token (or set SMOKE_API_TOKEN).",
    )
    p.add_argument(
        "--identity-token",
        action="store_true",
        help="Bearer from gcloud auth print-identity-token (user login; no --audiences).",
    )
    p.add_argument(
        "--impersonate-service-account",
        metavar="EMAIL",
        default="",
        help="With --identity-token: use SA impersonation + audiences (advanced).",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=600.0,
        help="HTTP timeout seconds (sync can be slow). Default: 600",
    )
    p.add_argument(
        "--zoom-days",
        type=int,
        default=14,
        help="days_lookback for POST /zoom/discover. Default: 14",
    )
    p.add_argument(
        "--sync-run",
        action="store_true",
        help="Only POST /sync/run (scheduler-style: Slack+Gmail+Drive discover then sync). Skips per-connector loop.",
    )
    p.add_argument(
        "--skip-zoom-discover",
        action="store_true",
        help="Skip POST /zoom/discover in the per-connector sequence.",
    )
    p.add_argument(
        "--no-sync",
        action="store_true",
        help="Only run discover endpoints; do not POST /sync/trigger.",
    )
    p.add_argument(
        "--save-json",
        metavar="PATH",
        default="",
        help="Write one JSON file with every step (name, url, http_status, response).",
    )
    p.add_argument(
        "--validate-oid",
        metavar="OID",
        default="",
        help=(
            "After HTTP steps, query the same DB as the API (PG_* / CLOUDSQL_* from env) "
            "and print opportunities + opportunity_sources for this opportunity_id "
            "(e.g. oid1111). Requires DB reachable from this machine."
        ),
    )
    args = p.parse_args()

    base = args.base_url.rstrip("/")
    headers: dict[str, str] = {"Accept": "application/json"}
    token = (args.token or "").strip()
    if args.identity_token:
        try:
            imp = (args.impersonate_service_account or "").strip()
            token = _gcloud_identity_token(
                impersonate_sa=imp or None,
                audience=base if imp else None,
            )
        except (RuntimeError, subprocess.CalledProcessError, OSError) as e:
            _log("ERROR", f"Could not get identity token: {e}")
            return 1
    if token:
        headers["Authorization"] = f"Bearer {token}"

    _log(
        "Smoke: connectors discover + sync",
        f"base_url={base}\n"
        f"auth={'Bearer <set>' if token else 'none'}\n"
        f"sync_run={args.sync_run}\n"
        "Server-side logs (Drive/Slack/Gmail plugins) appear in the uvicorn/Cloud Run log stream, "
        "not in this script — use LOG_LEVEL=info or Cloud Logging for those.\n",
    )

    timeout = args.timeout
    failures = 0
    report: dict[str, Any] = {
        "base_url": base,
        "sync_run": bool(args.sync_run),
        "note": (
            "Per-connector plugin logs (drive_plugin, slack_plugin, gmail_plugin, zoom, …) "
            "are printed by the API process. Locally: uvicorn main:app --log-level info. "
            "In GCP: Cloud Run → Logs or gcloud logging read …"
        ),
        "steps": [],
    }

    def _record(
        name: str, url: str, code: int, body: Any, err: str | None = None
    ) -> None:
        step: dict[str, Any] = {
            "name": name,
            "url": url,
            "http_status": code,
            "response": body,
        }
        if err:
            step["error"] = err
        report["steps"].append(step)

    if args.sync_run:
        url = urljoin(base + "/", "sync/run")
        _log("POST /sync/run", url)
        try:
            code, body = _post_empty(url, headers, timeout)
        except OSError as e:
            print(f"REQUEST FAILED: {e}")
            _record("POST /sync/run", url, 0, None, str(e))
            failures += 1
            report["failure_count"] = failures
            _maybe_save_json(args.save_json, report)
            return 1
        print(f"status={code}")
        print(_pretty(body))
        _record("POST /sync/run", url, code, body)
        if code >= 400:
            failures += 1
        report["failure_count"] = failures
        _maybe_save_json(args.save_json, report)
        return 1 if failures else 0

    steps: list[tuple[str, str]] = [
        ("POST /slack/discover", urljoin(base + "/", "slack/discover")),
        ("POST /gmail/discover", urljoin(base + "/", "gmail/discover")),
        ("POST /drive/discover", urljoin(base + "/", "drive/discover")),
    ]
    if not args.skip_zoom_discover:
        z = urljoin(base + "/", f"zoom/discover?days_lookback={args.zoom_days}")
        steps.append(("POST /zoom/discover", z))

    for title, url in steps:
        _log(title, url)
        try:
            code, body = _post_empty(url, headers, timeout)
        except OSError as e:
            print(f"REQUEST FAILED: {e}")
            _record(title, url, 0, None, str(e))
            failures += 1
            continue
        print(f"status={code}")
        print(_pretty(body))
        _record(title, url, code, body)
        if code >= 400:
            failures += 1
            print("^^ ERROR (HTTP >= 400)")

    if not args.no_sync:
        url = urljoin(base + "/", "sync/trigger")
        _log("POST /sync/trigger", url)
        try:
            code, body = _post_empty(url, headers, timeout)
        except OSError as e:
            print(f"REQUEST FAILED: {e}")
            _record("POST /sync/trigger", url, 0, None, str(e))
            failures += 1
            report["failure_count"] = failures
            _maybe_save_json(args.save_json, report)
            return 1
        print(f"status={code}")
        print(_pretty(body))
        _record("POST /sync/trigger", url, code, body)
        if code >= 400:
            failures += 1
    else:
        _log("Skipping /sync/trigger", "--no-sync")

    _log(
        "Done",
        f"failures={failures} (non-2xx discover/sync or transport error)\n"
        "Tip: for Drive, check DRIVE_ROOT_FOLDER_NAME matches parent folder (e.g. Requirements) "
        "and POST /drive/discover returned folders_parsed > 0 for your oid.",
    )
    report["failure_count"] = failures

    vo = (args.validate_oid or "").strip()
    if vo:
        _log("DB validate", f"opportunity_id={vo}")
        snap = _db_validate_opportunity(vo)
        print(_pretty(snap))
        report["db_validate"] = snap

    _maybe_save_json(args.save_json, report)
    return 1 if failures else 0


def _db_validate_opportunity(oid: str) -> dict[str, Any]:
    """Load ``opportunities`` + ``opportunity_sources`` for ``oid`` using app ORM (same env as API)."""
    try:
        from sqlalchemy.orm import sessionmaker

        from src.services.database_manager.models.auth_models import (
            Opportunity,
            OpportunitySource,
        )
        from src.services.database_manager.orm import get_engine
    except Exception as e:
        return {"ok": False, "error": f"import failed: {e}"}

    engine = get_engine()
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    try:
        opp = db.query(Opportunity).filter(Opportunity.opportunity_id == oid).first()
        if not opp:
            return {
                "ok": True,
                "opportunity_id": oid,
                "opportunity_row": None,
                "opportunity_sources": [],
                "notes": (
                    "No row in opportunities — run discover for Slack/Gmail/Drive/Zoom or insert."
                ),
            }
        rows = (
            db
            .query(OpportunitySource)
            .filter(OpportunitySource.opportunity_id == opp.id)
            .order_by(OpportunitySource.id.asc())
            .all()
        )
        return {
            "ok": True,
            "opportunity_id": oid,
            "opportunity_row": {
                "id": opp.id,
                "opportunity_id": opp.opportunity_id,
                "name": opp.name,
                "owner_id": opp.owner_id,
                "status": opp.status,
            },
            "opportunity_sources": [
                {
                    "id": r.id,
                    "source_type": r.source_type,
                    "last_synced_at": r.last_synced_at.isoformat()
                    if r.last_synced_at
                    else None,
                    "sync_checkpoint_preview": (r.sync_checkpoint or "")[:160],
                }
                for r in rows
            ],
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        db.close()


def _maybe_save_json(path_str: str, report: dict[str, Any]) -> None:
    if not (path_str or "").strip():
        return
    path = Path(path_str)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report, indent=2, default=str, ensure_ascii=False)
    path.write_text(text, encoding="utf-8")
    print(f"\nSaved JSON report → {path.resolve()}")


if __name__ == "__main__":
    raise SystemExit(main())
