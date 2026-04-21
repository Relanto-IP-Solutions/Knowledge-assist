"""Initialize the Firebase Admin SDK once per process (used for ID token verification)."""

from __future__ import annotations

from pathlib import Path

import firebase_admin
from firebase_admin import credentials

from configs.settings import ROOT_DIR, get_settings
from src.utils.logger import get_logger


logger = get_logger(__name__)


def _resolve_path_from_project_root(raw: str) -> Path:
    """Resolve env paths relative to repo root (not shell cwd)."""
    p = Path(raw.strip())
    if p.is_absolute():
        return p
    return (ROOT_DIR / p).resolve()


def ensure_firebase_initialized() -> None:
    """Load the service account and call ``initialize_app`` if not already done."""
    try:
        firebase_admin.get_app()
    except ValueError:
        pass
    else:
        return

    raw = (get_settings().firebase_auth.service_account_path or "").strip()
    if not raw:
        logger.warning(
            "FIREBASE_SERVICE_ACCOUNT_PATH is not set; using FIREBASE_PROJECT_ID "
            "for public-key token verification if configured, else protected routes return 503."
        )
        return

    path = _resolve_path_from_project_root(raw)
    if not path.is_file():
        logger.error(
            "FIREBASE_SERVICE_ACCOUNT_PATH file not found: {} (from env: {})",
            path,
            raw,
        )
        return

    cred = credentials.Certificate(str(path))
    firebase_admin.initialize_app(cred)
    logger.info(
        "Firebase Admin SDK initialized from FIREBASE_SERVICE_ACCOUNT_PATH={}",
        path,
    )
