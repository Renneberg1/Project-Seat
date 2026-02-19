"""Tests for project domain models."""

from __future__ import annotations

import sqlite3

from src.database import init_db, get_db
from src.models.project import Project, SpinUpRequest


class TestProject:
    def test_from_row_all_fields(self, tmp_db: str) -> None:
        with get_db(tmp_db) as conn:
            conn.execute(
                "INSERT INTO projects (jira_goal_key, name, confluence_charter_id, confluence_xft_id, status, phase) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("PROG-100", "Test Project", "12345", "67890", "active", "development"),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM projects WHERE jira_goal_key = 'PROG-100'").fetchone()

        project = Project.from_row(row)
        assert project.jira_goal_key == "PROG-100"
        assert project.name == "Test Project"
        assert project.confluence_charter_id == "12345"
        assert project.confluence_xft_id == "67890"
        assert project.status == "active"
        assert project.phase == "development"

    def test_nullable_confluence_ids(self, tmp_db: str) -> None:
        with get_db(tmp_db) as conn:
            conn.execute(
                "INSERT INTO projects (jira_goal_key, name, status) VALUES (?, ?, ?)",
                ("PROG-200", "No Pages", "spinning_up"),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM projects WHERE jira_goal_key = 'PROG-200'").fetchone()

        project = Project.from_row(row)
        assert project.confluence_charter_id is None
        assert project.confluence_xft_id is None

    def test_phase_defaults_to_planning(self, tmp_db: str) -> None:
        with get_db(tmp_db) as conn:
            conn.execute(
                "INSERT INTO projects (jira_goal_key, name, status) VALUES (?, ?, ?)",
                ("PROG-300", "Default Phase", "active"),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM projects WHERE jira_goal_key = 'PROG-300'").fetchone()

        project = Project.from_row(row)
        assert project.phase == "planning"

    def test_dhf_columns_default_to_none(self, tmp_db: str) -> None:
        with get_db(tmp_db) as conn:
            conn.execute(
                "INSERT INTO projects (jira_goal_key, name, status) VALUES (?, ?, ?)",
                ("PROG-400", "No DHF", "active"),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM projects WHERE jira_goal_key = 'PROG-400'").fetchone()

        project = Project.from_row(row)
        assert project.dhf_draft_root_id is None
        assert project.dhf_released_root_id is None

    def test_dhf_columns_round_trip(self, tmp_db: str) -> None:
        with get_db(tmp_db) as conn:
            conn.execute(
                "INSERT INTO projects (jira_goal_key, name, status, dhf_draft_root_id, dhf_released_root_id) "
                "VALUES (?, ?, ?, ?, ?)",
                ("PROG-500", "With DHF", "active", "111", "222"),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM projects WHERE jira_goal_key = 'PROG-500'").fetchone()

        project = Project.from_row(row)
        assert project.dhf_draft_root_id == "111"
        assert project.dhf_released_root_id == "222"


class TestSpinUpRequest:
    def test_default_space_key(self) -> None:
        req = SpinUpRequest(
            project_name="Test",
            program="HOP",
            team_projects=["AIM"],
            target_date="2026-06-01",
            labels=["test"],
            goal_summary="A test project",
        )
        assert req.confluence_space_key == "HPP"

    def test_custom_space_key(self) -> None:
        req = SpinUpRequest(
            project_name="Test",
            program="HOP",
            team_projects=[],
            target_date="",
            labels=[],
            goal_summary="",
            confluence_space_key="CUSTOM",
        )
        assert req.confluence_space_key == "CUSTOM"
