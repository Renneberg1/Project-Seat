"""Zoom REST API connector with OAuth authorization code flow."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from src.config import ZoomSettings

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0
_TOKEN_REFRESH_MARGIN = 300  # refresh 5 min before expiry


class ZoomConnectorError(Exception):
    """Raised when a Zoom API request fails after retries."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(f"Zoom HTTP {status_code}: {message}")


class ZoomNotAuthorizedError(Exception):
    """Raised when no refresh token is available — user must authorize via /zoom/authorize."""


class ZoomConnector:
    """Thin HTTP layer for the Zoom REST API.

    Uses OAuth authorization code flow with refresh tokens.
    The initial authorization is a one-time browser flow; after that
    tokens are refreshed automatically from the stored refresh token.
    Handles token caching, proactive refresh, retry with backoff,
    and pagination via next_page_token.
    """

    def __init__(self, settings: ZoomSettings, *, db_path: str | None = None) -> None:
        self._settings = settings
        self._db_path = db_path
        self._client: httpx.AsyncClient | None = None
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ------------------------------------------------------------------
    # Repository access (lazy import to avoid circular deps)
    # ------------------------------------------------------------------

    def _get_repo(self):
        from src.repositories.zoom_repo import ZoomRepository
        return ZoomRepository(self._db_path)

    # ------------------------------------------------------------------
    # OAuth token management (refresh_token grant)
    # ------------------------------------------------------------------

    async def _ensure_token(self) -> str:
        """Return a valid access token, refreshing if needed."""
        if self._access_token and time.monotonic() < self._token_expires_at:
            return self._access_token

        # Load refresh token from DB
        repo = self._get_repo()
        refresh_token = repo.get_config("zoom_refresh_token")
        if not refresh_token:
            raise ZoomNotAuthorizedError(
                "No Zoom refresh token found. Visit /zoom/inbox and click 'Connect Zoom' to authorize."
            )

        client = await self._get_client()
        resp = await client.post(
            "https://zoom.us/oauth/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            auth=(self._settings.client_id, self._settings.client_secret),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if resp.status_code != 200:
            raise ZoomConnectorError(resp.status_code, f"OAuth token refresh failed: {resp.text[:500]}")

        data = resp.json()
        self._access_token = data["access_token"]
        expires_in = data.get("expires_in", 3600)
        self._token_expires_at = time.monotonic() + expires_in - _TOKEN_REFRESH_MARGIN

        # Zoom rotates refresh tokens — store the new one
        new_refresh = data.get("refresh_token")
        if new_refresh:
            repo.set_config("zoom_refresh_token", new_refresh)

        logger.info("Zoom OAuth token refreshed (expires in %ds)", expires_in)
        return self._access_token

    # ------------------------------------------------------------------
    # Core request with retry
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        accept: str = "application/json",
    ) -> httpx.Response:
        client = await self._get_client()
        last_exc: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            token = await self._ensure_token()
            headers = {"Authorization": f"Bearer {token}", "Accept": accept}

            try:
                response = await client.request(method, url, params=params, headers=headers)

                # Token expired — refresh and retry immediately
                if response.status_code == 401 and attempt == 0:
                    self._access_token = None
                    self._token_expires_at = 0.0
                    continue

                if response.status_code == 429:
                    retry_after = float(response.headers.get("Retry-After", _BACKOFF_BASE * (2 ** attempt)))
                    logger.warning("Zoom rate-limited (429). Retrying after %.1fs", retry_after)
                    await asyncio.sleep(retry_after)
                    continue

                if response.status_code >= 500:
                    wait = _BACKOFF_BASE * (2 ** attempt)
                    logger.warning("Zoom server error %d. Retrying in %.1fs", response.status_code, wait)
                    await asyncio.sleep(wait)
                    continue

                if response.status_code >= 400:
                    raise ZoomConnectorError(response.status_code, response.text[:500])

                return response

            except httpx.TransportError as exc:
                last_exc = exc
                wait = _BACKOFF_BASE * (2 ** attempt)
                logger.warning("Zoom transport error: %s. Retrying in %.1fs", exc, wait)
                await asyncio.sleep(wait)

        msg = f"Zoom: failed after {_MAX_RETRIES} retries on {method} {url}"
        logger.error(msg)
        if last_exc:
            raise ZoomConnectorError(0, msg) from last_exc
        raise ZoomConnectorError(0, msg)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def list_recordings(
        self,
        user_id: str,
        from_date: str,
        to_date: str,
    ) -> list[dict[str, Any]]:
        """List cloud recordings within a date range.

        Uses the per-user endpoint (``/users/{user_id}/recordings``) which
        requires the ``cloud_recording:read:list_user_recordings:admin``
        scope (available in General apps).

        Auto-paginates via next_page_token.
        Dates are YYYY-MM-DD strings.
        """
        all_meetings: list[dict[str, Any]] = []
        params: dict[str, Any] = {
            "from": from_date,
            "to": to_date,
            "page_size": 100,
        }

        url = f"https://api.zoom.us/v2/users/{user_id}/recordings"

        while True:
            resp = await self._request("GET", url, params=params)
            data = resp.json()
            all_meetings.extend(data.get("meetings", []))

            next_token = data.get("next_page_token", "")
            if not next_token:
                break
            params["next_page_token"] = next_token

        return all_meetings

    async def download_transcript(self, download_url: str) -> bytes:
        """Download a transcript file (VTT) from its download URL.

        The download URL includes auth via query param, but we also
        pass the Bearer token for reliability.
        """
        resp = await self._request("GET", download_url, accept="*/*")
        return resp.content
