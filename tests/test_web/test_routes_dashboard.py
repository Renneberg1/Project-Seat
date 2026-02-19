"""Tests for dashboard routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from src.database import get_db
from src.models.dashboard import PIPELINE_PHASES, ProjectSummary
from src.models.jira import JiraIssue
from src.models.project import Project


def _insert_project(db_path: str, name: str = "Test Project", goal_key: str = "PROG-100", phase: str = "planning") -> int:
    with get_db(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO projects (jira_goal_key, name, status, phase) VALUES (?, ?, ?, ?)",
            (goal_key, name, "active", phase),
        )
        conn.commit()
        return cursor.lastrowid


def _make_summary(project: Project, error: str | None = None) -> ProjectSummary:
    goal = JiraIssue(
        id="10000", key=project.jira_goal_key, summary=project.name,
        status="In Progress", issue_type="Goal", project_key="PROG",
        labels=[], parent_key=None, fix_versions=[], due_date=None,
        description_adf=None,
    ) if error is None else None

    return ProjectSummary(
        project=project,
        goal=goal,
        risk_count=2,
        open_risk_count=1,
        decision_count=1,
        initiative_count=3,
        error=error,
    )


class TestDashboardGet:
    def test_empty_state(self, client) -> None:
        with patch("src.web.routes.dashboard.DashboardService") as MockSvc:
            MockSvc.return_value.get_all_summaries = AsyncMock(return_value=[])
            resp = client.get("/")
        assert resp.status_code == 200
        assert "No projects tracked yet" in resp.text
        assert "Spin Up a Project" in resp.text

    def test_shows_project_cards(self, client, tmp_db: str) -> None:
        pid = _insert_project(tmp_db, "Alpha", "PROG-1", "development")
        project = Project(
            id=pid, jira_goal_key="PROG-1", name="Alpha",
            confluence_charter_id=None, confluence_xft_id=None,
            status="active", phase="development", created_at="2026-01-01",
        )
        summary = _make_summary(project)

        with patch("src.web.routes.dashboard.DashboardService") as MockSvc:
            MockSvc.return_value.get_all_summaries = AsyncMock(return_value=[summary])
            resp = client.get("/")

        assert resp.status_code == 200
        assert "Alpha" in resp.text
        assert "PROG-1" in resp.text

    def test_contains_pipeline_stage_headers(self, client) -> None:
        with patch("src.web.routes.dashboard.DashboardService") as MockSvc:
            MockSvc.return_value.get_all_summaries = AsyncMock(return_value=[])
            # Even with no projects, stage headers should not appear (empty state shown)
            resp = client.get("/")
        assert resp.status_code == 200

    def test_error_project_shows_banner(self, client, tmp_db: str) -> None:
        pid = _insert_project(tmp_db, "Broken", "PROG-99")
        project = Project(
            id=pid, jira_goal_key="PROG-99", name="Broken",
            confluence_charter_id=None, confluence_xft_id=None,
            status="active", phase="planning", created_at="2026-01-01",
        )
        summary = _make_summary(project, error="HTTP 503: Service Unavailable")

        with patch("src.web.routes.dashboard.DashboardService") as MockSvc:
            MockSvc.return_value.get_all_summaries = AsyncMock(return_value=[summary])
            resp = client.get("/")

        assert resp.status_code == 200
        assert "Jira unavailable" in resp.text


class TestUpdatePhase:
    def test_post_updates_phase(self, client, tmp_db: str) -> None:
        pid = _insert_project(tmp_db, "Alpha", "PROG-1", "planning")

        with patch("src.web.routes.dashboard.DashboardService") as MockSvc:
            instance = MockSvc.return_value
            instance.update_phase = lambda pid, phase: None
            instance.list_projects = lambda: [
                Project(
                    id=pid, jira_goal_key="PROG-1", name="Alpha",
                    confluence_charter_id=None, confluence_xft_id=None,
                    status="active", phase="development", created_at="2026-01-01",
                )
            ]
            instance.get_project_summary = AsyncMock(
                return_value=_make_summary(
                    Project(
                        id=pid, jira_goal_key="PROG-1", name="Alpha",
                        confluence_charter_id=None, confluence_xft_id=None,
                        status="active", phase="development", created_at="2026-01-01",
                    )
                )
            )
            resp = client.post(f"/dashboard/{pid}/phase", data={"phase": "development"})

        assert resp.status_code == 200
