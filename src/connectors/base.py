"""Base connector with authentication, retry, pagination, and rate-limit handling."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from src.config import Settings, settings as default_settings

logger = logging.getLogger(__name__)

# Retry defaults
_MAX_RETRIES = 3
_BACKOFF_BASE = 1.0  # seconds
_RATE_LIMIT_STATUS = 429


class ConnectorError(Exception):
    """Raised when an API request fails after retries."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}: {message}")


class BaseConnector:
    """Thin HTTP layer shared by all Atlassian connectors.

    Handles:
    - Basic auth (email + API token)
    - Automatic retry with exponential backoff
    - Rate-limit (429) back-off using Retry-After header
    - JSON pagination (startAt / maxResults pattern for Jira,
      start / limit + _links.next for Confluence)
    - Structured error logging
    """

    def __init__(self, base_url: str, *, settings: Settings | None = None) -> None:
        cfg = settings or default_settings
        self._base_url = base_url.rstrip("/")
        self._auth = (cfg.atlassian.email, cfg.atlassian.api_token)
        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                auth=self._auth,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ------------------------------------------------------------------
    # Core request with retry
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> httpx.Response:
        client = await self._get_client()
        last_exc: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                response = await client.request(method, path, params=params, json=json_body)

                # Rate limit
                if response.status_code == _RATE_LIMIT_STATUS:
                    retry_after = float(response.headers.get("Retry-After", _BACKOFF_BASE * (2**attempt)))
                    logger.warning("Rate-limited (429). Retrying after %.1fs (attempt %d)", retry_after, attempt + 1)
                    await asyncio.sleep(retry_after)
                    continue

                # Server errors worth retrying
                if response.status_code >= 500:
                    wait = _BACKOFF_BASE * (2**attempt)
                    logger.warning(
                        "Server error %d on %s %s. Retrying in %.1fs (attempt %d)",
                        response.status_code,
                        method,
                        path,
                        wait,
                        attempt + 1,
                    )
                    await asyncio.sleep(wait)
                    continue

                # Client errors -> fail immediately
                if response.status_code >= 400:
                    body = response.text[:500]
                    logger.error("Client error %d on %s %s: %s", response.status_code, method, path, body)
                    raise ConnectorError(response.status_code, body)

                return response

            except httpx.TransportError as exc:
                last_exc = exc
                wait = _BACKOFF_BASE * (2**attempt)
                logger.warning("Transport error on %s %s: %s. Retrying in %.1fs", method, path, exc, wait)
                await asyncio.sleep(wait)

        # Exhausted retries
        msg = f"Failed after {_MAX_RETRIES} retries on {method} {path}"
        logger.error(msg)
        if last_exc:
            raise ConnectorError(0, msg) from last_exc
        raise ConnectorError(0, msg)

    # ------------------------------------------------------------------
    # Convenience verbs
    # ------------------------------------------------------------------

    async def get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        resp = await self._request("GET", path, params=params)
        return resp.json()

    async def post(self, path: str, *, json_body: dict[str, Any] | None = None) -> dict[str, Any]:
        resp = await self._request("POST", path, json_body=json_body)
        return resp.json()

    async def put(self, path: str, *, json_body: dict[str, Any] | None = None) -> dict[str, Any]:
        resp = await self._request("PUT", path, json_body=json_body)
        return resp.json()

    async def delete(self, path: str) -> None:
        await self._request("DELETE", path)

    # ------------------------------------------------------------------
    # Pagination helpers
    # ------------------------------------------------------------------

    async def post_all_jira(
        self,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        results_key: str = "issues",
        page_size: int = 50,
    ) -> list[dict[str, Any]]:
        """Paginate through a Jira POST endpoint that uses nextPageToken."""
        body = dict(body or {})
        body["maxResults"] = page_size
        all_results: list[dict[str, Any]] = []

        next_token: str | None = None
        while True:
            if next_token:
                body["nextPageToken"] = next_token
            data = await self.post(path, json_body=body)
            results = data.get(results_key, [])
            all_results.extend(results)

            next_token = data.get("nextPageToken")
            if not next_token or not results:
                break

        return all_results

    async def get_all_confluence(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        results_key: str = "results",
        page_size: int = 25,
    ) -> list[dict[str, Any]]:
        """Paginate through a Confluence endpoint that uses start/limit + _links.next."""
        params = dict(params or {})
        params["limit"] = page_size
        start = 0
        all_results: list[dict[str, Any]] = []

        while True:
            params["start"] = start
            data = await self.get(path, params=params)
            results = data.get(results_key, [])
            all_results.extend(results)

            # Confluence signals more pages via _links.next
            links = data.get("_links", {})
            if "next" not in links or not results:
                break
            start += len(results)

        return all_results
