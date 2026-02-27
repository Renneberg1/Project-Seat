"""Tests for CEO Review route contracts."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.database import init_db, get_db
from src.models.project import Project


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_db(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO projects (jira_goal_key, name, status, phase, team_projects, confluence_ceo_review_id) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("PROG-1", "Test Project", "active", "development", json.dumps([["AIM", "Drop 1"]]), "99999"),
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
         patch("src.web.deps.DashboardService") as MockDash:
        MockDash.return_value.list_projects.return_value = []
        from src.main import app
        app.state.testing = True
        yield TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Route tests
# ---------------------------------------------------------------------------


class TestRoutes:
    """Test CEO Review route contracts."""

    def test_main_page(self, client, tmp_db, project):
        with patch("src.web.deps.DashboardService") as MockDash, \
             patch("src.web.deps.CeoReviewService") as MockSvc:
            MockDash.return_value.get_project_by_id.return_value = project
            MockSvc.return_value.list_reviews.return_value = []

            resp = client.get(f"/project/{project.id}/ceo-review/")
            assert resp.status_code == 200
            assert "CEO Review" in resp.text

    def test_main_page_not_found(self, client, tmp_db):
        with patch("src.web.deps.DashboardService") as MockDash:
            MockDash.return_value.get_project_by_id.return_value = None
            resp = client.get("/project/999/ceo-review/")
            assert resp.status_code == 404

    def test_ask_returns_questions(self, client, tmp_db, project):
        questions = [{"question": "Why?", "category": "Dev", "why_needed": "Context"}]
        metrics = {"project_name": "Test"}

        with patch("src.web.deps.DashboardService") as MockDash, \
             patch("src.web.deps.CeoReviewService") as MockSvc:
            MockDash.return_value.get_project_by_id.return_value = project
            MockSvc.return_value.generate_questions = AsyncMock(
                return_value=(questions, metrics)
            )

            resp = client.post(
                f"/project/{project.id}/ceo-review/ask",
                data={"pm_notes": "Sprint delayed"},
            )
            assert resp.status_code == 200
            assert "Why?" in resp.text

    def test_analyze_returns_preview(self, client, tmp_db, project):
        review = {
            "health_indicator": "On Track",
            "summary": "Steady progress across all teams.",
            "bullets": ["Dev on track.", "Docs complete."],
            "escalations": [],
            "next_milestones": ["Ship"],
            "deep_dive_topics": [],
            "metrics": {"project_name": "Test", "new_decisions": [], "new_risks": [],
                        "team_progress": [], "sp_burned_2w": 0, "scope_change_2w": 0,
                        "dhf_total": 0, "dhf_released": 0, "dhf_completion_pct": 0,
                        "dhf_recently_updated": [], "open_risk_count": 0, "total_risk_count": 0},
        }

        with patch("src.web.deps.DashboardService") as MockDash, \
             patch("src.web.deps.CeoReviewService") as MockSvc, \
             patch("src.web.routes.ceo_review.resolve_confluence_mentions", new_callable=AsyncMock) as mock_resolve, \
             patch("src.web.deps.JiraConnector") as MockJira:
            MockDash.return_value.get_project_by_id.return_value = project
            MockSvc.return_value.generate_review = AsyncMock(return_value=review)
            MockSvc.return_value.render_confluence_xhtml.return_value = "<h1>test</h1>"
            MockSvc.return_value.save_review.return_value = 1
            mock_resolve.side_effect = lambda text, jira: text
            MockJira.return_value.close = AsyncMock()

            resp = client.post(
                f"/project/{project.id}/ceo-review/analyze",
                data={"pm_notes": ""},
            )
            assert resp.status_code == 200
            assert "On Track" in resp.text

    def test_accept_queues(self, client, tmp_db, project):
        mock_review = MagicMock()
        mock_review.status.value = "queued"

        with patch("src.web.deps.DashboardService") as MockDash, \
             patch("src.web.deps.CeoReviewService") as MockSvc:
            MockDash.return_value.get_project_by_id.return_value = project
            MockSvc.return_value.accept_review.return_value = mock_review

            resp = client.post(f"/project/{project.id}/ceo-review/1/accept")
            assert resp.status_code == 200
            assert "queued" in resp.text.lower() or "Approval Queue" in resp.text

    def test_reject(self, client, tmp_db, project):
        with patch("src.web.deps.DashboardService") as MockDash, \
             patch("src.web.deps.CeoReviewService") as MockSvc:
            MockDash.return_value.get_project_by_id.return_value = project

            resp = client.post(f"/project/{project.id}/ceo-review/1/reject")
            assert resp.status_code == 200
            assert "rejected" in resp.text.lower() or "Rejected" in resp.text
