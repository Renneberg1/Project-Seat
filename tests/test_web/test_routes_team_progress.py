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


def _setup_mocks(MockDash, MockTeam, MockSnap, project, reports, snapshots, due_date="2026-09-01", extra_projects=None):
    """Wire up common mocks for the team-progress route."""
    all_projects = [project] + (extra_projects or [])
    MockDash.return_value.get_project_by_id = lambda x: project
    MockDash.return_value.list_projects = lambda: all_projects

    async def _get_summary(p):
        return _make_summary(p, due_date)
    MockDash.return_value.get_project_summary = AsyncMock(side_effect=_get_summary)

    MockTeam.return_value.get_team_reports = AsyncMock(return_value=reports)
    MockSnap.return_value.get_snapshots.return_value = snapshots
    MockSnap.return_value.save_snapshot = lambda *a, **kw: None


def _patch_jira_versions(versions=None):
    """Patch JiraConnector to return fake versions (avoids real API calls)."""
    mock_jira = AsyncMock()
    mock_jira.get_versions = AsyncMock(return_value=versions or [])
    return patch("src.web.deps.JiraConnector", return_value=mock_jira)


# ---------------------------------------------------------------------------
# GET /project/{id}/team-progress
# ---------------------------------------------------------------------------


def test_team_progress_200_with_teams(client, tmp_db):
    project = _make_project()
    reports = [_make_report("AIM"), _make_report("CTCV", done_count=3)]

    with patch("src.web.deps.DashboardService") as MockDash, \
         patch("src.web.deps.TeamProgressService") as MockTeam, \
         patch("src.web.deps.TeamSnapshotService") as MockSnap, \
         _patch_jira_versions():
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
         patch("src.web.deps.TeamSnapshotService") as MockSnap, \
         _patch_jira_versions():
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
         patch("src.web.deps.TeamSnapshotService") as MockSnap, \
         _patch_jira_versions():
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
         patch("src.web.deps.TeamSnapshotService") as MockSnap, \
         _patch_jira_versions():
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
         patch("src.web.deps.TeamSnapshotService") as MockSnap, \
         _patch_jira_versions():
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
         patch("src.web.deps.TeamSnapshotService") as MockSnap, \
         _patch_jira_versions():
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
         patch("src.web.deps.TeamSnapshotService") as MockSnap, \
         _patch_jira_versions():
        _setup_mocks(MockDash, MockTeam, MockSnap, project, reports, snapshots, due_date="2026-01-01")

        result = client.get("/project/1/team-progress")

    assert result.status_code == 200
    assert 'id="burnupChart"' in result.text
    # Due date is in the past — JS will skip projection (dueDate <= lastDate guard)
    assert 'var projectDueDate = "2026-01-01"' in result.text


def test_team_progress_milestones_injected(client, tmp_db):
    """Version release dates from Jira are passed as milestone data."""
    project = _make_project()
    reports = [_make_report("AIM")]
    snapshots = [
        {"date": "2026-02-20", "sp_total": 20, "sp_done": 5},
        {"date": "2026-02-21", "sp_total": 20, "sp_done": 10},
    ]
    versions = [
        {"name": "HOP Drop 2", "releaseDate": "2026-06-15"},
        {"name": "Other Version", "releaseDate": "2026-12-01"},
    ]

    with patch("src.web.deps.DashboardService") as MockDash, \
         patch("src.web.deps.TeamProgressService") as MockTeam, \
         patch("src.web.deps.TeamSnapshotService") as MockSnap, \
         _patch_jira_versions(versions):
        _setup_mocks(MockDash, MockTeam, MockSnap, project, reports, snapshots)

        result = client.get("/project/1/team-progress")

    assert result.status_code == 200
    # Milestone for "HOP Drop 2" should be present, "Other Version" should not
    assert "2026-06-15" in result.text
    assert "2026-12-01" not in result.text


# ---------------------------------------------------------------------------
# Cross-project overlay tests
# ---------------------------------------------------------------------------


def test_team_progress_includes_overlay_projects(client, tmp_db):
    """Overlay data for other active projects is passed to the template."""
    project = _make_project(id=1, name="HOP Drop 3")
    overlay_proj = _make_project(
        id=2, name="HOP Drop 4", jira_goal_key="PROG-200",
        team_projects=[["AIM", "HOP Drop 4"]],
    )
    reports = [_make_report("AIM")]
    snapshots = [
        {"date": "2026-02-20", "sp_total": 20, "sp_done": 5},
        {"date": "2026-02-21", "sp_total": 20, "sp_done": 10},
    ]
    overlay_snapshots = [
        {"date": "2026-02-20", "sp_total": 30, "sp_done": 8},
    ]

    with patch("src.web.deps.DashboardService") as MockDash, \
         patch("src.web.deps.TeamProgressService") as MockTeam, \
         patch("src.web.deps.TeamSnapshotService") as MockSnap, \
         _patch_jira_versions():
        _setup_mocks(MockDash, MockTeam, MockSnap, project, reports, snapshots,
                     extra_projects=[overlay_proj])
        # Make get_snapshots return different data per project
        def _snap_by_id(pid):
            if pid == 2:
                return overlay_snapshots
            return snapshots
        MockSnap.return_value.get_snapshots = _snap_by_id

        result = client.get("/project/1/team-progress")

    assert result.status_code == 200
    # Overlay project name appears in the "Compare with:" checkboxes
    assert "HOP Drop 4" in result.text
    assert "Compare with:" in result.text
    # overlayProjects JS variable should contain the overlay data
    assert "overlayProjects" in result.text


def test_team_progress_excludes_current_from_overlay(client, tmp_db):
    """Current project should not appear in overlay list."""
    project = _make_project(id=1, name="HOP Drop 3")
    reports = [_make_report("AIM")]
    snapshots = [
        {"date": "2026-02-20", "sp_total": 20, "sp_done": 5},
        {"date": "2026-02-21", "sp_total": 20, "sp_done": 10},
    ]

    with patch("src.web.deps.DashboardService") as MockDash, \
         patch("src.web.deps.TeamProgressService") as MockTeam, \
         patch("src.web.deps.TeamSnapshotService") as MockSnap, \
         _patch_jira_versions():
        _setup_mocks(MockDash, MockTeam, MockSnap, project, reports, snapshots)

        result = client.get("/project/1/team-progress")

    assert result.status_code == 200
    # overlayProjects JS variable should be an empty array (current project excluded)
    assert "var overlayProjects = []" in result.text


def test_team_progress_overlay_excludes_inactive_and_no_teams(client, tmp_db):
    """Overlay list excludes archived projects and those without team_projects."""
    project = _make_project(id=1, name="HOP Drop 3")
    archived_proj = _make_project(
        id=2, name="Old Project", jira_goal_key="PROG-200",
        status="archived", team_projects=[["AIM", "Old"]],
    )
    no_teams_proj = _make_project(
        id=3, name="Empty Project", jira_goal_key="PROG-300",
        status="active", team_projects=[],
    )
    reports = [_make_report("AIM")]
    snapshots = [
        {"date": "2026-02-20", "sp_total": 20, "sp_done": 5},
        {"date": "2026-02-21", "sp_total": 20, "sp_done": 10},
    ]

    with patch("src.web.deps.DashboardService") as MockDash, \
         patch("src.web.deps.TeamProgressService") as MockTeam, \
         patch("src.web.deps.TeamSnapshotService") as MockSnap, \
         _patch_jira_versions():
        _setup_mocks(MockDash, MockTeam, MockSnap, project, reports, snapshots,
                     extra_projects=[archived_proj, no_teams_proj])

        result = client.get("/project/1/team-progress")

    assert result.status_code == 200
    # Neither archived nor no-teams projects appear in overlay JS data
    assert "var overlayProjects = []" in result.text
