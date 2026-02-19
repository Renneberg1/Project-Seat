"""Tests for approval queue routes."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

from src.database import get_db, init_db
from src.engine.approval import ApprovalEngine
from src.models.approval import ApprovalAction, ApprovalStatus


class TestApprovalQueue:
    def test_get_returns_200_empty(self, client) -> None:
        resp = client.get("/approval/")
        assert resp.status_code == 200

    def test_shows_pending_items(self, client, tmp_db: str) -> None:
        engine = ApprovalEngine(db_path=tmp_db)
        engine.propose(ApprovalAction.CREATE_JIRA_ISSUE, {"key": "test"}, preview="Create Goal")
        engine.propose(ApprovalAction.CREATE_JIRA_VERSION, {"name": "v1"}, preview="Create Version")

        # Need to patch settings so the routes use the same tmp_db
        with patch("src.web.routes.approval.ApprovalEngine", return_value=engine):
            resp = client.get("/approval/")

        assert resp.status_code == 200
        assert "Create Goal" in resp.text
        assert "Create Version" in resp.text


class TestRejectItem:
    def test_post_reject(self, client, tmp_db: str) -> None:
        engine = ApprovalEngine(db_path=tmp_db)
        item_id = engine.propose(ApprovalAction.CREATE_JIRA_ISSUE, {}, preview="Reject me")

        with patch("src.web.routes.approval.ApprovalEngine", return_value=engine):
            resp = client.post(f"/approval/{item_id}/reject")

        assert resp.status_code == 200
        item = engine.get(item_id)
        assert item.status == ApprovalStatus.REJECTED


class TestApproveItem:
    def test_post_approve_executes(self, client, tmp_db: str) -> None:
        engine = ApprovalEngine(db_path=tmp_db)
        item_id = engine.propose(
            ApprovalAction.CREATE_JIRA_ISSUE,
            {"project_key": "PROG", "issue_type_id": "10423", "summary": "Test"},
            preview="Create Goal",
        )

        mock_execute = AsyncMock(return_value=engine.get(item_id))
        with patch("src.web.routes.approval.SpinUpService") as MockSvc:
            MockSvc.return_value.execute_approved_item = mock_execute
            resp = client.post(f"/approval/{item_id}/approve")

        assert resp.status_code == 200


class TestApproveAll:
    def test_processes_all_pending(self, client, tmp_db: str) -> None:
        engine = ApprovalEngine(db_path=tmp_db)
        id1 = engine.propose(ApprovalAction.CREATE_JIRA_ISSUE, {}, preview="a")
        id2 = engine.propose(ApprovalAction.CREATE_JIRA_VERSION, {}, preview="b")

        mock_execute = AsyncMock(side_effect=[engine.get(id1), engine.get(id2)])
        with patch("src.web.routes.approval.ApprovalEngine", return_value=engine), \
             patch("src.web.routes.approval.SpinUpService") as MockSvc:
            MockSvc.return_value.execute_approved_item = mock_execute
            resp = client.post("/approval/approve-all")

        assert resp.status_code == 200
        assert mock_execute.call_count == 2
