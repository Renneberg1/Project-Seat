"""Tests for ApprovalRepository queue and audit log operations."""

from __future__ import annotations

import json

from src.models.approval import ApprovalAction, ApprovalStatus
from src.repositories.approval_repo import ApprovalRepository
from src.repositories.project_repo import ProjectRepository


def _make_project(tmp_db: str) -> int:
    return ProjectRepository(tmp_db).create(jira_goal_key="PROG-1", name="Test")


class TestPropose:
    def test_propose_returns_id(self, tmp_db: str):
        repo = ApprovalRepository(tmp_db)
        item_id = repo.propose(
            action_type=ApprovalAction.CREATE_JIRA_ISSUE,
            payload={"key": "RISK-1"},
            preview="Create risk RISK-1",
        )
        assert isinstance(item_id, int)
        assert item_id >= 1

    def test_propose_with_project_id(self, tmp_db: str):
        repo = ApprovalRepository(tmp_db)
        pid = _make_project(tmp_db)
        item_id = repo.propose(
            action_type=ApprovalAction.CREATE_JIRA_ISSUE,
            payload={"summary": "New risk"},
            preview="Create risk",
            context="From transcript",
            project_id=pid,
        )
        item = repo.get(item_id)
        assert item.project_id == pid
        assert item.context == "From transcript"


class TestGet:
    def test_get_found(self, tmp_db: str):
        repo = ApprovalRepository(tmp_db)
        item_id = repo.propose(
            action_type=ApprovalAction.UPDATE_CONFLUENCE_PAGE,
            payload={"page_id": "123"},
            preview="Update charter",
        )
        item = repo.get(item_id)
        assert item is not None
        assert item.action_type == ApprovalAction.UPDATE_CONFLUENCE_PAGE
        assert item.status == ApprovalStatus.PENDING
        assert item.result is None

    def test_get_not_found(self, tmp_db: str):
        repo = ApprovalRepository(tmp_db)
        assert repo.get(9999) is None


class TestListByStatus:
    def test_list_by_status_pending(self, tmp_db: str):
        repo = ApprovalRepository(tmp_db)
        repo.propose(ApprovalAction.CREATE_JIRA_ISSUE, {"a": 1}, "p1")
        repo.propose(ApprovalAction.CREATE_JIRA_ISSUE, {"a": 2}, "p2")
        items = repo.list_by_status(ApprovalStatus.PENDING)
        assert len(items) == 2

    def test_list_by_status_empty(self, tmp_db: str):
        repo = ApprovalRepository(tmp_db)
        items = repo.list_by_status(ApprovalStatus.EXECUTED)
        assert items == []

    def test_list_by_status_with_project_filter(self, tmp_db: str):
        repo = ApprovalRepository(tmp_db)
        pid = _make_project(tmp_db)
        repo.propose(ApprovalAction.CREATE_JIRA_ISSUE, {}, "p1", project_id=pid)
        repo.propose(ApprovalAction.CREATE_JIRA_ISSUE, {}, "p2", project_id=None)
        items = repo.list_by_status(ApprovalStatus.PENDING, project_id=pid)
        assert len(items) == 1

    def test_list_all(self, tmp_db: str):
        repo = ApprovalRepository(tmp_db)
        pid = _make_project(tmp_db)
        repo.propose(ApprovalAction.CREATE_JIRA_ISSUE, {}, "p1", project_id=pid)
        repo.propose(ApprovalAction.CREATE_JIRA_ISSUE, {}, "p2")
        assert len(repo.list_all()) == 2
        assert len(repo.list_all(project_id=pid)) == 1


class TestUpdateStatus:
    def test_update_status(self, tmp_db: str):
        repo = ApprovalRepository(tmp_db)
        item_id = repo.propose(ApprovalAction.CREATE_JIRA_ISSUE, {}, "p")
        repo.update_status(item_id, ApprovalStatus.APPROVED)
        item = repo.get(item_id)
        assert item.status == ApprovalStatus.APPROVED
        assert item.resolved_at is not None

    def test_mark_approved(self, tmp_db: str):
        repo = ApprovalRepository(tmp_db)
        item_id = repo.propose(ApprovalAction.CREATE_JIRA_ISSUE, {}, "p")
        repo.mark_approved(item_id)
        assert repo.get(item_id).status == ApprovalStatus.APPROVED

    def test_set_result(self, tmp_db: str):
        repo = ApprovalRepository(tmp_db)
        item_id = repo.propose(ApprovalAction.CREATE_JIRA_ISSUE, {}, "p")
        repo.set_result(item_id, ApprovalStatus.EXECUTED, '{"key":"RISK-1"}')
        item = repo.get(item_id)
        assert item.status == ApprovalStatus.EXECUTED
        assert item.result == '{"key":"RISK-1"}'
        assert item.resolved_at is not None

    def test_reset_to_pending(self, tmp_db: str):
        repo = ApprovalRepository(tmp_db)
        item_id = repo.propose(ApprovalAction.CREATE_JIRA_ISSUE, {}, "p")
        repo.update_status(item_id, ApprovalStatus.FAILED)
        repo.reset_to_pending(item_id)
        item = repo.get(item_id)
        assert item.status == ApprovalStatus.PENDING
        assert item.result is None
        assert item.resolved_at is None

    def test_update_payload(self, tmp_db: str):
        repo = ApprovalRepository(tmp_db)
        item_id = repo.propose(ApprovalAction.CREATE_JIRA_ISSUE, {"v": 1}, "p")
        repo.update_payload(item_id, '{"v": 2}')
        item = repo.get(item_id)
        assert json.loads(item.payload) == {"v": 2}


class TestAuditLog:
    def test_log_audit(self, tmp_db: str):
        repo = ApprovalRepository(tmp_db)
        item_id = repo.propose(ApprovalAction.CREATE_JIRA_ISSUE, {}, "p")
        repo.update_status(item_id, ApprovalStatus.EXECUTED)
        item = repo.get(item_id)
        repo.log_audit(item)  # should not raise

    def test_log_audit_raw(self, tmp_db: str):
        repo = ApprovalRepository(tmp_db)
        pid = _make_project(tmp_db)
        repo.log_audit_raw(pid, "release_lock", {"release": "v1.0"})
        # Verify it was written (no direct read API, just ensure no error)
