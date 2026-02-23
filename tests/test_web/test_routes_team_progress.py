"""Tests for team progress routes — contract tests for GET and POST endpoints."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

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
        team_projects={"AIM": "HOP Drop 2", "CTCV": "HOP Drop 2"},
    )
    defaults.update(overrides)
    return Project(**defaults)


def _make_report(team_key="AIM", **overrides):
    defaults = dict(
        team_key=team_key, version_name="HOP Drop 2",
        total_issues=10, done_count=5, in_progress_count=3,
        todo_count=2, blocker_count=0,
        sp_total=20.0, sp_done=10.0, sp_missing_count=1,
    )
    defaults.update(overrides)
    return TeamVersionReport(**defaults)


# ---------------------------------------------------------------------------
# GET /project/{id}/team-progress
# ---------------------------------------------------------------------------


def test_team_progress_200_with_teams(client, tmp_db):
    project = _make_project()
    reports = [_make_report("AIM"), _make_report("CTCV", done_count=3)]

    with patch("src.web.routes.project.DashboardService") as MockDash, \
         patch("src.web.routes.project.TeamProgressService") as MockTeam:
        MockDash.return_value.get_project_by_id = lambda x: project
        MockDash.return_value.list_projects = lambda: [project]
        MockTeam.return_value.get_team_reports = AsyncMock(return_value=reports)

        result = client.get("/project/1/team-progress")

    assert result.status_code == 200
    assert "AIM" in result.text
    assert "CTCV" in result.text
    assert "Team Progress" in result.text


def test_team_progress_200_without_teams(client, tmp_db):
    project = _make_project(team_projects={})

    with patch("src.web.routes.project.DashboardService") as MockDash, \
         patch("src.web.routes.project.TeamProgressService") as MockTeam:
        MockDash.return_value.get_project_by_id = lambda x: project
        MockDash.return_value.list_projects = lambda: [project]
        MockTeam.return_value.get_team_reports = AsyncMock(return_value=[])

        result = client.get("/project/1/team-progress")

    assert result.status_code == 200
    assert "No Team Projects Configured" in result.text


def test_team_progress_404_unknown_project(client, tmp_db):
    with patch("src.web.routes.project.DashboardService") as MockDash:
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
    assert json.loads(row["team_projects"]) == {"AIM": "HOP Drop 2", "CTCV": "HOP Drop 2", "YAM": "HOP Drop 2"}
