"""Tests for the /api/health endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient

from src.main import app


@pytest.fixture
def client(tmp_path):
    db_path = str(tmp_path / "test.db")
    with patch("src.web.routes.health.settings") as mock_settings, \
         patch("src.web.deps.DashboardService"):
        mock_settings.db_path = db_path
        # Init the DB so the check works
        from src.database import init_db
        init_db(db_path)
        yield TestClient(app, raise_server_exceptions=False)


class TestHealthEndpoint:
    def test_all_healthy(self, client):
        with patch("src.web.deps.JiraConnector") as MockJira, \
             patch("src.web.deps.ConfluenceConnector") as MockConf:
            MockJira.return_value.get_myself = AsyncMock(return_value={"accountId": "x"})
            MockJira.return_value.close = AsyncMock()
            MockConf.return_value.get_current_user = AsyncMock(return_value={"accountId": "x"})
            MockConf.return_value.close = AsyncMock()

            resp = client.get("/api/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"
            assert data["db"] is True
            assert data["jira"] is True
            assert data["confluence"] is True

    def test_jira_down(self, client):
        with patch("src.web.deps.JiraConnector") as MockJira, \
             patch("src.web.deps.ConfluenceConnector") as MockConf:
            MockJira.return_value.get_myself = AsyncMock(side_effect=RuntimeError("timeout"))
            MockJira.return_value.close = AsyncMock()
            MockConf.return_value.get_current_user = AsyncMock(return_value={"accountId": "x"})
            MockConf.return_value.close = AsyncMock()

            resp = client.get("/api/health")
            assert resp.status_code == 503
            data = resp.json()
            assert data["status"] == "degraded"
            assert data["db"] is True
            assert data["jira"] is False
            assert data["confluence"] is True

    def test_confluence_down(self, client):
        with patch("src.web.deps.JiraConnector") as MockJira, \
             patch("src.web.deps.ConfluenceConnector") as MockConf:
            MockJira.return_value.get_myself = AsyncMock(return_value={"accountId": "x"})
            MockJira.return_value.close = AsyncMock()
            MockConf.return_value.get_current_user = AsyncMock(side_effect=RuntimeError("timeout"))
            MockConf.return_value.close = AsyncMock()

            resp = client.get("/api/health")
            assert resp.status_code == 503
            data = resp.json()
            assert data["jira"] is True
            assert data["confluence"] is False

    def test_db_down(self, client):
        with patch("src.web.deps.JiraConnector") as MockJira, \
             patch("src.web.deps.ConfluenceConnector") as MockConf, \
             patch("src.web.routes.health.get_db", side_effect=RuntimeError("db error")):
            MockJira.return_value.get_myself = AsyncMock(return_value={"accountId": "x"})
            MockJira.return_value.close = AsyncMock()
            MockConf.return_value.get_current_user = AsyncMock(return_value={"accountId": "x"})
            MockConf.return_value.close = AsyncMock()

            resp = client.get("/api/health")
            assert resp.status_code == 503
            data = resp.json()
            assert data["db"] is False
