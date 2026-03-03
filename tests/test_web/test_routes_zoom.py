"""Tests for Zoom OAuth routes and backward-compat redirects.

Inbox, triage, sync, dismiss, retry, and reanalyse tests have moved to
``test_routes_meetings.py``.
"""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest

from src.config import Settings, AtlassianSettings, LLMSettings, ZoomSettings
from src.database import init_db
from src.repositories.zoom_repo import ZoomRepository


@pytest.fixture()
def zoom_db(tmp_path: Path) -> str:
    path = str(tmp_path / "zoom_test.db")
    init_db(path)
    return path


@pytest.fixture()
def zoom_repo(zoom_db: str) -> ZoomRepository:
    return ZoomRepository(zoom_db)


@pytest.fixture()
def zoom_settings() -> ZoomSettings:
    return ZoomSettings(
        client_id="test-client-id",
        client_secret="test-client-secret",
        redirect_uri="http://localhost:8000/zoom/callback",
        user_id="me",
        enabled=True,
    )


@pytest.fixture()
def client_with_zoom(zoom_db: str, zoom_repo: ZoomRepository, zoom_settings: ZoomSettings):
    from starlette.testclient import TestClient
    from src.main import app

    settings = Settings(
        atlassian=AtlassianSettings(domain="test", email="test@test.com", api_token="fake"),
        llm=LLMSettings(),
        zoom=zoom_settings,
        db_path=zoom_db,
    )

    with patch("src.config.settings", settings):
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


# ------------------------------------------------------------------
# Backward-compat redirect tests
# ------------------------------------------------------------------

def test_zoom_inbox_redirects_to_meetings(client_with_zoom) -> None:
    """GET /zoom/inbox redirects to /meetings/."""
    resp = client_with_zoom.get("/zoom/inbox", follow_redirects=False)
    assert resp.status_code == 302
    assert "/meetings/" in resp.headers["location"]


def test_zoom_triage_redirects_to_meetings(client_with_zoom) -> None:
    """GET /zoom/triage redirects to /meetings/."""
    resp = client_with_zoom.get("/zoom/triage", follow_redirects=False)
    assert resp.status_code == 302
    assert "/meetings/" in resp.headers["location"]


# ------------------------------------------------------------------
# OAuth authorize tests
# ------------------------------------------------------------------

def test_authorize_redirects_to_zoom(client_with_zoom) -> None:
    """GET /zoom/authorize redirects to Zoom consent screen."""
    resp = client_with_zoom.get("/zoom/authorize", follow_redirects=False)
    assert resp.status_code == 302
    location = resp.headers["location"]
    assert "zoom.us/oauth/authorize" in location
    assert "client_id=test-client-id" in location
    assert "redirect_uri=" in location
    assert "response_type=code" in location
    assert "state=" in location


def test_authorize_stores_state(client_with_zoom, zoom_repo: ZoomRepository) -> None:
    """Authorize stores oauth state in config table."""
    client_with_zoom.get("/zoom/authorize", follow_redirects=False)
    stored = zoom_repo.get_config("zoom_oauth_state")
    assert stored is not None
    parts = stored.split(":")
    assert len(parts) == 2


# ------------------------------------------------------------------
# OAuth callback tests
# ------------------------------------------------------------------

def test_callback_exchanges_code(client_with_zoom, zoom_repo: ZoomRepository) -> None:
    """Callback exchanges code, stores refresh token, redirects to meetings."""
    state = "abc123"
    zoom_repo.set_config("zoom_oauth_state", f"{state}:{int(time.time())}")

    token_response = {
        "access_token": "new-access",
        "refresh_token": "new-refresh",
        "expires_in": 3600,
    }

    with patch("src.web.routes.zoom.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=None)

        import httpx as _httpx
        mock_client.post = AsyncMock(return_value=_httpx.Response(
            200,
            content=__import__("json").dumps(token_response).encode(),
            headers={"Content-Type": "application/json"},
            request=_httpx.Request("POST", "https://zoom.us/oauth/token"),
        ))

        resp = client_with_zoom.get(f"/zoom/callback?code=authcode123&state={state}", follow_redirects=False)

    assert resp.status_code == 302
    assert "/meetings/?connected=1" in resp.headers["location"]
    assert zoom_repo.get_config("zoom_refresh_token") == "new-refresh"
    assert zoom_repo.get_config("zoom_oauth_state") is None


def test_callback_rejects_invalid_state(client_with_zoom, zoom_repo: ZoomRepository) -> None:
    """Callback rejects mismatched state."""
    zoom_repo.set_config("zoom_oauth_state", f"real-state:{int(time.time())}")

    resp = client_with_zoom.get("/zoom/callback?code=authcode&state=wrong-state", follow_redirects=False)
    assert resp.status_code == 302
    assert "error=state_mismatch" in resp.headers["location"]


def test_callback_rejects_expired_state(client_with_zoom, zoom_repo: ZoomRepository) -> None:
    """Callback rejects expired state (>10 minutes)."""
    state = "expired-state"
    old_ts = int(time.time()) - 700  # 11+ minutes ago
    zoom_repo.set_config("zoom_oauth_state", f"{state}:{old_ts}")

    resp = client_with_zoom.get(f"/zoom/callback?code=authcode&state={state}", follow_redirects=False)
    assert resp.status_code == 302
    assert "error=state_expired" in resp.headers["location"]


def test_callback_missing_state(client_with_zoom) -> None:
    """Callback rejects when no state is stored."""
    resp = client_with_zoom.get("/zoom/callback?code=authcode&state=anything", follow_redirects=False)
    assert resp.status_code == 302
    assert "error=missing_state" in resp.headers["location"]
