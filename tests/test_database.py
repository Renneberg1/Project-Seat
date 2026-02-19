"""Tests for database schema and connection helpers."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from src.database import get_db, init_db


class TestInitDb:
    def test_creates_all_tables(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "test.db")
        init_db(db_path)

        conn = sqlite3.connect(db_path)
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        conn.close()

        expected = {"projects", "approval_log", "transcript_cache", "approval_queue", "config"}
        assert expected.issubset(tables)

    def test_idempotent(self, tmp_path: Path) -> None:
        db_path = str(tmp_path / "test.db")
        init_db(db_path)
        init_db(db_path)  # second call should not raise


class TestGetDb:
    def test_returns_row_factory(self, tmp_db: str) -> None:
        with get_db(tmp_db) as conn:
            assert conn.row_factory is sqlite3.Row

    def test_connection_closed_after_exit(self, tmp_db: str) -> None:
        with get_db(tmp_db) as conn:
            pass
        # After the context manager exits, attempting to use the connection should fail
        with pytest.raises(Exception):
            conn.execute("SELECT 1")


class TestRoundTrips:
    def test_projects(self, tmp_db: str) -> None:
        with get_db(tmp_db) as conn:
            conn.execute(
                "INSERT INTO projects (jira_goal_key, name, status) VALUES (?, ?, ?)",
                ("PROG-1", "Test", "active"),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM projects WHERE jira_goal_key = 'PROG-1'").fetchone()
        assert row["name"] == "Test"
        assert row["status"] == "active"

    def test_approval_queue(self, tmp_db: str) -> None:
        with get_db(tmp_db) as conn:
            conn.execute(
                "INSERT INTO approval_queue (action_type, payload, status) VALUES (?, ?, ?)",
                ("create_jira_issue", '{}', "pending"),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM approval_queue ORDER BY id DESC LIMIT 1").fetchone()
        assert row["action_type"] == "create_jira_issue"
        assert row["status"] == "pending"

    def test_approval_log(self, tmp_db: str) -> None:
        with get_db(tmp_db) as conn:
            conn.execute(
                "INSERT INTO approval_log (action_type, payload, approved_by) VALUES (?, ?, ?)",
                ("create_jira_issue", '{"a":1}', "local_user"),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM approval_log ORDER BY id DESC LIMIT 1").fetchone()
        assert row["approved_by"] == "local_user"

    def test_config(self, tmp_db: str) -> None:
        with get_db(tmp_db) as conn:
            conn.execute(
                "INSERT INTO config (key, value) VALUES (?, ?)",
                ("theme", "dark"),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM config WHERE key = 'theme'").fetchone()
        assert row["value"] == "dark"


import pytest
