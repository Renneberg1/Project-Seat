"""Tests for the approval engine — queue operations and async execution."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from src.connectors.base import ConnectorError
from src.database import get_db
from src.engine.approval import ApprovalEngine
from src.models.approval import ApprovalAction, ApprovalStatus


# ---------------------------------------------------------------------------
# propose: Incoming command — assert side effect (returns item ID)
# ---------------------------------------------------------------------------


def test_propose_inserts_pending_item_and_returns_positive_id(tmp_db):
    engine = ApprovalEngine(db_path=tmp_db)

    result = engine.propose(
        ApprovalAction.CREATE_JIRA_ISSUE,
        {"project_key": "PROG"},
        preview="Create Goal",
    )

    assert isinstance(result, int)
    assert result > 0


def test_propose_stores_json_payload(tmp_db):
    engine = ApprovalEngine(db_path=tmp_db)
    payload = {"project_key": "PROG", "summary": "Test"}

    result = engine.propose(ApprovalAction.CREATE_JIRA_ISSUE, payload, preview="test")

    item = engine.get(result)
    assert json.loads(item.payload) == payload


# ---------------------------------------------------------------------------
# list_pending: Incoming query — assert return value
# ---------------------------------------------------------------------------


def test_list_pending_excludes_rejected_items(tmp_db):
    engine = ApprovalEngine(db_path=tmp_db)
    engine.propose(ApprovalAction.CREATE_JIRA_ISSUE, {}, preview="a")
    engine.propose(ApprovalAction.CREATE_JIRA_VERSION, {}, preview="b")
    items = engine.list_pending()
    engine.reject(items[0].id)

    result = engine.list_pending()

    assert len(result) == 1
    assert result[0].preview == "b"


def test_list_pending_filters_by_project_id(tmp_db):
    engine = ApprovalEngine(db_path=tmp_db)
    engine.propose(ApprovalAction.CREATE_JIRA_ISSUE, {}, preview="a", project_id=1)
    engine.propose(ApprovalAction.CREATE_JIRA_VERSION, {}, preview="b", project_id=2)

    result = engine.list_pending(project_id=1)

    assert len(result) == 1
    assert result[0].preview == "a"


# ---------------------------------------------------------------------------
# list_all: Incoming query — assert return value
# ---------------------------------------------------------------------------


def test_list_all_returns_items_across_statuses(tmp_db):
    engine = ApprovalEngine(db_path=tmp_db)
    id1 = engine.propose(ApprovalAction.CREATE_JIRA_ISSUE, {}, preview="a")
    engine.propose(ApprovalAction.CREATE_JIRA_VERSION, {}, preview="b")
    engine.reject(id1)

    result = engine.list_all()

    assert len(result) == 2
    statuses = {i.status for i in result}
    assert ApprovalStatus.REJECTED in statuses
    assert ApprovalStatus.PENDING in statuses


# ---------------------------------------------------------------------------
# get: Incoming query — assert return value
# ---------------------------------------------------------------------------


def test_get_returns_item_by_id(tmp_db):
    engine = ApprovalEngine(db_path=tmp_db)
    item_id = engine.propose(ApprovalAction.CREATE_JIRA_ISSUE, {}, preview="test")

    result = engine.get(item_id)

    assert result is not None
    assert result.id == item_id


def test_get_returns_none_for_missing_id(tmp_db):
    engine = ApprovalEngine(db_path=tmp_db)

    result = engine.get(99999)

    assert result is None


# ---------------------------------------------------------------------------
# reject: Incoming command — assert side effect
# ---------------------------------------------------------------------------


def test_reject_sets_rejected_status_and_timestamp(tmp_db):
    engine = ApprovalEngine(db_path=tmp_db)
    item_id = engine.propose(ApprovalAction.CREATE_JIRA_ISSUE, {}, preview="test")

    result = engine.reject(item_id)

    assert result.status == ApprovalStatus.REJECTED
    assert result.resolved_at is not None


# ---------------------------------------------------------------------------
# approve_and_execute: Contract tests (integration with connectors)
# ---------------------------------------------------------------------------


async def test_approve_and_execute_create_jira_issue_returns_executed(tmp_db):
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


async def test_approve_and_execute_create_confluence_page_returns_executed(tmp_db):
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


async def test_approve_and_execute_update_confluence_page_increments_version(tmp_db):
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
    put_body = mock_put.call_args[1]["json_body"]
    assert put_body["version"]["number"] == 6


async def test_approve_and_execute_writes_to_audit_log(tmp_db):
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
        result = await engine.approve_and_execute(item_id)

    with get_db(tmp_db) as conn:
        rows = conn.execute("SELECT * FROM approval_log").fetchall()
    assert len(rows) >= 1
    assert rows[-1]["action_type"] == "create_jira_version"


# ---------------------------------------------------------------------------
# approve_and_execute: Error handling
# ---------------------------------------------------------------------------


async def test_approve_and_execute_connector_error_sets_failed_status(tmp_db):
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


# ---------------------------------------------------------------------------
# approve_and_execute: Precondition violations
# ---------------------------------------------------------------------------


async def test_approve_and_execute_non_pending_raises_value_error(tmp_db):
    engine = ApprovalEngine(db_path=tmp_db)
    item_id = engine.propose(ApprovalAction.CREATE_JIRA_ISSUE, {}, preview="test")
    engine.reject(item_id)

    with pytest.raises(ValueError, match="not pending"):
        await engine.approve_and_execute(item_id)


async def test_approve_and_execute_missing_item_raises_value_error(tmp_db):
    engine = ApprovalEngine(db_path=tmp_db)

    with pytest.raises(ValueError, match="not found"):
        await engine.approve_and_execute(99999)
