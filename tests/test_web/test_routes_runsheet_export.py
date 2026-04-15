"""Tests for the run sheet export route."""

from __future__ import annotations

from io import BytesIO
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.models.dhf import DHFDocument, DocumentStatus
from src.models.release import Release


@pytest.fixture
def client():
    return TestClient(app)


def _make_project(**overrides):
    defaults = {
        "id": 1,
        "name": "Test Project",
        "jira_goal_key": "PROG-1",
        "status": "active",
        "dhf_draft_root_id": "111",
        "dhf_released_root_id": "222",
        "charter_page_id": None,
        "xft_page_id": None,
        "pi_version": None,
        "team_projects": None,
        "jira_plan_url": None,
    }
    defaults.update(overrides)
    obj = MagicMock()
    for k, v in defaults.items():
        setattr(obj, k, v)
    return obj


def _make_release(**overrides):
    defaults = {
        "id": 10,
        "project_id": 1,
        "name": "v1.0",
        "locked": False,
        "created_at": "2026-01-01",
        "version_snapshot": None,
    }
    defaults.update(overrides)
    return Release(**defaults)


def _make_doc(title="Doc A", area="Software"):
    return DHFDocument(
        title=title,
        area=area,
        released_version="1.0",
        draft_version=None,
        status=DocumentStatus.RELEASED,
        last_modified="2026-01-15",
        author="Author",
        page_url="https://example.com",
    )


class TestExportRunsheet:
    @patch("src.web.routes.project.DHFService")
    @patch("src.web.routes.project.ReleaseService")
    @patch("src.web.routes.project.DashboardService")
    @patch("src.web.routes.project.RunsheetExportService")
    def test_export_returns_xlsx(
        self, mock_export_cls, mock_dash_cls, mock_release_cls, mock_dhf_cls, client,
    ):
        project = _make_project()
        release = _make_release()

        mock_dash = MagicMock()
        mock_dash.get_project_by_id.return_value = project
        mock_dash_cls.return_value = mock_dash

        mock_release = MagicMock()
        mock_release.get_release.return_value = release
        mock_release.get_selected_documents.return_value = {"Doc A"}
        mock_release_cls.return_value = mock_release

        mock_dhf = MagicMock()
        mock_dhf.get_dhf_table = AsyncMock(return_value=([_make_doc()], ["Software"]))
        mock_dhf_cls.return_value = mock_dhf

        # Return a real xlsx-like BytesIO
        fake_xlsx = BytesIO(b"PK\x03\x04fake-xlsx-content")
        mock_export = MagicMock()
        mock_export.generate.return_value = fake_xlsx
        mock_export_cls.return_value = mock_export

        with (
            patch("src.web.deps.DashboardService", return_value=mock_dash),
            patch("src.web.deps.ReleaseService", return_value=mock_release),
            patch("src.web.deps.DHFService", return_value=mock_dhf),
            patch("src.web.deps.RunsheetExportService", return_value=mock_export),
        ):
            resp = client.get("/project/1/releases/10/export")

        assert resp.status_code == 200
        assert "spreadsheetml" in resp.headers["content-type"]
        assert "Documentation Run Sheet" in resp.headers["content-disposition"]

    @patch("src.web.deps.DashboardService")
    def test_export_404_missing_project(self, mock_dash_cls, client):
        mock_dash = MagicMock()
        mock_dash.get_project_by_id.return_value = None
        mock_dash.list_projects.return_value = []
        mock_dash_cls.return_value = mock_dash

        with patch("src.web.deps.DashboardService", return_value=mock_dash):
            resp = client.get("/project/999/releases/10/export")

        assert resp.status_code == 404

    @patch("src.web.deps.ReleaseService")
    @patch("src.web.deps.DashboardService")
    def test_export_404_missing_release(self, mock_dash_cls, mock_release_cls, client):
        project = _make_project()
        mock_dash = MagicMock()
        mock_dash.get_project_by_id.return_value = project
        mock_dash.list_projects.return_value = [project]
        mock_dash_cls.return_value = mock_dash

        mock_release = MagicMock()
        mock_release.get_release.return_value = None
        mock_release_cls.return_value = mock_release

        with (
            patch("src.web.deps.DashboardService", return_value=mock_dash),
            patch("src.web.deps.ReleaseService", return_value=mock_release),
        ):
            resp = client.get("/project/1/releases/999/export")

        assert resp.status_code == 404
