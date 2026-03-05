"""Zoom REST API connector with OAuth authorization code flow."""

from __future__ import annotations

import asyncio
import logging
import time
import urllib.parse
from typing import Any

import httpx

from src.config import ZoomSettings
from src.connectors.retry import BACKOFF_BASE, MAX_RETRIES, retry_after_or_backoff

logger = logging.getLogger(__name__)
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
        self._verify_ssl = settings.verify_ssl
        self._client: httpx.AsyncClient | None = None
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0, follow_redirects=True, verify=self._verify_ssl)
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

        for attempt in range(MAX_RETRIES):
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
                    retry_after = retry_after_or_backoff(response.headers, attempt)
                    logger.warning("Zoom rate-limited (429). Retrying after %.1fs", retry_after)
                    await asyncio.sleep(retry_after)
                    continue

                if response.status_code >= 500:
                    wait = BACKOFF_BASE * (2 ** attempt)
                    logger.warning("Zoom server error %d. Retrying in %.1fs", response.status_code, wait)
                    await asyncio.sleep(wait)
                    continue

                if response.status_code >= 400:
                    raise ZoomConnectorError(response.status_code, response.text[:500])

                return response

            except httpx.TransportError as exc:
                last_exc = exc
                wait = BACKOFF_BASE * (2 ** attempt)
                logger.warning("Zoom transport error: %s. Retrying in %.1fs", exc, wait)
                await asyncio.sleep(wait)

        msg = f"Zoom: failed after {MAX_RETRIES} retries on {method} {url}"
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

    async def exchange_authorization_code(
        self, code: str, redirect_uri: str,
    ) -> dict[str, Any]:
        """Exchange an OAuth authorization code for tokens.

        Returns the raw token response dict from Zoom.
        Raises ZoomConnectorError on failure.
        """
        client = await self._get_client()
        resp = await client.post(
            "https://zoom.us/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
            },
            auth=(self._settings.client_id, self._settings.client_secret),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code != 200:
            raise ZoomConnectorError(
                resp.status_code,
                f"OAuth code exchange failed: {resp.text[:500]}",
            )
        return resp.json()

    async def download_transcript(self, download_url: str) -> bytes:
        """Download a transcript file (VTT) from its download URL.

        The download URL includes auth via query param, but we also
        pass the Bearer token for reliability.
        """
        resp = await self._request("GET", download_url, accept="*/*")
        return resp.content

    async def list_past_meetings(
        self,
        user_id: str,
        from_date: str,
        to_date: str,
    ) -> list[dict[str, Any]]:
        """List past scheduled meeting instances within a date range.

        Uses ``GET /users/{userId}/meetings?type=previous_meetings``
        which requires the ``meeting:read:list_meetings:admin`` scope.

        **Limitation:** Only returns pre-scheduled meetings that have ended.
        Instant/ad-hoc meetings are NOT returned by this endpoint.
        Use ``get_meeting_transcript(uuid)`` directly for those.

        Auto-paginates via next_page_token.
        Dates are YYYY-MM-DD strings.
        """
        all_meetings: list[dict[str, Any]] = []
        params: dict[str, Any] = {
            "type": "previous_meetings",
            "from": from_date,
            "to": to_date,
            "page_size": 100,
        }

        url = f"https://api.zoom.us/v2/users/{user_id}/meetings"

        while True:
            resp = await self._request("GET", url, params=params)
            data = resp.json()
            meetings = data.get("meetings", [])
            logger.info(
                "Zoom past meetings: fetched %d (page), total_records=%s",
                len(meetings), data.get("total_records", "?"),
            )
            all_meetings.extend(meetings)

            next_token = data.get("next_page_token", "")
            if not next_token:
                break
            params["next_page_token"] = next_token

        return all_meetings

    @staticmethod
    def _double_encode_uuid(uuid: str) -> str:
        """Double-encode a meeting UUID for use in URL paths.

        Zoom UUIDs that start with ``/`` or contain ``//`` must be
        double-URL-encoded when used as a path parameter.
        """
        if uuid.startswith("/") or "//" in uuid:
            return urllib.parse.quote(urllib.parse.quote(uuid, safe=""), safe="")
        return uuid

    async def get_meeting_transcript(self, meeting_uuid: str) -> dict[str, Any] | None:
        """Get transcript metadata for a past meeting.

        Uses ``GET /meetings/{meetingId}/transcript``.
        Returns the response dict (contains ``download_url``) on success,
        or ``None`` if the meeting has no transcript (404).
        """
        encoded = self._double_encode_uuid(meeting_uuid)
        url = f"https://api.zoom.us/v2/meetings/{encoded}/transcript"

        try:
            resp = await self._request("GET", url)
            return resp.json()
        except ZoomConnectorError as exc:
            if exc.status_code == 404:
                logger.debug("No transcript at /meetings/%s/transcript (404)", meeting_uuid)
                return None
            raise

    async def get_past_meeting_instances(self, meeting_id: str) -> list[dict[str, Any]]:
        """Get past instances of a meeting (recurring or otherwise).

        Uses ``GET /past_meetings/{meetingId}/instances``.
        Returns a list of meeting instance dicts, each with a ``uuid`` field.
        Returns empty list on 404.
        """
        url = f"https://api.zoom.us/v2/past_meetings/{meeting_id}/instances"
        try:
            resp = await self._request("GET", url)
            data = resp.json()
            return data.get("meetings", [])
        except ZoomConnectorError as exc:
            if exc.status_code == 404:
                return []
            raise

    async def download_meeting_transcript(self, download_url: str) -> bytes:
        """Download VTT bytes from a meeting transcript download URL."""
        resp = await self._request("GET", download_url, accept="*/*")
        return resp.content
