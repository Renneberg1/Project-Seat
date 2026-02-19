"""Tests for database schema, connection helpers, and CRUD round-trips."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.database import get_db, init_db


# ---------------------------------------------------------------------------
# init_db: Contract tests
# ---------------------------------------------------------------------------


def test_init_db_creates_all_required_tables(tmp_path):
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


def test_init_db_is_idempotent(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)

    result = init_db(db_path)  # second call should not raise

    # No exception means success; init_db returns None
    assert result is None


# ---------------------------------------------------------------------------
# get_db: Contract tests
# ---------------------------------------------------------------------------


def test_get_db_returns_connection_with_row_factory(tmp_db):
    with get_db(tmp_db) as conn:
        result = conn.row_factory

    assert result is sqlite3.Row


def test_get_db_closes_connection_after_exit(tmp_db):
    with get_db(tmp_db) as conn:
        pass

    with pytest.raises(Exception):
        conn.execute("SELECT 1")


# ---------------------------------------------------------------------------
# Round-trip tests: Insert and query each table
# ---------------------------------------------------------------------------


def test_projects_round_trip_insert_and_query(tmp_db):
    with get_db(tmp_db) as conn:
        conn.execute(
            "INSERT INTO projects (jira_goal_key, name, status) VALUES (?, ?, ?)",
            ("PROG-1", "Test", "active"),
        )
        conn.commit()

        result = conn.execute("SELECT * FROM projects WHERE jira_goal_key = 'PROG-1'").fetchone()

    assert result["name"] == "Test"
    assert result["status"] == "active"


def test_approval_queue_round_trip_insert_and_query(tmp_db):
    with get_db(tmp_db) as conn:
        conn.execute(
            "INSERT INTO approval_queue (action_type, payload, status) VALUES (?, ?, ?)",
            ("create_jira_issue", '{}', "pending"),
        )
        conn.commit()

        result = conn.execute("SELECT * FROM approval_queue ORDER BY id DESC LIMIT 1").fetchone()

    assert result["action_type"] == "create_jira_issue"
    assert result["status"] == "pending"


def test_approval_log_round_trip_insert_and_query(tmp_db):
    with get_db(tmp_db) as conn:
        conn.execute(
            "INSERT INTO approval_log (action_type, payload, approved_by) VALUES (?, ?, ?)",
            ("create_jira_issue", '{"a":1}', "local_user"),
        )
        conn.commit()

        result = conn.execute("SELECT * FROM approval_log ORDER BY id DESC LIMIT 1").fetchone()

    assert result["approved_by"] == "local_user"


def test_config_round_trip_insert_and_query(tmp_db):
    with get_db(tmp_db) as conn:
        conn.execute(
            "INSERT INTO config (key, value) VALUES (?, ?)",
            ("theme", "dark"),
        )
        conn.commit()

        result = conn.execute("SELECT * FROM config WHERE key = 'theme'").fetchone()

    assert result["value"] == "dark"
