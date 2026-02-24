"""Tests for project settings routes."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from src.database import init_db, get_db
from src.models.project import Project


@pytest.fixture
def tmp_db(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO projects (jira_goal_key, name, status, phase, team_projects, confluence_ceo_review_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("PROG-1", "Test Project", "active", "development", json.dumps({"AIM": "Drop 1"}), "99999"),
        )
        conn.commit()
    return db_path


@pytest.fixture
def project(tmp_db):
    with get_db(tmp_db) as conn:
        row = conn.execute("SELECT * FROM projects WHERE id = 1").fetchone()
    return Project.from_row(row)


@pytest.fixture
def client(tmp_db):
    from starlette.testclient import TestClient

    with patch("src.main.init_db"), \
         patch("src.main.orchestrator"), \
         patch("src.web.deps.DashboardService") as MockDash, \
         patch("src.web.routes.settings.app_settings") as MockSettings:
        MockDash.return_value.list_projects.return_value = []
        MockSettings.db_path = tmp_db
        from src.main import app
        app.state.testing = True
        yield TestClient(app, raise_server_exceptions=False)


class TestSettingsPage:
    def test_get_settings(self, client, tmp_db, project):
        with patch("src.web.routes.settings.DashboardService") as MockDash:
            MockDash.return_value.get_project_by_id.return_value = project
            resp = client.get(f"/project/{project.id}/settings/")
            assert resp.status_code == 200
            assert "Project Settings" in resp.text
            assert "PROG-1" in resp.text
            assert "Test Project" in resp.text

    def test_get_settings_not_found(self, client, tmp_db):
        with patch("src.web.routes.settings.DashboardService") as MockDash:
            MockDash.return_value.get_project_by_id.return_value = None
            resp = client.get("/project/999/settings/")
            assert resp.status_code == 404

    def test_save_settings(self, client, tmp_db, project):
        with patch("src.web.routes.settings.DashboardService") as MockDash:
            MockDash.return_value.get_project_by_id.return_value = project

            resp = client.post(
                f"/project/{project.id}/settings/",
                data={
                    "name": "Updated Name",
                    "jira_goal_key": "PROG-1",
                    "phase": "verification",
                    "confluence_charter_id": "111",
                    "confluence_xft_id": "222",
                    "confluence_ceo_review_id": "333",
                    "dhf_draft_root_id": "444",
                    "dhf_released_root_id": "555",
                    "pi_version": "PI 25.1",
                    "jira_plan_url": "https://example.com/plan",
                    "team_projects": "AIM=Drop 2\nCTCV=Release 3",
                },
            )
            assert resp.status_code == 200
            assert "Settings saved" in resp.text

        # Verify DB was updated
        with get_db(tmp_db) as conn:
            row = conn.execute("SELECT * FROM projects WHERE id = 1").fetchone()
        assert row["name"] == "Updated Name"
        assert row["phase"] == "verification"
        assert row["confluence_ceo_review_id"] == "333"
        assert row["dhf_draft_root_id"] == "444"
        assert row["pi_version"] == "PI 25.1"
        teams = json.loads(row["team_projects"])
        assert teams == {"AIM": "Drop 2", "CTCV": "Release 3"}

    def test_save_clears_optional_fields(self, client, tmp_db, project):
        """Empty optional fields should be set to NULL."""
        with patch("src.web.routes.settings.DashboardService") as MockDash:
            MockDash.return_value.get_project_by_id.return_value = project

            resp = client.post(
                f"/project/{project.id}/settings/",
                data={
                    "name": "Test Project",
                    "jira_goal_key": "PROG-1",
                    "phase": "development",
                    "confluence_charter_id": "",
                    "confluence_xft_id": "",
                    "confluence_ceo_review_id": "",
                    "dhf_draft_root_id": "",
                    "dhf_released_root_id": "",
                    "pi_version": "",
                    "jira_plan_url": "",
                    "team_projects": "",
                },
            )
            assert resp.status_code == 200

        with get_db(tmp_db) as conn:
            row = conn.execute("SELECT * FROM projects WHERE id = 1").fetchone()
        assert row["confluence_ceo_review_id"] is None
        assert row["pi_version"] is None
