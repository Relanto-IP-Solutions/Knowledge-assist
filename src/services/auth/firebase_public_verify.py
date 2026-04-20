"""Verify Firebase ID tokens using Google's public x509 keys (no service account JSON).

See Firebase docs: "Verify ID tokens using a third-party JWT library".
"""

from __future__ import annotations

import time
from typing import Any

import jwt
import requests


_GOOGLE_X509_URL = (
    "https://www.googleapis.com/robot/v1/metadata/x509"
    "/securetoken@system.gserviceaccount.com"
)

_cache: dict[str, Any] = {"certs": None, "exp_ts": 0.0}
_MAX_TTL = 3600.0


def _fetch_x509_certs() -> dict[str, str]:
    """Return kid -> PEM string; cached using HTTP Cache-Control max-age when present."""
    now = time.time()
    if _cache["certs"] is not None and now < float(_cache["exp_ts"]):
        return _cache["certs"]

    r = requests.get(_GOOGLE_X509_URL, timeout=15)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict):
        msg = "unexpected cert response shape"
        raise ValueError(msg)

    ttl = _MAX_TTL
    cc = (r.headers.get("Cache-Control") or "").lower()
    if "max-age=" in cc:
        try:
            fragment = next(
                (p.strip() for p in cc.split(",") if "max-age=" in p),
                None,
            )
            if fragment:
                ttl = float(fragment.split("max-age=", 1)[1].split(",", 1)[0].strip())
        except (IndexError, ValueError):
            ttl = _MAX_TTL
    ttl = min(max(ttl, 60.0), _MAX_TTL)

    _cache["certs"] = data
    _cache["exp_ts"] = now + ttl
    return data


def verify_firebase_id_token_public(token: str, project_id: str) -> dict[str, Any]:
    """Verify RS256 signature, ``aud``, ``iss``, and expiry for a Firebase ID token."""
    pid = (project_id or "").strip()
    if not pid:
        raise ValueError("project_id is required")

    try:
        headers = jwt.get_unverified_header(token)
    except jwt.exceptions.PyJWTError as exc:
        raise ValueError(str(exc)) from exc

    kid = headers.get("kid")
    if not kid:
        raise ValueError("missing kid in token header")

    certs = _fetch_x509_certs()
    pem = certs.get(kid)
    if pem is None:
        _cache["certs"] = None
        certs = _fetch_x509_certs()
        pem = certs.get(kid)
    if pem is None:
        raise ValueError("no public key for token kid")

    issuer = f"https://securetoken.google.com/{pid}"
    try:
        return jwt.decode(
            token,
            pem,
            algorithms=["RS256"],
            audience=pid,
            issuer=issuer,
            leeway=10,
        )
    except jwt.exceptions.PyJWTError as exc:
        raise ValueError(str(exc)) from exc
