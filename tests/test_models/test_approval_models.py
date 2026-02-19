"""Tests for approval queue models and enums."""

from __future__ import annotations

import pytest

from src.database import get_db
from src.models.approval import ApprovalAction, ApprovalItem, ApprovalStatus


def _insert_project(db_path):
    with get_db(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO projects (jira_goal_key, name, status, phase) VALUES (?, ?, ?, ?)",
            ("PROG-100", "Test", "active", "planning"),
        )
        conn.commit()
        return cursor.lastrowid


# ---------------------------------------------------------------------------
# ApprovalAction enum: Contract tests
# ---------------------------------------------------------------------------


def test_approval_action_has_six_values():
    result = {a.value for a in ApprovalAction}

    expected = {
        "create_jira_issue",
        "create_jira_version",
        "update_jira_issue",
        "add_issue_link",
        "create_confluence_page",
        "update_confluence_page",
    }
    assert result == expected


def test_approval_action_invalid_value_raises_value_error():
    with pytest.raises(ValueError):
        ApprovalAction("nonexistent_action")


# ---------------------------------------------------------------------------
# ApprovalStatus enum: Contract tests
# ---------------------------------------------------------------------------


def test_approval_status_has_five_values():
    result = {s.value for s in ApprovalStatus}

    expected = {"pending", "approved", "rejected", "executed", "failed"}
    assert result == expected


def test_approval_status_invalid_value_raises_value_error():
    with pytest.raises(ValueError):
        ApprovalStatus("bogus")


# ---------------------------------------------------------------------------
# ApprovalItem.from_row: Contract test
# ---------------------------------------------------------------------------


def test_approval_item_from_row_round_trip(tmp_db):
    pid = _insert_project(tmp_db)
    with get_db(tmp_db) as conn:
        conn.execute(
            """INSERT INTO approval_queue
               (project_id, action_type, payload, preview, context, status)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (pid, "create_jira_issue", '{"key": "PROG"}', "Create goal", "spin-up", "pending"),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM approval_queue ORDER BY id DESC LIMIT 1").fetchone()

    result = ApprovalItem.from_row(row)

    assert result.action_type == ApprovalAction.CREATE_JIRA_ISSUE
    assert result.status == ApprovalStatus.PENDING
    assert result.payload == '{"key": "PROG"}'
    assert result.preview == "Create goal"
    assert result.context == "spin-up"
    assert result.project_id == pid
    assert result.result is None
    assert result.resolved_at is None
