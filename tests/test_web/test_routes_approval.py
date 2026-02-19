"""Tests for approval queue routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from src.engine.approval import ApprovalEngine
from src.models.approval import ApprovalAction, ApprovalStatus


# ---------------------------------------------------------------------------
# GET /approval/ — approval queue page: Contract tests
# ---------------------------------------------------------------------------


def test_approval_queue_get_returns_200_empty(client):
    result = client.get("/approval/")

    assert result.status_code == 200


def test_approval_queue_shows_pending_items(client, tmp_db):
    engine = ApprovalEngine(db_path=tmp_db)
    engine.propose(ApprovalAction.CREATE_JIRA_ISSUE, {"key": "test"}, preview="Create Goal")
    engine.propose(ApprovalAction.CREATE_JIRA_VERSION, {"name": "v1"}, preview="Create Version")

    with patch("src.web.routes.approval.ApprovalEngine", return_value=engine):
        result = client.get("/approval/")

    assert result.status_code == 200
    assert "Create Goal" in result.text
    assert "Create Version" in result.text


# ---------------------------------------------------------------------------
# POST /approval/{id}/reject — reject item: Contract tests
# ---------------------------------------------------------------------------


def test_reject_item_post_updates_status(client, tmp_db):
    engine = ApprovalEngine(db_path=tmp_db)
    item_id = engine.propose(ApprovalAction.CREATE_JIRA_ISSUE, {}, preview="Reject me")

    with patch("src.web.routes.approval.ApprovalEngine", return_value=engine):
        result = client.post(f"/approval/{item_id}/reject")

    assert result.status_code == 200
    item = engine.get(item_id)
    assert item.status == ApprovalStatus.REJECTED


# ---------------------------------------------------------------------------
# POST /approval/{id}/approve — approve item: Contract tests
# ---------------------------------------------------------------------------


def test_approve_item_post_executes(client, tmp_db):
    engine = ApprovalEngine(db_path=tmp_db)
    item_id = engine.propose(
        ApprovalAction.CREATE_JIRA_ISSUE,
        {"project_key": "PROG", "issue_type_id": "10423", "summary": "Test"},
        preview="Create Goal",
    )
    mock_execute = AsyncMock(return_value=engine.get(item_id))

    with patch("src.web.routes.approval.SpinUpService") as MockSvc:
        MockSvc.return_value.execute_approved_item = mock_execute

        result = client.post(f"/approval/{item_id}/approve")

    assert result.status_code == 200


# ---------------------------------------------------------------------------
# POST /approval/approve-all — approve all: Contract tests
# ---------------------------------------------------------------------------


def test_approve_all_processes_all_pending(client, tmp_db):
    engine = ApprovalEngine(db_path=tmp_db)
    id1 = engine.propose(ApprovalAction.CREATE_JIRA_ISSUE, {}, preview="a")
    id2 = engine.propose(ApprovalAction.CREATE_JIRA_VERSION, {}, preview="b")
    mock_execute = AsyncMock(side_effect=[engine.get(id1), engine.get(id2)])

    with patch("src.web.routes.approval.ApprovalEngine", return_value=engine), \
         patch("src.web.routes.approval.SpinUpService") as MockSvc:
        MockSvc.return_value.execute_approved_item = mock_execute

        result = client.post("/approval/approve-all")

    assert result.status_code == 200
    assert mock_execute.call_count == 2
