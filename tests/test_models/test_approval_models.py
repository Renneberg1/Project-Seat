"""Tests for approval queue models and enums."""

from __future__ import annotations

import pytest

from src.database import get_db
from src.models.approval import ApprovalAction, ApprovalItem, ApprovalStatus


class TestApprovalAction:
    def test_all_six_values(self) -> None:
        expected = {
            "create_jira_issue",
            "create_jira_version",
            "update_jira_issue",
            "add_issue_link",
            "create_confluence_page",
            "update_confluence_page",
        }
        actual = {a.value for a in ApprovalAction}
        assert actual == expected

    def test_invalid_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            ApprovalAction("nonexistent_action")


class TestApprovalStatus:
    def test_all_five_values(self) -> None:
        expected = {"pending", "approved", "rejected", "executed", "failed"}
        actual = {s.value for s in ApprovalStatus}
        assert actual == expected

    def test_invalid_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            ApprovalStatus("bogus")


class TestApprovalItem:
    def test_from_row_round_trip(self, tmp_db: str) -> None:
        with get_db(tmp_db) as conn:
            conn.execute(
                """INSERT INTO approval_queue
                   (project_id, action_type, payload, preview, context, status)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (1, "create_jira_issue", '{"key": "PROG"}', "Create goal", "spin-up", "pending"),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM approval_queue ORDER BY id DESC LIMIT 1").fetchone()

        item = ApprovalItem.from_row(row)
        assert item.action_type == ApprovalAction.CREATE_JIRA_ISSUE
        assert item.status == ApprovalStatus.PENDING
        assert item.payload == '{"key": "PROG"}'
        assert item.preview == "Create goal"
        assert item.context == "spin-up"
        assert item.project_id == 1
        assert item.result is None
        assert item.resolved_at is None
