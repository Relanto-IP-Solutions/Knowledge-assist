#!/usr/bin/env python3
"""End-to-end test: Google OAuth → Gmail fetch → GCS write.

This script:
1. Checks database connection and creates auth tables if needed
2. Runs OAuth flow (opens browser, captures callback code via local HTTP server)
3. Stores the refresh token in the `users` table
4. Creates a test opportunity and opportunity_source
5. Fetches Gmail threads matching the opportunity OID
6. Writes them to GCS raw/gmail/{thread_id}/thread.json

Usage
-----
    # Run the full flow (OAuth + Gmail sync):
    uv run python scripts/tests_integration/smoke_gmail_oauth_and_gcs.py

    # Skip OAuth if user already exists (just test Gmail→GCS):
    uv run python scripts/tests_integration/smoke_gmail_oauth_and_gcs.py --skip-oauth --email you@example.com

    # Use a specific opportunity ID for Gmail search:
    uv run python scripts/tests_integration/smoke_gmail_oauth_and_gcs.py --opp-id "006Ki000004r26LIAQ"

    # Test with a custom Gmail search query (overrides opp-id based search):
    uv run python scripts/tests_integration/smoke_gmail_oauth_and_gcs.py --query "subject:test"

Requirements
------------
    configs/.env          : PG_HOST, PG_PORT, PG_USER, PG_DATABASE, GCP_PROJECT_ID, GCS_BUCKET_INGESTION
    configs/secrets/.env  : GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, PG_PASSWORD (if needed),
                            GOOGLE_APPLICATION_CREDENTIALS
"""

from __future__ import annotations

import argparse
import http.server
import json
import socketserver
import sys
import threading
import time
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs, urlparse


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _print_section(title: str, width: int = 70) -> None:
    print(f"\n{'=' * width}")
    print(f"  {title}")
    print("=" * width)


def _print_step(step: int, desc: str) -> None:
    print(f"\n[Step {step}] {desc}")
    print("-" * 50)


# ---------------------------------------------------------------------------
# OAuth callback server
# ---------------------------------------------------------------------------

_captured_code: str | None = None
_server_ready = threading.Event()


class OAuthCallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        global _captured_code
        parsed = urlparse(self.path)

        if parsed.path in ("/auth/google/callback", "/oauth/google/callback"):
            query = parse_qs(parsed.query)
            code = query.get("code", [None])[0]
            error = query.get("error", [None])[0]

            if error:
                self.send_response(400)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(f"<h1>OAuth Error</h1><p>{error}</p>".encode())
                return

            if code:
                _captured_code = code
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(
                    b"<h1>Success!</h1>"
                    b"<p>Authorization code received. You can close this tab.</p>"
                    b"<script>window.close();</script>"
                )
                return

        self.send_response(404)
        self.end_headers()

    def log_message(self, fmt, *args):
        pass  # Suppress HTTP logs


def _run_oauth_server(port: int) -> None:
    with socketserver.TCPServer(("", port), OAuthCallbackHandler) as httpd:
        httpd.socket.settimeout(1.0)
        _server_ready.set()
        while _captured_code is None:
            httpd.handle_request()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="End-to-end test: Google OAuth → Gmail → GCS",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--skip-oauth",
        action="store_true",
        help="Skip OAuth flow; use existing user from database.",
    )
    parser.add_argument(
        "--email",
        help="User email (required with --skip-oauth, or shown after OAuth).",
    )
    parser.add_argument(
        "--opp-id",
        dest="opp_id",
        default="oid1",
        help="Opportunity ID — fetches Gmail threads with this in subject (default: oid1).",
    )
    parser.add_argument(
        "--query",
        help="Custom Gmail search query (overrides --opp-id based subject search).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Local port for OAuth callback server (default: 8080).",
    )
    parser.add_argument(
        "--max-threads",
        type=int,
        default=5,
        help="Maximum Gmail threads to sync (default: 5).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    _print_section("GMAIL OAUTH + GCS PIPELINE TEST")
    print(f"  Opportunity ID: {args.opp_id}")
    print(f"  Custom query  : {args.query or '(none, will use subject:{opp_id})'}")
    print(f"  OAuth port    : {args.port}")
    print(f"  Skip OAuth    : {args.skip_oauth}")
    print(f"  Max threads   : {args.max_threads}")

    # -------------------------------------------------------------------------
    # Step 1: Check settings
    # -------------------------------------------------------------------------
    _print_step(1, "Loading settings and checking configuration")

    from configs.settings import get_settings

    settings = get_settings()
    oauth = settings.oauth_plugin
    db_settings = settings.database
    ingestion = settings.ingestion

    missing = []
    if not oauth.google_client_id:
        missing.append("GOOGLE_CLIENT_ID")
    if not oauth.google_client_secret:
        missing.append("GOOGLE_CLIENT_SECRET")
    if not ingestion.gcs_bucket_ingestion:
        missing.append("GCS_BUCKET_INGESTION")

    if missing:
        print(f"  ERROR: Missing required settings: {', '.join(missing)}")
        print("  Add them to configs/secrets/.env or configs/.env")
        return 1

    print(f"  GOOGLE_CLIENT_ID     : {oauth.google_client_id[:20]}...")
    print(f"  GCS_BUCKET_INGESTION : {ingestion.gcs_bucket_ingestion}")
    print(f"  PG_HOST              : {db_settings.pg_host or '(Cloud SQL connector)'}")
    print("  Settings OK.")

    # -------------------------------------------------------------------------
    # Step 2: Check/create database tables
    # -------------------------------------------------------------------------
    _print_step(2, "Checking database connection and auth tables")

    from sqlalchemy import inspect, text

    from src.services.database_manager.orm import Base, get_engine

    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("  Database connection OK.")
    except Exception as e:
        print(f"  ERROR: Database connection failed: {e}")
        print("\n  Troubleshooting:")
        print("    - For local Postgres: ensure PG_HOST, PG_USER, PG_PASSWORD are set")
        print("    - For Cloud SQL: run 'cloud-sql-proxy' and set PG_HOST=127.0.0.1")
        return 1

    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()
    required_tables = ["users", "opportunities", "opportunity_sources"]
    missing_tables = [t for t in required_tables if t not in existing_tables]

    if missing_tables:
        print(f"  Creating missing tables: {missing_tables}")
        Base.metadata.create_all(bind=engine)
        print("  Tables created.")
    else:
        print(f"  Auth tables exist: {required_tables}")

    # -------------------------------------------------------------------------
    # Step 3: OAuth flow (or skip)
    # -------------------------------------------------------------------------
    from sqlalchemy.orm import sessionmaker

    from src.services.database_manager.models.auth_models import (
        Opportunity,
        OpportunitySource,
        User,
    )

    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    user_email: str | None = args.email

    if args.skip_oauth:
        _print_step(3, "Skipping OAuth (--skip-oauth)")
        if not user_email:
            print("  ERROR: --email is required with --skip-oauth")
            return 1
        user = db.query(User).filter(User.email == user_email).first()
        if not user:
            print(f"  ERROR: User {user_email} not found in database.")
            return 1
        if not user.google_refresh_token:
            print(f"  ERROR: User {user_email} has no Google refresh token.")
            print("  Run without --skip-oauth to complete OAuth flow.")
            return 1
        print(f"  Using existing user: {user.email}")
    else:
        _print_step(3, "Running OAuth flow")

        redirect_uri = f"http://localhost:{args.port}/auth/google/callback"
        print(f"  Redirect URI : {redirect_uri}")
        print(f"  Client ID    : {oauth.google_client_id}")
        print(
            "  IMPORTANT: Ensure this URI is in your Google Cloud Console authorized redirects!"
        )

        if not oauth.google_client_id or not oauth.google_client_id.endswith(
            ".apps.googleusercontent.com"
        ):
            print("\n  WARNING: Client ID may be invalid. Expected format:")
            print("    xxxx.apps.googleusercontent.com")

        # Build auth URL
        from urllib.parse import urlencode

        auth_params = {
            "client_id": oauth.google_client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile https://www.googleapis.com/auth/gmail.readonly",
            "access_type": "offline",
            "prompt": "consent",
        }
        auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(
            auth_params
        )

        # Start callback server
        global _captured_code
        _captured_code = None
        server_thread = threading.Thread(
            target=_run_oauth_server, args=(args.port,), daemon=True
        )
        server_thread.start()
        _server_ready.wait(timeout=5)

        print("\n  Opening browser for Google sign-in...")
        print("  (If browser doesn't open, copy and paste this URL manually:)")
        print(f"\n  {auth_url}\n")

        webbrowser.open(auth_url)

        print("\n  Waiting for OAuth callback...")
        timeout = 120
        start = time.time()
        while _captured_code is None and (time.time() - start) < timeout:
            time.sleep(0.5)

        if _captured_code is None:
            print(f"  ERROR: OAuth callback not received within {timeout}s.")
            return 1

        print("  Authorization code received!")

        # Exchange code for tokens
        print("  Exchanging code for tokens...")

        import httpx
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token

        try:
            resp = httpx.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": _captured_code,
                    "client_id": oauth.google_client_id,
                    "client_secret": oauth.google_client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
                timeout=30,
            )
            if resp.status_code != 200:
                print(f"  ERROR: Token exchange failed: {resp.text}")
                return 1

            token_data = resp.json()
            id_token_str = token_data.get("id_token")
            refresh_token = token_data.get("refresh_token")

            if not id_token_str:
                print("  ERROR: No ID token in response.")
                return 1

            # Verify and extract email
            idinfo = id_token.verify_oauth2_token(
                id_token_str,
                google_requests.Request(),
                oauth.google_client_id,
                clock_skew_in_seconds=10,
            )
            user_email = idinfo.get("email")
            user_name = idinfo.get("name")

            print(f"  Authenticated as: {user_email} ({user_name})")

            if not refresh_token:
                print(
                    "  WARNING: No refresh token received (user may have already authorized)."
                )
                print("  To get a new refresh token, revoke access at:")
                print("    https://myaccount.google.com/permissions")

            # Store in database
            user = db.query(User).filter(User.email == user_email).first()
            if not user:
                user = User(email=user_email, name=user_name)
                db.add(user)
                print(f"  Created new user: {user_email}")
            else:
                print(f"  Found existing user: {user_email}")

            if refresh_token:
                user.google_refresh_token = refresh_token
                print("  Stored refresh token.")

            db.commit()

        except Exception as e:
            print(f"  ERROR: OAuth token exchange failed: {e}")
            return 1

    # -------------------------------------------------------------------------
    # Step 4: Create/find opportunity and source
    # -------------------------------------------------------------------------
    _print_step(4, "Setting up test opportunity")

    user = db.query(User).filter(User.email == user_email).first()
    if not user:
        print(f"  ERROR: User {user_email} not found.")
        return 1

    from src.utils.opportunity_id import require_stored_opportunity_id

    opp_key = require_stored_opportunity_id(args.opp_id)

    opp = db.query(Opportunity).filter(Opportunity.opportunity_id == opp_key).first()
    if not opp:
        opp = Opportunity(
            opportunity_id=opp_key,
            name=f"Test Opportunity {opp_key}",
            owner_id=user.id,
        )
        db.add(opp)
        db.commit()
        db.refresh(opp)
        print(f"  Created opportunity: {opp.opportunity_id}")
    else:
        print(f"  Found existing opportunity: {opp.opportunity_id}")

    source = (
        db
        .query(OpportunitySource)
        .filter(
            OpportunitySource.opportunity_id == opp.id,
            OpportunitySource.source_type == "gmail",
        )
        .first()
    )
    if not source:
        source = OpportunitySource(opportunity_id=opp.id, source_type="gmail")
        db.add(source)
        db.commit()
        print("  Created gmail source.")
    else:
        print("  Gmail source exists.")

    # -------------------------------------------------------------------------
    # Step 5: Test Gmail API connection
    # -------------------------------------------------------------------------
    _print_step(5, "Testing Gmail API connection")

    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    if not user.google_refresh_token:
        print("  ERROR: User has no refresh token. Run OAuth flow first.")
        return 1

    creds = Credentials(
        token=None,
        refresh_token=user.google_refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=oauth.google_client_id,
        client_secret=oauth.google_client_secret,
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    )

    try:
        creds.refresh(Request())
        print("  Credentials refreshed successfully.")
    except Exception as e:
        print(f"  ERROR: Failed to refresh credentials: {e}")
        print("  The refresh token may be invalid or revoked.")
        return 1

    try:
        service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        profile = service.users().getProfile(userId="me").execute()
        print(f"  Gmail API connected: {profile.get('emailAddress')}")
        print(f"  Total messages: {profile.get('messagesTotal', 'N/A')}")
    except Exception as e:
        print(f"  ERROR: Gmail API call failed: {e}")
        return 1

    # -------------------------------------------------------------------------
    # Step 6: Search and fetch Gmail threads
    # -------------------------------------------------------------------------
    _print_step(6, "Searching Gmail for matching threads")

    query = args.query or f'subject:"{opp_key}"'
    print(f"  Search query: {query}")

    try:
        list_resp = (
            service
            .users()
            .threads()
            .list(userId="me", q=query, maxResults=args.max_threads)
            .execute()
        )
        threads = list_resp.get("threads") or []
        print(f"  Found {len(threads)} thread(s).")

        if not threads:
            print("\n  No threads found matching the query.")
            print("  To test with real data, either:")
            print(f"    1. Send yourself an email with '{args.opp_id}' in the subject")
            print(
                "    2. Use --query to search for existing emails (e.g. --query 'subject:test')"
            )
            print("\n  Skipping GCS write step (no data to write).")
            return 0

    except Exception as e:
        print(f"  ERROR: Gmail search failed: {e}")
        return 1

    # -------------------------------------------------------------------------
    # Step 7: Write to GCS
    # -------------------------------------------------------------------------
    _print_step(7, "Fetching thread details and writing to GCS")

    from src.services.plugins.gmail_plugin import _build_thread_json
    from src.services.storage.service import Storage

    storage = Storage()
    threads_written = 0

    for thread_meta in threads:
        thread_id = thread_meta.get("id", "")
        if not thread_id:
            continue

        try:
            thread_data = (
                service
                .users()
                .threads()
                .get(userId="me", id=thread_id, format="full")
                .execute()
            )

            thread_json = _build_thread_json(thread_data, opp_key)

            gcs_path = storage.write(
                tier="raw",
                opportunity_id=opp_key,
                source="gmail",
                object_name=f"{thread_id}/thread.json",
                content=json.dumps(thread_json, ensure_ascii=False, indent=2),
                content_type="application/json",
            )

            threads_written += 1
            print(f"  [{threads_written}] Thread: {thread_json['subject'][:50]}...")
            print(f"      Messages: {thread_json['message_count']}")
            print(f"      GCS: {gcs_path}")

        except Exception as e:
            print(f"  ERROR writing thread {thread_id}: {e}")

    # -------------------------------------------------------------------------
    # Step 8: Verify GCS contents
    # -------------------------------------------------------------------------
    _print_step(8, "Verifying GCS contents")

    try:
        objects = storage.list_objects("raw", opp_key, "gmail")
        print(f"  Objects in raw/gmail: {len(objects)}")
        for obj in objects[:10]:
            print(f"    - {obj}")
        if len(objects) > 10:
            print(f"    ... and {len(objects) - 10} more")
    except Exception as e:
        print(f"  WARNING: Could not list GCS objects: {e}")

    # -------------------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------------------
    _print_section("TEST COMPLETED")
    print(f"  User email      : {user_email}")
    print(f"  Opportunity ID  : {opp_key}")
    print(f"  Threads found   : {len(threads)}")
    print(f"  Threads written : {threads_written}")
    print(f"  GCS bucket      : {ingestion.gcs_bucket_ingestion}")
    print(f"  GCS path        : {opp_key}/raw/gmail/")

    if threads_written > 0:
        print("\n  SUCCESS: Gmail → GCS pipeline working!")
        print("\n  Next steps:")
        print("    1. Run the preprocessing pipeline to process these emails")
        print("    2. Run RAG ingestion to index the processed content")
    else:
        print("\n  No threads were written (search returned no results).")

    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
