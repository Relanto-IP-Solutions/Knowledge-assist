"""Knowledge-Assist application single entrypoint."""

from typing import Annotated
from urllib.parse import quote, urlsplit, urlunsplit

import functions_framework
import uvicorn
from typing import Annotated
from urllib.parse import quote, urlsplit, urlunsplit

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import text
from sqlalchemy.orm import Session
from time import perf_counter

from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session
from time import perf_counter

from configs.settings import get_settings
from src.services.database_manager.orm import get_db
from src.services.plugins import oauth_service
from src.apis.routes import (
    admin_routes,
    auth_routes,
    drive_routes,
    gmail_routes,
    onedrive_routes,
    opportunity_routes,
    slack_routes,
    sync_routes,
    team_routes,
    zoom_routes,
)
from src.services.database_manager.orm import get_db
from src.services.plugins import oauth_service
from src.utils.logger import get_logger


logger = get_logger(__name__)
app = FastAPI(
    title="Knowledge-Assist",
    description="Sales Agent application for technical requirements capture",
    version="0.1.0",
)


@app.middleware("http")
async def _process_time_header(request: Request, call_next):
    t0 = perf_counter()
    response = await call_next(request)
    response.headers["X-Process-Time-ms"] = str(int((perf_counter() - t0) * 1000))
    return response


@app.on_event("startup")
def _on_startup() -> None:
    from src.services.auth.firebase_init import ensure_firebase_initialized
    from src.services.database_manager.connection import warm_database_connection_pool
    from src.services.database_manager.orm import warm_sqlalchemy

    ensure_firebase_initialized()
    warm_database_connection_pool()
    warm_sqlalchemy()

# Browser CORS for frontend ↔ API. ``allow_origins=["*"]`` cannot be used with
# ``allow_credentials=True`` (CORS + Starlette); use CORS_ALLOW_ORIGINS with explicit
# URLs when the SPA sends cookies or Authorization with credentials.
_cors_raw = (get_settings().app.cors_allow_origins or "*").strip()
if _cors_raw == "*":
    _cors_origins: list[str] = ["*"]
    _cors_credentials = False
else:
    _cors_origins = [o.strip() for o in _cors_raw.split(",") if o.strip()]
    if not _cors_origins:
        _cors_origins = ["*"]
        _cors_credentials = False
    else:
        _cors_credentials = True

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health/db")
def health_db(db: Annotated[Session, Depends(get_db)]):
    """ORM path smoke test (same engine/session as most routes). No auth."""
    try:
        one = db.execute(text("SELECT 1 AS one")).scalar_one()
        return {"ok": True, "orm": True, "check": int(one)}
    except Exception as exc:
        logger.exception("health_db ORM failed")
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/health/db-raw")
def health_db_raw():
    """Raw pooled connection (same path as firebase_uid lookup in ``firebase_auth``). No auth."""
    from src.services.database_manager.connection import get_db_connection

    try:
        con = get_db_connection()
        try:
            cur = con.cursor()
            cur.execute("SELECT 1 AS one")
            row = cur.fetchone()
            v = row[0] if row else None
            return {"ok": True, "raw": True, "check": v}
        finally:
            con.close()
    except Exception as exc:
        logger.exception("health_db_raw failed")
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _normalize_google_redirect_uri(uri: str) -> str:
    """Normalize callback host to avoid localhost vs 127.0.0.1 mismatches."""
    p = urlsplit(uri)
    host = (p.hostname or "").strip().lower()
    if host != "127.0.0.1":
        return uri
    port = f":{p.port}" if p.port else ""
    netloc = f"localhost{port}"
    return urlunsplit((p.scheme, netloc, p.path, p.query, p.fragment))


@app.get("/auth/google/callback")
async def google_oauth_browser_callback(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    code: str | None = None,
    error: str | None = None,
    state: str | None = None,
):
    """Google redirects the browser here with GET ?code= (must match OAuth client Redirect URI)."""
    if error:
        return JSONResponse({"ok": False, "error": error}, status_code=400)
    if not code:
        return JSONResponse(
            {"ok": False, "error": "missing code"},
            status_code=400,
        )
    provider, oid_from_state = oauth_service.parse_google_oauth_state(state)
    u = request.url
    redirect_uri = _normalize_google_redirect_uri(f"{u.scheme}://{u.netloc}{u.path}")
    try:
        result = await oauth_service.exchange_google_code(
            code, redirect_uri, db, provider=provider
        )
    except Exception as exc:
        logger.warning("Google OAuth exchange failed: {}", exc)
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)

    base = (get_settings().app.frontend_app_url or "").strip().rstrip("/")
    if base and oid_from_state:
        sep = "?"
        dest = f"{base}/projects/{quote(oid_from_state, safe='')}{sep}provider={quote(provider)}"
        return RedirectResponse(url=dest, status_code=302)

    payload = {"ok": True, **result}
    if oid_from_state:
        payload["oid"] = oid_from_state
    return JSONResponse(payload)


app.include_router(auth_routes.router)
app.include_router(auth_routes.external_router)
app.include_router(drive_routes.router)
app.include_router(drive_routes.integrations_drive_router)
app.include_router(gmail_routes.router)
app.include_router(gmail_routes.integrations_gmail_router)
app.include_router(gmail_routes.dashboard_gmail_router)
app.include_router(onedrive_routes.integrations_onedrive_router)
app.include_router(slack_routes.router)
app.include_router(slack_routes.integrations_slack_router)
app.include_router(admin_routes.router)
app.include_router(team_routes.router)
app.include_router(opportunity_routes.router)
app.include_router(opportunity_routes.public_router)
app.include_router(sync_routes.router)
app.include_router(zoom_routes.router)
if __name__ == "__main__":
    settings = get_settings().app
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.env == "development",
        reload_dirs=["src", "configs", "functions"],
    )


@functions_framework.cloud_event
def rag_ingestion(cloud_event):
    from functions.rag_ingestion import handle_pubsub

    return handle_pubsub(cloud_event)


@functions_framework.http
def pubsub_dispatch(request):
    from functions.pubsub_dispatch import handle

    return handle(request)


@functions_framework.http
def gcs_file_processor(request):
    from functions.gcs_file_processor import handle

    return handle(request)
