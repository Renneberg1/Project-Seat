"""Tests for project domain models."""

from __future__ import annotations

from src.database import get_db
from src.models.project import Project, SpinUpRequest


# ---------------------------------------------------------------------------
# Project.from_row: Contract tests
# ---------------------------------------------------------------------------


def test_project_from_row_all_fields(tmp_db):
    with get_db(tmp_db) as conn:
        conn.execute(
            "INSERT INTO projects (jira_goal_key, name, confluence_charter_id, confluence_xft_id, status, phase) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("PROG-100", "Test Project", "12345", "67890", "active", "development"),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM projects WHERE jira_goal_key = 'PROG-100'").fetchone()

    result = Project.from_row(row)

    assert result.jira_goal_key == "PROG-100"
    assert result.name == "Test Project"
    assert result.confluence_charter_id == "12345"
    assert result.confluence_xft_id == "67890"
    assert result.status == "active"
    assert result.phase == "development"


def test_project_from_row_nullable_confluence_ids(tmp_db):
    with get_db(tmp_db) as conn:
        conn.execute(
            "INSERT INTO projects (jira_goal_key, name, status) VALUES (?, ?, ?)",
            ("PROG-200", "No Pages", "spinning_up"),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM projects WHERE jira_goal_key = 'PROG-200'").fetchone()

    result = Project.from_row(row)

    assert result.confluence_charter_id is None
    assert result.confluence_xft_id is None


def test_project_from_row_phase_defaults_to_planning(tmp_db):
    with get_db(tmp_db) as conn:
        conn.execute(
            "INSERT INTO projects (jira_goal_key, name, status) VALUES (?, ?, ?)",
            ("PROG-300", "Default Phase", "active"),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM projects WHERE jira_goal_key = 'PROG-300'").fetchone()

    result = Project.from_row(row)

    assert result.phase == "planning"


def test_project_from_row_dhf_columns_default_to_none(tmp_db):
    with get_db(tmp_db) as conn:
        conn.execute(
            "INSERT INTO projects (jira_goal_key, name, status) VALUES (?, ?, ?)",
            ("PROG-400", "No DHF", "active"),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM projects WHERE jira_goal_key = 'PROG-400'").fetchone()

    result = Project.from_row(row)

    assert result.dhf_draft_root_id is None
    assert result.dhf_released_root_id is None


def test_project_from_row_dhf_columns_round_trip(tmp_db):
    with get_db(tmp_db) as conn:
        conn.execute(
            "INSERT INTO projects (jira_goal_key, name, status, dhf_draft_root_id, dhf_released_root_id) "
            "VALUES (?, ?, ?, ?, ?)",
            ("PROG-500", "With DHF", "active", "111", "222"),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM projects WHERE jira_goal_key = 'PROG-500'").fetchone()

    result = Project.from_row(row)

    assert result.dhf_draft_root_id == "111"
    assert result.dhf_released_root_id == "222"


# ---------------------------------------------------------------------------
# SpinUpRequest: Contract tests
# ---------------------------------------------------------------------------


def test_spinup_request_default_space_key():
    result = SpinUpRequest(
        project_name="Test",
        program="HOP",
        team_projects=["AIM"],
        target_date="2026-06-01",
        labels=["test"],
        goal_summary="A test project",
    )

    assert result.confluence_space_key == "HPP"


def test_spinup_request_custom_space_key():
    result = SpinUpRequest(
        project_name="Test",
        program="HOP",
        team_projects=[],
        target_date="",
        labels=[],
        goal_summary="",
        confluence_space_key="CUSTOM",
    )

    assert result.confluence_space_key == "CUSTOM"
