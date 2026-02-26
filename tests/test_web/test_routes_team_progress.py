"""Tests for team progress routes — contract tests for GET and POST endpoints."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

from src.models.dashboard import ProjectSummary
from src.models.jira import JiraIssue
from src.models.project import Project
from src.services.team_progress import TeamVersionReport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project(**overrides):
    defaults = dict(
        id=1, jira_goal_key="PROG-100", name="HOP Drop 2",
        confluence_charter_id=None, confluence_xft_id=None,
        status="active", phase="planning", created_at="2026-01-01",
        team_projects=[["AIM", "HOP Drop 2"], ["CTCV", "HOP Drop 2"]],
    )
    defaults.update(overrides)
    return Project(**defaults)


def _make_report(team_key="AIM", **overrides):
    defaults = dict(
        team_key=team_key, version_name="HOP Drop 2",
        total_issues=10, done_count=5, in_progress_count=3,
        todo_count=2, blocker_count=0,
        sp_total=20.0, sp_done=10.0, sp_in_progress=6.0, sp_missing_count=1,
    )
    defaults.update(overrides)
    return TeamVersionReport(**defaults)


def _make_goal(due_date="2026-09-01"):
    return JiraIssue(
        id="10000", key="PROG-100", summary="HOP Drop 2",
        status="In Progress", issue_type="Goal", project_key="PROG",
        labels=[], parent_key=None, fix_versions=[], due_date=due_date,
        description_adf=None,
    )


def _make_summary(project, due_date="2026-09-01"):
    goal = _make_goal(due_date) if due_date else None
    return ProjectSummary(
        project=project, goal=goal,
        risk_count=0, open_risk_count=0, decision_count=0,
        initiative_count=0, error=None,
    )


def _setup_mocks(MockDash, MockTeam, MockSnap, project, reports, snapshots, due_date="2026-09-01"):
    """Wire up common mocks for the team-progress route."""
    MockDash.return_value.get_project_by_id = lambda x: project
    MockDash.return_value.list_projects = lambda: [project]
    MockDash.return_value.get_project_summary = AsyncMock(
        return_value=_make_summary(project, due_date),
    )
    MockTeam.return_value.get_team_reports = AsyncMock(return_value=reports)
    MockSnap.return_value.get_snapshots.return_value = snapshots


# ---------------------------------------------------------------------------
# GET /project/{id}/team-progress
# ---------------------------------------------------------------------------


def test_team_progress_200_with_teams(client, tmp_db):
    project = _make_project()
    reports = [_make_report("AIM"), _make_report("CTCV", done_count=3)]

    with patch("src.web.deps.DashboardService") as MockDash, \
         patch("src.web.deps.TeamProgressService") as MockTeam, \
         patch("src.web.deps.TeamSnapshotService") as MockSnap:
        _setup_mocks(MockDash, MockTeam, MockSnap, project, reports, [])

        result = client.get("/project/1/team-progress")

    assert result.status_code == 200
    assert "AIM" in result.text
    assert "CTCV" in result.text
    assert "Team Progress" in result.text


def test_team_progress_200_without_teams(client, tmp_db):
    project = _make_project(team_projects=[])

    with patch("src.web.deps.DashboardService") as MockDash, \
         patch("src.web.deps.TeamProgressService") as MockTeam, \
         patch("src.web.deps.TeamSnapshotService") as MockSnap:
        _setup_mocks(MockDash, MockTeam, MockSnap, project, [], [])

        result = client.get("/project/1/team-progress")

    assert result.status_code == 200
    assert "No Team Projects Configured" in result.text


def test_team_progress_404_unknown_project(client, tmp_db):
    with patch("src.web.deps.DashboardService") as MockDash:
        MockDash.return_value.get_project_by_id = lambda x: None
        MockDash.return_value.list_projects = lambda: []

        result = client.get("/project/999/team-progress")

    assert result.status_code == 404


def test_save_config_redirects(client, tmp_db):
    """POST config saves team_projects to DB and redirects to team-progress."""
    # Insert a project into the temp DB first
    from src.database import get_db
    with get_db(tmp_db) as conn:
        conn.execute(
            "INSERT INTO projects (id, jira_goal_key, name, status, phase) VALUES (?, ?, ?, ?, ?)",
            (1, "PROG-100", "HOP Drop 2", "active", "planning"),
        )
        conn.commit()

    result = client.post(
        "/project/1/team-projects/config",
        data={"team_projects": "AIM:HOP Drop 2, CTCV:HOP Drop 2, YAM:HOP Drop 2"},
        follow_redirects=False,
    )

    assert result.status_code == 303
    assert "/project/1/team-progress" in result.headers["location"]

    # Verify the DB was updated with dict format
    with get_db(tmp_db) as conn:
        row = conn.execute("SELECT team_projects FROM projects WHERE id = 1").fetchone()
    assert json.loads(row["team_projects"]) == [["AIM", "HOP Drop 2"], ["CTCV", "HOP Drop 2"], ["YAM", "HOP Drop 2"]]


def test_team_progress_burnup_chart_shown_with_data(client, tmp_db):
    """Burnup chart canvas appears when >= 2 snapshots exist."""
    project = _make_project()
    reports = [_make_report("AIM")]
    snapshots = [
        {"date": "2026-02-20", "sp_total": 20, "sp_done": 5},
        {"date": "2026-02-21", "sp_total": 20, "sp_done": 10},
    ]

    with patch("src.web.deps.DashboardService") as MockDash, \
         patch("src.web.deps.TeamProgressService") as MockTeam, \
         patch("src.web.deps.TeamSnapshotService") as MockSnap:
        _setup_mocks(MockDash, MockTeam, MockSnap, project, reports, snapshots)

        result = client.get("/project/1/team-progress")

    assert result.status_code == 200
    assert 'id="burnupChart"' in result.text
    assert "Total Scope (SP)" in result.text


def test_team_progress_burnup_hint_with_single_snapshot(client, tmp_db):
    """Single snapshot shows hint message instead of chart."""
    project = _make_project()
    reports = [_make_report("AIM")]
    snapshots = [{"date": "2026-02-21", "sp_total": 20, "sp_done": 10}]

    with patch("src.web.deps.DashboardService") as MockDash, \
         patch("src.web.deps.TeamProgressService") as MockTeam, \
         patch("src.web.deps.TeamSnapshotService") as MockSnap:
        _setup_mocks(MockDash, MockTeam, MockSnap, project, reports, snapshots)

        result = client.get("/project/1/team-progress")

    assert result.status_code == 200
    assert "Burnup chart will appear after multiple days of data" in result.text
    assert 'id="burnupChart"' not in result.text


# ---------------------------------------------------------------------------
# Projection line tests
# ---------------------------------------------------------------------------


def test_team_progress_projection_shown_with_due_date(client, tmp_db):
    """Projection due date is passed to the chart script when goal has a due date."""
    project = _make_project()
    reports = [_make_report("AIM")]
    snapshots = [
        {"date": "2026-02-20", "sp_total": 20, "sp_done": 5},
        {"date": "2026-02-21", "sp_total": 20, "sp_done": 10},
    ]

    with patch("src.web.deps.DashboardService") as MockDash, \
         patch("src.web.deps.TeamProgressService") as MockTeam, \
         patch("src.web.deps.TeamSnapshotService") as MockSnap:
        _setup_mocks(MockDash, MockTeam, MockSnap, project, reports, snapshots, due_date="2026-09-01")

        result = client.get("/project/1/team-progress")

    assert result.status_code == 200
    # Chart is rendered with projection date injected into JS
    assert 'var projectDueDate = "2026-09-01"' in result.text
    assert "Done (Projected)" in result.text


def test_team_progress_no_projection_without_due_date(client, tmp_db):
    """No projection when goal has no due date — projectDueDate is null."""
    project = _make_project()
    reports = [_make_report("AIM")]
    snapshots = [
        {"date": "2026-02-20", "sp_total": 20, "sp_done": 5},
        {"date": "2026-02-21", "sp_total": 20, "sp_done": 10},
    ]

    with patch("src.web.deps.DashboardService") as MockDash, \
         patch("src.web.deps.TeamProgressService") as MockTeam, \
         patch("src.web.deps.TeamSnapshotService") as MockSnap:
        _setup_mocks(MockDash, MockTeam, MockSnap, project, reports, snapshots, due_date=None)

        result = client.get("/project/1/team-progress")

    assert result.status_code == 200
    assert 'id="burnupChart"' in result.text
    assert "var projectDueDate = null" in result.text


def test_team_progress_no_projection_due_date_in_past(client, tmp_db):
    """Past due date is passed but JS won't render projection (dueDate <= lastDate)."""
    project = _make_project()
    reports = [_make_report("AIM")]
    snapshots = [
        {"date": "2026-02-20", "sp_total": 20, "sp_done": 5},
        {"date": "2026-02-21", "sp_total": 20, "sp_done": 10},
    ]

    with patch("src.web.deps.DashboardService") as MockDash, \
         patch("src.web.deps.TeamProgressService") as MockTeam, \
         patch("src.web.deps.TeamSnapshotService") as MockSnap:
        _setup_mocks(MockDash, MockTeam, MockSnap, project, reports, snapshots, due_date="2026-01-01")

        result = client.get("/project/1/team-progress")

    assert result.status_code == 200
    assert 'id="burnupChart"' in result.text
    # Due date is in the past — JS will skip projection (dueDate <= lastDate guard)
    assert 'var projectDueDate = "2026-01-01"' in result.text
