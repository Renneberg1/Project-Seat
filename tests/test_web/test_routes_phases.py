"""Tests for phase gates routes — pipeline view and phase updates."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from src.database import get_db
from src.models.dashboard import PIPELINE_PHASES, ProjectSummary
from src.models.jira import JiraIssue
from src.models.project import Project


def _insert_project(db_path, name="Test Project", goal_key="PROG-100", phase="planning"):
    with get_db(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO projects (jira_goal_key, name, status, phase) VALUES (?, ?, ?, ?)",
            (goal_key, name, "active", phase),
        )
        conn.commit()
        return cursor.lastrowid


def _make_summary(project, error=None):
    goal = JiraIssue(
        id="10000", key=project.jira_goal_key, summary=project.name,
        status="In Progress", issue_type="Goal", project_key="PROG",
        labels=[], parent_key=None, fix_versions=[], due_date=None,
        description_adf=None,
    ) if error is None else None

    return ProjectSummary(
        project=project, goal=goal,
        risk_count=2, open_risk_count=1, decision_count=1, initiative_count=3,
        error=error,
    )


# ---------------------------------------------------------------------------
# GET / — root redirect: Contract tests
# ---------------------------------------------------------------------------


def test_root_redirects_to_phases(client):
    result = client.get("/", follow_redirects=False)

    assert result.status_code == 302
    assert result.headers["location"] == "/phases/"


def test_root_follow_redirect_returns_200(client):
    with patch("src.web.routes.phases.DashboardService") as MockSvc:
        MockSvc.return_value.get_all_summaries = AsyncMock(return_value=[])
        MockSvc.return_value.list_projects = lambda: []

        result = client.get("/")

    assert result.status_code == 200


# ---------------------------------------------------------------------------
# GET /phases/ — pipeline view: Contract tests
# ---------------------------------------------------------------------------


def test_phases_get_empty_state_shows_no_projects_message(client):
    with patch("src.web.routes.phases.DashboardService") as MockSvc:
        MockSvc.return_value.get_all_summaries = AsyncMock(return_value=[])
        MockSvc.return_value.list_projects = lambda: []

        result = client.get("/phases/")

    assert result.status_code == 200
    assert "No projects tracked yet" in result.text
    assert "Spin Up a Project" in result.text


def test_phases_get_shows_project_cards(client, tmp_db):
    pid = _insert_project(tmp_db, "Alpha", "PROG-1", "development")
    project = Project(
        id=pid, jira_goal_key="PROG-1", name="Alpha",
        confluence_charter_id=None, confluence_xft_id=None,
        status="active", phase="development", created_at="2026-01-01",
    )
    summary = _make_summary(project)

    with patch("src.web.routes.phases.DashboardService") as MockSvc:
        MockSvc.return_value.get_all_summaries = AsyncMock(return_value=[summary])
        MockSvc.return_value.list_projects = lambda: [project]

        result = client.get("/phases/")

    assert result.status_code == 200
    assert "Alpha" in result.text
    assert "PROG-1" in result.text


def test_phases_get_page_title_says_phase_gates(client):
    with patch("src.web.routes.phases.DashboardService") as MockSvc:
        MockSvc.return_value.get_all_summaries = AsyncMock(return_value=[])
        MockSvc.return_value.list_projects = lambda: []

        result = client.get("/phases/")

    assert "Phase Gates" in result.text


def test_phases_get_error_project_shows_banner(client, tmp_db):
    pid = _insert_project(tmp_db, "Broken", "PROG-99")
    project = Project(
        id=pid, jira_goal_key="PROG-99", name="Broken",
        confluence_charter_id=None, confluence_xft_id=None,
        status="active", phase="planning", created_at="2026-01-01",
    )
    summary = _make_summary(project, error="HTTP 503: Service Unavailable")

    with patch("src.web.routes.phases.DashboardService") as MockSvc:
        MockSvc.return_value.get_all_summaries = AsyncMock(return_value=[summary])
        MockSvc.return_value.list_projects = lambda: [project]

        result = client.get("/phases/")

    assert result.status_code == 200
    assert "Jira unavailable" in result.text


# ---------------------------------------------------------------------------
# POST /phases/{id}/phase — update phase: Contract tests
# ---------------------------------------------------------------------------


def test_update_phase_post_returns_200(client, tmp_db):
    pid = _insert_project(tmp_db, "Alpha", "PROG-1", "planning")

    with patch("src.web.routes.phases.DashboardService") as MockSvc:
        instance = MockSvc.return_value
        instance.update_phase = lambda pid, phase: None
        instance.get_project_by_id = lambda pid: Project(
            id=pid, jira_goal_key="PROG-1", name="Alpha",
            confluence_charter_id=None, confluence_xft_id=None,
            status="active", phase="development", created_at="2026-01-01",
        )
        instance.get_project_summary = AsyncMock(
            return_value=_make_summary(
                Project(
                    id=pid, jira_goal_key="PROG-1", name="Alpha",
                    confluence_charter_id=None, confluence_xft_id=None,
                    status="active", phase="development", created_at="2026-01-01",
                )
            )
        )

        result = client.post(f"/phases/{pid}/phase", data={"phase": "development"})

    assert result.status_code == 200


def test_update_phase_nonexistent_project_returns_404(client):
    with patch("src.web.routes.phases.DashboardService") as MockSvc:
        instance = MockSvc.return_value
        instance.update_phase = lambda pid, phase: None
        instance.get_project_by_id = lambda pid: None

        result = client.post("/phases/999/phase", data={"phase": "development"})

    assert result.status_code == 404
