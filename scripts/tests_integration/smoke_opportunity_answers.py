#!/usr/bin/env python3
"""Smoke: GET + POST ``/opportunities/{opportunity_id}/answers``; optional GET ``/questions``.

Endpoints (FastAPI)::

  GET  /opportunities/{oid}/answers
  POST /opportunities/{opportunity_id}/answers
  GET  /opportunities/{oid}/questions   (``--get-questions`` or ``--questions-only``)

GET/POST responses include ``answer_type`` and ``requirement_type`` from ``sase_questions``
(``q_id`` matches ``answers.question_id``).

Use ``--save-json PATH`` to write the full HTTP report (status + bodies) for inspection.

POST supports the **flat** body shape from ``SaveOrResolveAnswersInput`` (see ``/docs``)::

  {
    "question_id": "<q_id from sase_questions / GET questions>",
    "action": "INSERT",
    "answers": [{"value": "...", "confidence": 0.9, "metadata": {}}]
  }

Requires
--------
  API reachable; DB with ``sase_questions`` / ``answers`` as expected.
  Uses only the Python standard library for HTTP (no ``httpx`` / ``requests``).

Examples
--------
  # GET only (print full JSON)
  python scripts/tests_integration/smoke_opportunity_answers.py --opportunity-id oid0011

  # Cloud Run (private) + user identity token — do NOT pass --audiences to gcloud manually
  python scripts/tests_integration/smoke_opportunity_answers.py \\
    --base-url https://YOUR-SERVICE.run.app --opportunity-id oid0011 --identity-token

  # POST sample INSERT (optional; set --question-id to a real q_id)
  python scripts/tests_integration/smoke_opportunity_answers.py \\
    --opportunity-id oid0011 --question-id QID-001 --post-insert-sample

  # Save API responses to JSON (GET answers, optional questions, optional POST)
  python scripts/tests_integration/smoke_opportunity_answers.py -o oid0011 \\
    --save-json output/answers_smoke.json

  # Only GET /opportunities/{id}/questions (answer_type, requirement_type, option_values)
  python scripts/tests_integration/smoke_opportunity_answers.py -o oid0011 --questions-only

If ``uv run`` fails on Windows with "Access is denied" on ``.venv``:
  - Close editors using the venv; pause OneDrive on this folder; or run:
    ``.venv\\Scripts\\python.exe scripts/tests_integration/smoke_opportunity_answers.py ...``
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
from urllib.parse import quote


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
    """Mint an ID token for calling private Cloud Run.

    With **user** login (``gcloud auth login``), use **no** ``--audiences`` — that flag
    only works with **service account impersonation** (see gcloud error
    "Invalid account type for --audiences").

    If you use ``--impersonate-service-account``, pass ``audience`` = your Cloud Run URL
    so the token is accepted.
    """
    exe = shutil.which("gcloud") or shutil.which("gcloud.cmd")
    if not exe:
        raise RuntimeError(
            "gcloud not found in PATH. Install Google Cloud SDK or use --token manually."
        )
    cmd = [exe, "auth", "print-identity-token"]
    if impersonate_sa:
        cmd.append(f"--impersonate-service-account={impersonate_sa}")
        if audience:
            cmd.append(f"--audiences={audience.rstrip('/')}")
    return subprocess.check_output(cmd, text=True, timeout=120).strip()


def _http_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout: float = 120.0,
) -> tuple[int, Any]:
    """Return (status_code, parsed JSON or raw text). Uses stdlib only."""
    h = dict(headers or {})
    data: bytes | None = None
    if json_body is not None:
        data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method.upper(), headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        status = e.code
        raw = e.read().decode("utf-8", errors="replace")
    except urllib.error.URLError as e:
        print(f"ERROR: request failed: {e}", file=sys.stderr)
        raise
    try:
        body: Any = json.loads(raw) if raw.strip() else None
    except json.JSONDecodeError:
        body = raw
    return status, body


def _save_report_json(path_str: str, report: dict[str, Any]) -> None:
    if not (path_str or "").strip():
        return
    path = Path(path_str)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, default=str, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nSaved JSON report → {path.resolve()}")


def _pretty(data: Any, limit: int = 200_000) -> str:
    try:
        s = json.dumps(data, indent=2, default=str, ensure_ascii=False)
    except TypeError:
        s = str(data)
    if len(s) > limit:
        return s[:limit] + f"\n... [{len(s) - limit} chars truncated]"
    return s


def main() -> int:
    p = argparse.ArgumentParser(
        description=(
            "Smoke: GET/POST /opportunities/{id}/answers; optional GET /opportunities/{id}/questions "
            "(use --questions-only for questions only)."
        ),
    )
    default_base = (
        os.environ.get("SMOKE_API_BASE_URL")
        or os.environ.get("API_BASE_URL")
        or "http://0.0.0.0:8080"
    ).rstrip("/")
    p.add_argument(
        "--base-url", default=default_base, help="API root (no trailing slash)"
    )
    p.add_argument("--opportunity-id", "-o", required=True, help="e.g. oid0011")
    p.add_argument("--token", default=os.environ.get("SMOKE_API_TOKEN", ""))
    p.add_argument(
        "--identity-token",
        action="store_true",
        help="Authorization: Bearer from gcloud auth print-identity-token (user login; no --audiences).",
    )
    p.add_argument(
        "--impersonate-service-account",
        metavar="EMAIL",
        default="",
        help=(
            "If set, adds --impersonate-service-account=... and --audiences=<base-url> "
            "(for SA tokens; user accounts cannot use --audiences alone)."
        ),
    )
    p.add_argument("--timeout", type=float, default=120.0)
    p.add_argument(
        "--questions-only",
        action="store_true",
        help="Only GET /opportunities/{id}/questions (skip GET /answers).",
    )
    p.add_argument(
        "--get-questions",
        action="store_true",
        help="After GET /answers, also GET /opportunities/{id}/questions (ignored if --questions-only).",
    )
    p.add_argument(
        "--post-insert-sample",
        action="store_true",
        help="After GET, POST a minimal INSERT (needs --question-id).",
    )
    p.add_argument(
        "--question-id",
        "-q",
        default="",
        help="sase_questions.q_id for INSERT sample",
    )
    p.add_argument(
        "--save-json",
        metavar="PATH",
        default="",
        help="Write all HTTP responses (status + body) to this JSON file.",
    )
    args = p.parse_args()

    base = args.base_url.rstrip("/")
    oid = args.opportunity_id.strip()
    oid_enc = quote(oid, safe="")

    headers: dict[str, str] = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    token = (args.token or "").strip()
    if args.identity_token:
        try:
            imp = (args.impersonate_service_account or "").strip()
            token = _gcloud_identity_token(
                impersonate_sa=imp or None,
                audience=base if imp else None,
            )
        except (RuntimeError, subprocess.CalledProcessError, OSError) as e:
            print(f"ERROR: identity token: {e}", file=sys.stderr)
            return 1
    if token:
        headers["Authorization"] = f"Bearer {token}"

    if args.questions_only and args.post_insert_sample:
        print(
            "ERROR: --questions-only cannot be combined with --post-insert-sample.",
            file=sys.stderr,
        )
        return 1

    report: dict[str, Any] = {
        "opportunity_id": oid,
        "base_url": base,
        "note": (
            "Structured logs from plugins run on the API server (uvicorn / Cloud Run), "
            "not in this script — set LOG_LEVEL=info or check Cloud Logging."
        ),
        "endpoints": {},
    }

    if args.questions_only:
        print("=" * 72)
        print(f"GET /opportunities/{oid}/questions")
        print("=" * 72)
        url_q = f"{base}/opportunities/{oid_enc}/questions"
        try:
            st_q, body_q = _http_json(
                url_q, method="GET", headers=headers, timeout=args.timeout
            )
        except urllib.error.URLError:
            return 1
        print(f"status={st_q}")
        print(_pretty(body_q))
        report["endpoints"]["get_questions"] = {
            "http_status": st_q,
            "url": url_q,
            "body": body_q,
        }
        _save_report_json(args.save_json, report)
        return 0

    print("=" * 72)
    print(f"GET /opportunities/{oid}/answers")
    print("=" * 72)
    url_answers = f"{base}/opportunities/{oid_enc}/answers"
    try:
        status, body = _http_json(
            url_answers, method="GET", headers=headers, timeout=args.timeout
        )
    except urllib.error.URLError:
        return 1
    print(f"status={status}")
    print(_pretty(body))
    report["endpoints"]["get_answers"] = {
        "http_status": status,
        "url": url_answers,
        "body": body,
    }

    if args.get_questions:
        print("\n" + "=" * 72)
        print(f"GET /opportunities/{oid}/questions")
        print("=" * 72)
        url_q = f"{base}/opportunities/{oid_enc}/questions"
        try:
            st_q, body_q = _http_json(
                url_q, method="GET", headers=headers, timeout=args.timeout
            )
        except urllib.error.URLError:
            _save_report_json(args.save_json, report)
            return 1
        print(f"status={st_q}")
        print(_pretty(body_q))
        report["endpoints"]["get_questions"] = {
            "http_status": st_q,
            "url": url_q,
            "body": body_q,
        }

    if args.post_insert_sample:
        qid = (args.question_id or "").strip()
        if not qid:
            print(
                "\nERROR: --question-id is required for --post-insert-sample "
                "(use --get-questions to list q_id values).",
                file=sys.stderr,
            )
            _save_report_json(args.save_json, report)
            return 1
        payload = {
            "question_id": qid,
            "action": "INSERT",
            "answers": [
                {
                    "value": "Smoke test answer from smoke_opportunity_answers.py",
                    "confidence": 0.5,
                    "metadata": {"source": "smoke_opportunity_answers.py"},
                }
            ],
        }
        print("\n" + "=" * 72)
        print(f"POST /opportunities/{oid}/answers")
        print("=" * 72)
        print("request body:", _pretty(payload)[:4000])
        try:
            st_p, body_p = _http_json(
                url_answers,
                method="POST",
                headers=headers,
                json_body=payload,
                timeout=args.timeout,
            )
        except urllib.error.URLError:
            _save_report_json(args.save_json, report)
            return 1
        print(f"status={st_p}")
        print(_pretty(body_p))
        report["endpoints"]["post_answers_insert_sample"] = {
            "http_status": st_p,
            "url": url_answers,
            "request": payload,
            "body": body_p,
        }

    _save_report_json(args.save_json, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
