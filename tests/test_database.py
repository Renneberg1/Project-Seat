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
    expected = {
        "projects", "approval_log", "transcript_cache", "approval_queue",
        "config", "releases", "release_documents", "transcript_suggestions",
        "team_progress_snapshots", "health_reviews", "ceo_reviews",
        "charter_suggestions", "schema_versions",
    }
    assert expected.issubset(tables)


def test_init_db_is_idempotent(tmp_path):
    db_path = str(tmp_path / "test.db")
    init_db(db_path)

    result = init_db(db_path)  # second call should not raise

    # No exception means success; init_db returns None
    assert result is None


def test_init_db_migrations_only_run_once(tmp_path):
    """Verify that migrations are tracked and not re-applied."""
    db_path = str(tmp_path / "test.db")
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    versions_1 = {
        row[0] for row in conn.execute("SELECT version FROM schema_versions").fetchall()
    }
    conn.close()

    # Second init should not error and should not add duplicate versions
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    versions_2 = {
        row[0] for row in conn.execute("SELECT version FROM schema_versions").fetchall()
    }
    conn.close()

    assert versions_1 == versions_2
    assert len(versions_1) > 0  # at least some migrations ran


def test_wal_mode_enabled(tmp_path):
    """Verify WAL journal mode is set on both init_db and get_db connections."""
    db_path = str(tmp_path / "test.db")
    init_db(db_path)

    with get_db(db_path) as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"


# ---------------------------------------------------------------------------
# CASCADE tests
# ---------------------------------------------------------------------------


def test_cascade_deletes_child_rows(tmp_path):
    """Deleting a project should cascade to all child tables."""
    db_path = str(tmp_path / "test.db")
    init_db(db_path)

    with get_db(db_path) as conn:
        # Create a project
        conn.execute(
            "INSERT INTO projects (jira_goal_key, name, status) VALUES (?, ?, ?)",
            ("PROG-1", "Test", "active"),
        )
        project_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Add child rows in various tables
        conn.execute(
            "INSERT INTO approval_log (project_id, action_type, payload) VALUES (?, ?, ?)",
            (project_id, "CREATE_JIRA_ISSUE", "{}"),
        )
        conn.execute(
            "INSERT INTO approval_queue (project_id, action_type, payload) VALUES (?, ?, ?)",
            (project_id, "CREATE_JIRA_ISSUE", "{}"),
        )
        conn.execute(
            "INSERT INTO transcript_cache (project_id, filename, raw_text) VALUES (?, ?, ?)",
            (project_id, "test.vtt", "text"),
        )
        transcript_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO transcript_suggestions (transcript_id, project_id, suggestion_type, title) VALUES (?, ?, ?, ?)",
            (transcript_id, project_id, "risk", "Test Risk"),
        )
        conn.execute(
            "INSERT INTO health_reviews (project_id, health_rating) VALUES (?, ?)",
            (project_id, "Green"),
        )
        conn.execute(
            "INSERT INTO ceo_reviews (project_id) VALUES (?)",
            (project_id,),
        )
        conn.execute(
            "INSERT INTO charter_suggestions (project_id, section_name) VALUES (?, ?)",
            (project_id, "Objectives"),
        )
        conn.execute(
            "INSERT INTO team_progress_snapshots (project_id, snapshot_date, data_json) VALUES (?, ?, ?)",
            (project_id, "2026-01-01", "{}"),
        )
        conn.execute(
            "INSERT INTO releases (project_id, name) VALUES (?, ?)",
            (project_id, "v1.0"),
        )
        release_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO release_documents (release_id, doc_title) VALUES (?, ?)",
            (release_id, "Doc A"),
        )
        conn.commit()

        # Verify child rows exist
        assert conn.execute("SELECT COUNT(*) FROM approval_log WHERE project_id = ?", (project_id,)).fetchone()[0] > 0
        assert conn.execute("SELECT COUNT(*) FROM transcript_suggestions WHERE project_id = ?", (project_id,)).fetchone()[0] > 0

        # Delete the project
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        conn.commit()

        # Verify all child rows are gone
        for table in [
            "approval_log", "approval_queue", "transcript_cache",
            "transcript_suggestions", "health_reviews", "ceo_reviews",
            "charter_suggestions", "team_progress_snapshots", "releases",
        ]:
            count = conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE project_id = ?", (project_id,)
            ).fetchone()[0]
            assert count == 0, f"Expected 0 rows in {table}, got {count}"

        # release_documents should also be gone (cascaded through releases)
        assert conn.execute("SELECT COUNT(*) FROM release_documents WHERE release_id = ?", (release_id,)).fetchone()[0] == 0


def test_indexes_created(tmp_path):
    """Verify that expected indexes exist after init_db."""
    db_path = str(tmp_path / "test.db")
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    indexes = {
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
    }
    conn.close()

    expected_indexes = {
        "idx_transcript_suggestions_tid",
        "idx_transcript_suggestions_proj",
        "idx_approval_queue_proj",
        "idx_approval_queue_status",
        "idx_charter_suggestions_proj",
        "idx_health_reviews_proj",
        "idx_ceo_reviews_proj",
        "idx_approval_log_proj",
    }
    assert expected_indexes.issubset(indexes)


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
