"""Load Zoom credentials from Google Cloud Secret Manager into ``os.environ``.

Runs when ``configs.settings`` is imported (before ``get_settings()`` is called), so
pydantic sees ``ZOOM_*`` like normal env vars.

**When to use**
- **Local / Cloud Run with explicit GSM fetch**: set ``ZOOM_SECRETS_FROM_SECRET_MANAGER=1`` (or
  ``true``), ``GCP_PROJECT_ID`` (or ``GOOGLE_CLOUD_PROJECT``), and ensure Application Default
  Credentials can call ``secretmanager.versions.access`` (service account key or ``gcloud auth
  application-default login``). Secrets in GSM must be named ``ZOOM_ACCOUNT_ID``, ``ZOOM_CLIENT_ID``,
  ``ZOOM_CLIENT_SECRET``, ``ZOOM_WEBHOOK_SECRET_TOKEN`` (same as env var names).

- **Cloud Run with ``--set-secrets``** (e.g.
  ``ZOOM_ACCOUNT_ID=ZOOM_ACCOUNT_ID:latest``): the platform injects values into the environment
  before the process starts. This module **skips** fetching for any variable that is already
  non-empty.

Existing non-empty ``os.environ`` values are never overwritten.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path


_log = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parents[1]

_ZOOM_KEYS = (
    "ZOOM_ACCOUNT_ID",
    "ZOOM_CLIENT_ID",
    "ZOOM_CLIENT_SECRET",
    "ZOOM_WEBHOOK_SECRET_TOKEN",
)


def _truthy(val: str | None) -> bool:
    if not val:
        return False
    return val.strip().lower() in ("1", "true", "yes", "on")


def _parse_env_file(path: Path, *, override: bool) -> None:
    """Load KEY=VALUE into os.environ (same order as pydantic: configs/.env then secrets/.env)."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if not key:
            continue
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
            val = val[1:-1]
        if override or key not in os.environ:
            os.environ[key] = val


def _load_dotenv_files() -> None:
    _parse_env_file(_ROOT / "configs" / ".env", override=False)
    _parse_env_file(_ROOT / "configs" / "secrets" / ".env", override=True)


def _gcp_project_id() -> str:
    return (
        os.environ.get("GCP_PROJECT_ID")
        or os.environ.get("GOOGLE_CLOUD_PROJECT")
        or os.environ.get("GCLOUD_PROJECT")
        or ""
    ).strip()


def load_zoom_secrets_from_secret_manager() -> None:
    """Populate missing ``ZOOM_*`` env vars from Secret Manager when enabled."""
    _load_dotenv_files()

    if not _truthy(os.environ.get("ZOOM_SECRETS_FROM_SECRET_MANAGER")):
        return

    project = _gcp_project_id()
    if not project:
        _log.warning(
            "ZOOM_SECRETS_FROM_SECRET_MANAGER is set but GCP_PROJECT_ID / "
            "GOOGLE_CLOUD_PROJECT is empty; skipping Secret Manager fetch."
        )
        return

    missing = [k for k in _ZOOM_KEYS if not (os.environ.get(k) or "").strip()]
    if not missing:
        return

    try:
        from google.cloud import secretmanager
    except ImportError as e:
        _log.warning(
            "ZOOM_SECRETS_FROM_SECRET_MANAGER is set but google-cloud-secret-manager "
            "is not installed: %s",
            e,
        )
        return

    client = secretmanager.SecretManagerServiceClient()
    for key in missing:
        name = f"projects/{project}/secrets/{key}/versions/latest"
        try:
            resp = client.access_secret_version(request={"name": name})
            raw = resp.payload.data.decode("utf-8").strip()
            # Strip a single trailing newline common when secrets are pasted
            if raw.endswith("\n") and not raw.endswith("\n\n"):
                raw = raw.rstrip("\n")
            os.environ[key] = raw
            _log.info("Loaded %s from Secret Manager (project=%s)", key, project)
        except Exception as exc:
            _log.warning(
                "Could not load secret %s from Secret Manager (project=%s): %s",
                key,
                project,
                exc,
            )
