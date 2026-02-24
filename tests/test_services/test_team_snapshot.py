"""Tests for TeamSnapshotService — snapshot persistence and retrieval."""

from __future__ import annotations

import json
from datetime import date, timedelta
from unittest.mock import AsyncMock, patch

from src.database import get_db, init_db
from src.models.project import Project
from src.services.team_progress import TeamVersionReport
from src.services.team_snapshot import TeamSnapshotService, snapshot_all_projects


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project(**overrides):
    defaults = dict(
        id=1, jira_goal_key="PROG-100", name="HOP Drop 2",
        confluence_charter_id=None, confluence_xft_id=None,
        status="active", phase="planning", created_at="2026-01-01",
        team_projects=[["AIM", "HOP Drop 2"]],
    )
    defaults.update(overrides)
    return Project(**defaults)


def _make_report(team_key="AIM", sp_total=20.0, sp_done=10.0, **overrides):
    defaults = dict(
        team_key=team_key, version_name="HOP Drop 2",
        total_issues=10, done_count=5, in_progress_count=3,
        todo_count=2, blocker_count=0,
        sp_total=sp_total, sp_done=sp_done, sp_in_progress=0.0, sp_missing_count=1,
    )
    defaults.update(overrides)
    return TeamVersionReport(**defaults)


def _seed_project(db_path: str, project_id: int = 1) -> None:
    """Insert a minimal project row needed for FK constraints."""
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO projects (id, jira_goal_key, name, status, phase) "
            "VALUES (?, ?, ?, ?, ?)",
            (project_id, "PROG-100", "HOP Drop 2", "active", "planning"),
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_save_snapshot_round_trip(tmp_db):
    _seed_project(tmp_db)
    svc = TeamSnapshotService(db_path=tmp_db)
    project = _make_project()
    reports = [_make_report("AIM", sp_total=20, sp_done=8)]

    svc.save_snapshot(project, reports)
    snapshots = svc.get_snapshots(project.id)

    assert len(snapshots) == 1
    assert snapshots[0]["date"] == date.today().isoformat()
    assert snapshots[0]["sp_total"] == 20.0
    assert snapshots[0]["sp_done"] == 8.0


def test_save_snapshot_idempotent_same_day(tmp_db):
    _seed_project(tmp_db)
    svc = TeamSnapshotService(db_path=tmp_db)
    project = _make_project()

    # First save
    svc.save_snapshot(project, [_make_report(sp_total=20, sp_done=5)])
    # Second save (same day) — should overwrite
    svc.save_snapshot(project, [_make_report(sp_total=20, sp_done=12)])

    snapshots = svc.get_snapshots(project.id)
    assert len(snapshots) == 1
    assert snapshots[0]["sp_done"] == 12.0


def test_get_snapshots_ordered_by_date(tmp_db):
    _seed_project(tmp_db)
    svc = TeamSnapshotService(db_path=tmp_db)

    # Insert snapshots with explicit dates (bypass save_snapshot which uses today)
    today = date.today()
    with get_db(tmp_db) as conn:
        for i in range(3):
            d = (today - timedelta(days=2 - i)).isoformat()
            data = json.dumps({"sp_total": 30, "sp_done": 10 + i * 5, "per_team": []})
            conn.execute(
                "INSERT INTO team_progress_snapshots (project_id, snapshot_date, data_json) "
                "VALUES (?, ?, ?)",
                (1, d, data),
            )
        conn.commit()

    snapshots = svc.get_snapshots(1)
    dates = [s["date"] for s in snapshots]
    assert dates == sorted(dates)
    assert len(snapshots) == 3


def test_get_snapshots_days_limit(tmp_db):
    _seed_project(tmp_db)
    svc = TeamSnapshotService(db_path=tmp_db)

    today = date.today()
    with get_db(tmp_db) as conn:
        # Old snapshot (120 days ago — outside default 90-day window)
        old_date = (today - timedelta(days=120)).isoformat()
        data = json.dumps({"sp_total": 30, "sp_done": 5, "per_team": []})
        conn.execute(
            "INSERT INTO team_progress_snapshots (project_id, snapshot_date, data_json) "
            "VALUES (?, ?, ?)",
            (1, old_date, data),
        )
        # Recent snapshot
        recent_date = (today - timedelta(days=10)).isoformat()
        conn.execute(
            "INSERT INTO team_progress_snapshots (project_id, snapshot_date, data_json) "
            "VALUES (?, ?, ?)",
            (1, recent_date, data),
        )
        conn.commit()

    snapshots = svc.get_snapshots(1, days=90)
    assert len(snapshots) == 1
    assert snapshots[0]["date"] == recent_date


async def test_snapshot_all_projects(tmp_db):
    """snapshot_all_projects iterates active projects and saves snapshots."""
    project_active = _make_project(id=1, status="active", team_projects=[["AIM", "v1"]])
    project_no_teams = _make_project(id=2, status="active", team_projects=[])
    reports = [_make_report()]

    with patch("src.services.dashboard.DashboardService") as MockDash, \
         patch("src.services.team_progress.TeamProgressService") as MockTeam, \
         patch("src.services.team_snapshot.TeamSnapshotService") as MockSnap:
        MockDash.return_value.list_projects.return_value = [project_active, project_no_teams]
        MockTeam.return_value.get_team_reports = AsyncMock(return_value=reports)
        mock_snap_instance = MockSnap.return_value

        await snapshot_all_projects()

        # Only the active project with teams should be snapshotted
        mock_snap_instance.save_snapshot.assert_called_once_with(project_active, reports)


import pytest

test_snapshot_all_projects = pytest.mark.asyncio(test_snapshot_all_projects)
