"""Tests for project domain models."""

from __future__ import annotations

import sqlite3

from src.database import init_db, get_db
from src.models.project import Project, SpinUpRequest


class TestProject:
    def test_from_row_all_fields(self, tmp_db: str) -> None:
        with get_db(tmp_db) as conn:
            conn.execute(
                "INSERT INTO projects (jira_goal_key, name, confluence_charter_id, confluence_xft_id, status) "
                "VALUES (?, ?, ?, ?, ?)",
                ("PROG-100", "Test Project", "12345", "67890", "active"),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM projects WHERE jira_goal_key = 'PROG-100'").fetchone()

        project = Project.from_row(row)
        assert project.jira_goal_key == "PROG-100"
        assert project.name == "Test Project"
        assert project.confluence_charter_id == "12345"
        assert project.confluence_xft_id == "67890"
        assert project.status == "active"

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
