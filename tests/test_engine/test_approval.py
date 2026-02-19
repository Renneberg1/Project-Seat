"""Tests for the approval engine — queue operations and async execution."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from src.connectors.base import ConnectorError
from src.engine.approval import ApprovalEngine
from src.models.approval import ApprovalAction, ApprovalStatus


# ---------------------------------------------------------------------------
# Sync queue tests
# ---------------------------------------------------------------------------


class TestPropose:
    def test_inserts_pending_item(self, tmp_db: str) -> None:
        engine = ApprovalEngine(db_path=tmp_db)
        item_id = engine.propose(
            ApprovalAction.CREATE_JIRA_ISSUE,
            {"project_key": "PROG"},
            preview="Create Goal",
        )
        assert isinstance(item_id, int)
        assert item_id > 0

    def test_stores_json_payload(self, tmp_db: str) -> None:
        engine = ApprovalEngine(db_path=tmp_db)
        payload = {"project_key": "PROG", "summary": "Test"}
        item_id = engine.propose(
            ApprovalAction.CREATE_JIRA_ISSUE, payload, preview="test"
        )
        item = engine.get(item_id)
        assert json.loads(item.payload) == payload


class TestListPending:
    def test_returns_only_pending(self, tmp_db: str) -> None:
        engine = ApprovalEngine(db_path=tmp_db)
        engine.propose(ApprovalAction.CREATE_JIRA_ISSUE, {}, preview="a")
        engine.propose(ApprovalAction.CREATE_JIRA_VERSION, {}, preview="b")
        # Reject one
        items = engine.list_pending()
        engine.reject(items[0].id)

        pending = engine.list_pending()
        assert len(pending) == 1
        assert pending[0].preview == "b"

    def test_filter_by_project_id(self, tmp_db: str) -> None:
        engine = ApprovalEngine(db_path=tmp_db)
        engine.propose(ApprovalAction.CREATE_JIRA_ISSUE, {}, preview="a", project_id=1)
        engine.propose(ApprovalAction.CREATE_JIRA_VERSION, {}, preview="b", project_id=2)

        result = engine.list_pending(project_id=1)
        assert len(result) == 1
        assert result[0].preview == "a"


class TestListAll:
    def test_returns_all_statuses(self, tmp_db: str) -> None:
        engine = ApprovalEngine(db_path=tmp_db)
        id1 = engine.propose(ApprovalAction.CREATE_JIRA_ISSUE, {}, preview="a")
        engine.propose(ApprovalAction.CREATE_JIRA_VERSION, {}, preview="b")
        engine.reject(id1)

        all_items = engine.list_all()
        assert len(all_items) == 2
        statuses = {i.status for i in all_items}
        assert ApprovalStatus.REJECTED in statuses
        assert ApprovalStatus.PENDING in statuses


class TestGet:
    def test_returns_item_by_id(self, tmp_db: str) -> None:
        engine = ApprovalEngine(db_path=tmp_db)
        item_id = engine.propose(ApprovalAction.CREATE_JIRA_ISSUE, {}, preview="test")
        item = engine.get(item_id)
        assert item is not None
        assert item.id == item_id

    def test_returns_none_for_missing(self, tmp_db: str) -> None:
        engine = ApprovalEngine(db_path=tmp_db)
        assert engine.get(99999) is None


class TestReject:
    def test_sets_rejected_status(self, tmp_db: str) -> None:
        engine = ApprovalEngine(db_path=tmp_db)
        item_id = engine.propose(ApprovalAction.CREATE_JIRA_ISSUE, {}, preview="test")
        result = engine.reject(item_id)
        assert result.status == ApprovalStatus.REJECTED
        assert result.resolved_at is not None


# ---------------------------------------------------------------------------
# Async execution tests
# ---------------------------------------------------------------------------


class TestApproveAndExecute:
    async def test_create_jira_issue(self, tmp_db: str) -> None:
        engine = ApprovalEngine(db_path=tmp_db)
        item_id = engine.propose(
            ApprovalAction.CREATE_JIRA_ISSUE,
            {"project_key": "PROG", "issue_type_id": "10423", "summary": "Test"},
            preview="Create Goal",
        )

        mock_create = AsyncMock(return_value={"id": "1", "key": "PROG-999"})
        mock_close = AsyncMock()

        with patch("src.engine.approval.JiraConnector") as MockJira:
            instance = MockJira.return_value
            instance.create_issue = mock_create
            instance.close = mock_close

            result = await engine.approve_and_execute(item_id)

        assert result.status == ApprovalStatus.EXECUTED
        result_data = json.loads(result.result)
        assert result_data["key"] == "PROG-999"

    async def test_create_confluence_page(self, tmp_db: str) -> None:
        engine = ApprovalEngine(db_path=tmp_db)
        item_id = engine.propose(
            ApprovalAction.CREATE_CONFLUENCE_PAGE,
            {"space_key": "HPP", "title": "Charter", "body_storage": "<p>Hi</p>"},
            preview="Create Charter",
        )

        mock_create = AsyncMock(return_value={"id": "12345", "title": "Charter"})
        mock_close = AsyncMock()

        with patch("src.engine.approval.ConfluenceConnector") as MockConf:
            instance = MockConf.return_value
            instance.create_page = mock_create
            instance.close = mock_close

            result = await engine.approve_and_execute(item_id)

        assert result.status == ApprovalStatus.EXECUTED
        result_data = json.loads(result.result)
        assert result_data["id"] == "12345"

    async def test_connector_raises_sets_failed(self, tmp_db: str) -> None:
        engine = ApprovalEngine(db_path=tmp_db)
        item_id = engine.propose(
            ApprovalAction.CREATE_JIRA_ISSUE,
            {"project_key": "PROG", "issue_type_id": "10423", "summary": "Fail"},
            preview="Fail test",
        )

        with patch("src.engine.approval.JiraConnector") as MockJira:
            instance = MockJira.return_value
            instance.create_issue = AsyncMock(side_effect=ConnectorError(500, "boom"))
            instance.close = AsyncMock()

            result = await engine.approve_and_execute(item_id)

        assert result.status == ApprovalStatus.FAILED
        assert "boom" in json.loads(result.result)["error"]

    async def test_non_pending_raises_value_error(self, tmp_db: str) -> None:
        engine = ApprovalEngine(db_path=tmp_db)
        item_id = engine.propose(ApprovalAction.CREATE_JIRA_ISSUE, {}, preview="test")
        engine.reject(item_id)

        with pytest.raises(ValueError, match="not pending"):
            await engine.approve_and_execute(item_id)

    async def test_missing_item_raises_value_error(self, tmp_db: str) -> None:
        engine = ApprovalEngine(db_path=tmp_db)
        with pytest.raises(ValueError, match="not found"):
            await engine.approve_and_execute(99999)

    async def test_writes_to_audit_log(self, tmp_db: str) -> None:
        engine = ApprovalEngine(db_path=tmp_db)
        item_id = engine.propose(
            ApprovalAction.CREATE_JIRA_VERSION,
            {"project_key": "RISK", "name": "Test Version"},
            preview="Create version",
            project_id=1,
        )

        with patch("src.engine.approval.JiraConnector") as MockJira:
            instance = MockJira.return_value
            instance.create_version = AsyncMock(return_value={"id": "100"})
            instance.close = AsyncMock()

            await engine.approve_and_execute(item_id)

        from src.database import get_db
        with get_db(tmp_db) as conn:
            rows = conn.execute("SELECT * FROM approval_log").fetchall()
        assert len(rows) >= 1
        assert rows[-1]["action_type"] == "create_jira_version"

    async def test_update_confluence_page_increments_version(self, tmp_db: str) -> None:
        engine = ApprovalEngine(db_path=tmp_db)
        item_id = engine.propose(
            ApprovalAction.UPDATE_CONFLUENCE_PAGE,
            {"page_id": "123", "title": "Updated", "body_storage": "<p>New</p>"},
            preview="Update page",
        )

        mock_get_page = AsyncMock(return_value={"version": {"number": 5}})
        mock_put = AsyncMock(return_value={"id": "123", "version": {"number": 6}})
        mock_close = AsyncMock()

        with patch("src.engine.approval.ConfluenceConnector") as MockConf:
            instance = MockConf.return_value
            instance.get_page = mock_get_page
            instance.put = mock_put
            instance.close = mock_close

            result = await engine.approve_and_execute(item_id)

        assert result.status == ApprovalStatus.EXECUTED
        # Verify version was incremented
        put_body = mock_put.call_args[1]["json_body"]
        assert put_body["version"]["number"] == 6
