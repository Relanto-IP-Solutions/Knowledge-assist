"""Zoom API client for OAuth 2.0 and file downloads."""

import base64
import urllib.parse
from typing import Any

import httpx

from configs.settings import get_settings
from src.utils.logger import get_logger


logger = get_logger(__name__)


class ZoomClient:
    """Handles Zoom Server-to-Server OAuth and authenticated downloads."""

    def __init__(self) -> None:
        self.settings = get_settings().zoom
        # Zoom REST API host (same as plugins; avoid ``zoom.us`` vs ``api.zoom.us`` mismatch).
        self.base_url = "https://api.zoom.us/v2"
        self._token: str | None = None

    async def get_access_token(self) -> str:
        """Fetch a Server-to-Server OAuth token from Zoom."""
        if self._token:
            return self._token

        logger.debug("Fetching new Zoom access token")
        url = f"https://zoom.us/oauth/token?grant_type=account_credentials&account_id={self.settings.account_id}"

        # Zoom requires Basic Auth: base64(client_id:client_secret)
        auth_str = f"{self.settings.client_id}:{self.settings.client_secret}"
        encoded_auth = base64.b64encode(auth_str.encode()).decode()

        headers = {
            "Authorization": f"Basic {encoded_auth}",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers)
            response.raise_for_status()
            data = response.json()
            self._token = data["access_token"]
            return self._token

    async def download_file(
        self, download_url: str, override_token: str | None = None
    ) -> bytes:
        """Download a file from Zoom using the Bearer token or an override token."""
        token = override_token or await self.get_access_token()
        # Zoom recommends appending the token as a query parameter instead of an auth header
        # because clients (like httpx) often strip the auth header during redirects to S3.
        separator = "&" if "?" in download_url else "?"
        url_with_token = f"{download_url}{separator}access_token={token}"

        async with httpx.AsyncClient(follow_redirects=True) as client:
            response = await client.get(url_with_token)
            response.raise_for_status()
            return response.content

    async def get_recording_details(
        self, meeting_id_or_uuid: str, access_token: str | None = None
    ) -> dict[str, Any]:
        """Fetch full recording metadata for a meeting."""
        token = access_token or await self.get_access_token()

        import urllib.parse

        clean_id = str(meeting_id_or_uuid)
        # Zoom requires UUIDs to be double URL-encoded ONLY if they contain slashes
        if not clean_id.isdigit():
            # First encode
            clean_id = urllib.parse.quote(clean_id, safe="")
            # Double encode if the original had a slash
            if "/" in str(meeting_id_or_uuid):
                clean_id = urllib.parse.quote(clean_id, safe="")

        url = f"{self.base_url}/meetings/{clean_id}/recordings"
        headers = {"Authorization": f"Bearer {token}"}

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
            if response.status_code >= 400:
                logger.error(
                    "Zoom API /recordings error for {}: {}", clean_id, response.text
                )
            response.raise_for_status()
            return response.json()

    async def list_recordings(
        self,
        from_date: str,
        to_date: str,
        user_id: str = "me",
        page_size: int = 300,
    ) -> list[dict[str, Any]]:
        """List cloud recordings for a user within a date range.

        Uses: GET /users/{userId}/recordings?from=YYYY-MM-DD&to=YYYY-MM-DD
        Returns a flat list of meeting objects (each contains topic, start_time, etc.).
        """
        token = await self.get_access_token()
        headers = {"Authorization": f"Bearer {token}"}

        # ``me`` is literal; emails must be URL-encoded in the path (S2S OAuth).
        _uid = (user_id or "").strip()
        if not _uid or _uid == "me":
            user_path = "me"
        else:
            user_path = urllib.parse.quote(_uid, safe="")

        out: list[dict[str, Any]] = []
        next_page_token: str | None = None

        async with httpx.AsyncClient() as client:
            while True:
                params: dict[str, Any] = {
                    "from": from_date,
                    "to": to_date,
                    "page_size": max(30, min(int(page_size), 300)),
                }
                if next_page_token:
                    params["next_page_token"] = next_page_token
                url = f"{self.base_url}/users/{user_path}/recordings"
                resp = await client.get(url, headers=headers, params=params)
                if resp.status_code >= 400:
                    logger.error(
                        "Zoom API list recordings error: %s %s",
                        resp.status_code,
                        resp.text,
                    )
                resp.raise_for_status()
                data = resp.json() or {}
                meetings = data.get("meetings") or []
                out.extend(m for m in meetings if isinstance(m, dict))
                next_page_token = (data.get("next_page_token") or "").strip() or None
                if not next_page_token:
                    break
        return out

    async def list_users(self, page_size: int = 300) -> list[dict[str, Any]]:
        """List all account users (paginated) for org-wide recording crawl."""
        token = await self.get_access_token()
        headers = {"Authorization": f"Bearer {token}"}
        out: list[dict[str, Any]] = []
        next_page_token: str | None = None

        async with httpx.AsyncClient() as client:
            while True:
                params: dict[str, Any] = {
                    "page_size": max(30, min(int(page_size), 300)),
                }
                if next_page_token:
                    params["next_page_token"] = next_page_token
                url = f"{self.base_url}/users"
                resp = await client.get(url, headers=headers, params=params)
                if resp.status_code >= 400:
                    logger.error(
                        "Zoom API list users error: %s %s",
                        resp.status_code,
                        resp.text,
                    )
                resp.raise_for_status()
                data = resp.json() or {}
                users = data.get("users") or []
                out.extend(u for u in users if isinstance(u, dict))
                next_page_token = (data.get("next_page_token") or "").strip() or None
                if not next_page_token:
                    break
        return out
