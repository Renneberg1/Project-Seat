"""Tests for Closure Report route contracts."""

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
            "INSERT INTO projects (jira_goal_key, name, status, phase, "
            "confluence_charter_id, team_projects) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("PROG-1", "Test Project", "active", "development",
             "88888", json.dumps([["AIM", "Drop 1"]])),
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


class TestRoutes:
    """Test Closure Report route contracts."""

    def test_main_page(self, client, tmp_db, project):
        with patch("src.web.deps.DashboardService") as MockDash, \
             patch("src.web.deps.ClosureService") as MockSvc:
            MockDash.return_value.get_project_by_id.return_value = project
            MockSvc.return_value.list_reports.return_value = []

            resp = client.get(f"/project/{project.id}/closure/")
            assert resp.status_code == 200
            assert "Closure Report" in resp.text

    def test_main_page_not_found(self, client, tmp_db):
        with patch("src.web.deps.DashboardService") as MockDash:
            MockDash.return_value.get_project_by_id.return_value = None
            resp = client.get("/project/999/closure/")
            assert resp.status_code == 404

    def test_ask_returns_questions(self, client, tmp_db, project):
        questions = [{"question": "What lessons?", "category": "Lessons Learned", "why_needed": "Context"}]
        metrics = {"project_name": "Test"}

        with patch("src.web.deps.DashboardService") as MockDash, \
             patch("src.web.deps.ClosureService") as MockSvc:
            MockDash.return_value.get_project_by_id.return_value = project
            MockSvc.return_value.generate_questions = AsyncMock(
                return_value=(questions, metrics)
            )

            resp = client.post(
                f"/project/{project.id}/closure/ask",
                data={"pm_notes": "Project done"},
            )
            assert resp.status_code == 200
            assert "What lessons?" in resp.text

    def test_analyze_returns_preview(self, client, tmp_db, project):
        report = {
            "final_delivery_outcome": "Delivered successfully.",
            "success_criteria_assessments": [
                {
                    "criterion": "On-time delivery",
                    "expected_outcome": "Q1",
                    "measurement_method": "Date",
                    "actual_performance": "Q1",
                    "status": "Met",
                    "comments": "On time",
                }
            ],
            "lessons_learned": [
                {
                    "category": "Planning",
                    "description": "Scope lock important",
                    "effect_triggers": "Scope creep",
                    "recommendations": "Lock early",
                    "owner": "PM",
                }
            ],
            "metrics": {
                "project_name": "Test",
                "phase": "closed",
                "pm": "Alice",
                "sponsor": "Bob",
                "timeline": {},
                "scope_delivered": [],
                "scope_not_delivered": [],
                "all_risks": [],
                "all_decisions": [],
                "dhf_total": 0,
                "dhf_released": 0,
                "dhf_completion_pct": 0,
                "team_progress": [],
                "releases": [],
            },
        }

        with patch("src.web.deps.DashboardService") as MockDash, \
             patch("src.web.deps.ClosureService") as MockSvc:
            MockDash.return_value.get_project_by_id.return_value = project
            MockSvc.return_value.generate_report = AsyncMock(return_value=report)
            MockSvc.return_value.render_confluence_xhtml.return_value = "<h1>test</h1>"
            MockSvc.return_value.save_report.return_value = 1

            resp = client.post(
                f"/project/{project.id}/closure/analyze",
                data={"pm_notes": ""},
            )
            assert resp.status_code == 200
            assert "Delivered successfully" in resp.text or "Delivery Outcome" in resp.text

    def test_accept_queues(self, client, tmp_db, project):
        mock_report = MagicMock()
        mock_report.status.value = "queued"

        with patch("src.web.deps.DashboardService") as MockDash, \
             patch("src.web.deps.ClosureService") as MockSvc:
            MockDash.return_value.get_project_by_id.return_value = project
            MockSvc.return_value.accept_report.return_value = mock_report

            resp = client.post(f"/project/{project.id}/closure/1/accept")
            assert resp.status_code == 200
            assert "queued" in resp.text.lower() or "Approval Queue" in resp.text

    def test_reject(self, client, tmp_db, project):
        with patch("src.web.deps.DashboardService") as MockDash, \
             patch("src.web.deps.ClosureService") as MockSvc:
            MockDash.return_value.get_project_by_id.return_value = project

            resp = client.post(f"/project/{project.id}/closure/1/reject")
            assert resp.status_code == 200
            assert "rejected" in resp.text.lower() or "Rejected" in resp.text
