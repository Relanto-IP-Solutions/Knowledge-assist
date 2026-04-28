"""OAuth token encryption helpers (mixed plaintext/encrypted safe)."""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet


_ENV_KEY = "OAUTH_ENCRYPTION_KEY"


def _build_local_dev_key() -> str:
    # Deterministic local fallback so developer environments do not break.
    digest = hashlib.sha256(b"knowledge-assist-local-dev-oauth-key").digest()
    return base64.urlsafe_b64encode(digest).decode("utf-8")


def _resolve_key() -> str:
    return (os.getenv(_ENV_KEY) or "").strip() or _build_local_dev_key()


def _get_fernet() -> Fernet:
    return Fernet(_resolve_key().encode("utf-8"))


def is_encrypted(token: str | None) -> bool:
    return bool(token and str(token).startswith("gAAAAA"))


def encrypt(plaintext: str | None) -> str | None:
    if plaintext is None:
        return None
    raw = str(plaintext)
    if not raw:
        return raw
    if is_encrypted(raw):
        return raw
    return _get_fernet().encrypt(raw.encode("utf-8")).decode("utf-8")


def decrypt(ciphertext: str | None) -> str | None:
    if ciphertext is None:
        return None
    raw = str(ciphertext)
    if not raw:
        return raw
    if not is_encrypted(raw):
        return raw
    return _get_fernet().decrypt(raw.encode("utf-8")).decode("utf-8")
