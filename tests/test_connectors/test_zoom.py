"""Tests for the Zoom connector — OAuth refresh_token flow, pagination, transcript download."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.config import ZoomSettings
from src.connectors.zoom import ZoomConnector, ZoomConnectorError, ZoomNotAuthorizedError
from src.database import init_db
from src.repositories.zoom_repo import ZoomRepository


@pytest.fixture()
def zoom_db(tmp_path: Path) -> str:
    path = str(tmp_path / "zoom_conn_test.db")
    init_db(path)
    return path


@pytest.fixture()
def zoom_settings() -> ZoomSettings:
    return ZoomSettings(
        client_id="test-client",
        client_secret="test-secret",
        redirect_uri="http://localhost:8000/zoom/callback",
        user_id="me",
        enabled=True,
    )


@pytest.fixture()
def connector(zoom_settings: ZoomSettings, zoom_db: str) -> ZoomConnector:
    return ZoomConnector(zoom_settings, db_path=zoom_db)


def _make_response(status_code: int = 200, json_data=None, content: bytes = b"") -> httpx.Response:
    if json_data is not None:
        content = json.dumps(json_data).encode()
    return httpx.Response(
        status_code=status_code,
        content=content,
        headers={"Content-Type": "application/json"},
        request=httpx.Request("GET", "https://api.zoom.us/test"),
    )


@pytest.mark.asyncio
async def test_no_refresh_token_raises(connector: ZoomConnector) -> None:
    """ZoomNotAuthorizedError is raised when no refresh token exists."""
    with pytest.raises(ZoomNotAuthorizedError, match="No Zoom refresh token"):
        await connector._ensure_token()


@pytest.mark.asyncio
async def test_oauth_token_refresh(connector: ZoomConnector, zoom_db: str) -> None:
    """Token is fetched via refresh_token grant."""
    repo = ZoomRepository(zoom_db)
    repo.set_config("zoom_refresh_token", "old-refresh-token")

    token_response = _make_response(200, {
        "access_token": "new-access-token",
        "refresh_token": "new-refresh-token",
        "expires_in": 3600,
    })

    with patch.object(connector, "_get_client") as mock_client:
        client = AsyncMock()
        client.is_closed = False
        mock_client.return_value = client
        client.post = AsyncMock(return_value=token_response)

        token = await connector._ensure_token()

    assert token == "new-access-token"
    # New refresh token should be persisted
    assert repo.get_config("zoom_refresh_token") == "new-refresh-token"


@pytest.mark.asyncio
async def test_oauth_token_cached(connector: ZoomConnector, zoom_db: str) -> None:
    """Token is reused if not expired."""
    import time
    connector._access_token = "cached-token"
    connector._token_expires_at = time.monotonic() + 3600

    token = await connector._ensure_token()
    assert token == "cached-token"


@pytest.mark.asyncio
async def test_oauth_refresh_failure_raises(connector: ZoomConnector, zoom_db: str) -> None:
    """OAuth refresh failure raises ZoomConnectorError."""
    repo = ZoomRepository(zoom_db)
    repo.set_config("zoom_refresh_token", "bad-refresh-token")

    with patch.object(connector, "_get_client") as mock_client:
        client = AsyncMock()
        client.is_closed = False
        mock_client.return_value = client
        client.post = AsyncMock(return_value=_make_response(401, {"error": "invalid_grant"}))

        with pytest.raises(ZoomConnectorError, match="401"):
            await connector._ensure_token()


@pytest.mark.asyncio
async def test_list_recordings_pagination(connector: ZoomConnector, zoom_db: str) -> None:
    """list_recordings auto-paginates via next_page_token."""
    page1 = _make_response(200, {
        "meetings": [{"uuid": "m1", "topic": "Meeting 1"}],
        "next_page_token": "page2",
    })
    page2 = _make_response(200, {
        "meetings": [{"uuid": "m2", "topic": "Meeting 2"}],
        "next_page_token": "",
    })

    import time
    connector._access_token = "test-token"
    connector._token_expires_at = time.monotonic() + 3600

    with patch.object(connector, "_get_client") as mock_client:
        client = AsyncMock()
        client.is_closed = False
        mock_client.return_value = client
        client.request = AsyncMock(side_effect=[page1, page2])

        meetings = await connector.list_recordings("me", "2026-01-01", "2026-01-31")

    assert len(meetings) == 2
    assert meetings[0]["uuid"] == "m1"
    assert meetings[1]["uuid"] == "m2"

    # Verify per-user endpoint is used (not account-level)
    call_args = client.request.call_args_list[0]
    assert "/users/me/recordings" in call_args.args[1]


@pytest.mark.asyncio
async def test_download_transcript(connector: ZoomConnector, zoom_db: str) -> None:
    """download_transcript returns VTT bytes."""
    import time
    connector._access_token = "test-token"
    connector._token_expires_at = time.monotonic() + 3600

    vtt_content = b"WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nHello world"

    with patch.object(connector, "_get_client") as mock_client:
        client = AsyncMock()
        client.is_closed = False
        mock_client.return_value = client
        client.request = AsyncMock(return_value=httpx.Response(
            200, content=vtt_content,
            request=httpx.Request("GET", "https://zoom.us/download"),
        ))

        result = await connector.download_transcript("https://zoom.us/download/transcript.vtt")

    assert result == vtt_content


@pytest.mark.asyncio
async def test_close(connector: ZoomConnector) -> None:
    """close() handles both open and closed clients."""
    # No client yet
    await connector.close()

    # With client
    connector._client = AsyncMock()
    connector._client.is_closed = False
    await connector.close()
    connector._client.aclose.assert_awaited_once()
