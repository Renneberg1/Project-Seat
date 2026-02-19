"""Tests for the Jira connector."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.connectors.jira import JiraConnector
from tests.conftest import make_response


@pytest.fixture()
def jira(test_settings) -> JiraConnector:
    return JiraConnector(settings=test_settings)


class TestGetIssue:
    async def test_calls_correct_path(self, jira: JiraConnector) -> None:
        sample = {"id": "1", "key": "PROG-1", "fields": {}}
        mock = AsyncMock(return_value=sample)
        with patch.object(jira, "get", mock):
            result = await jira.get_issue("PROG-1")
        mock.assert_called_once_with("/issue/PROG-1", params=None)
        assert result["key"] == "PROG-1"

    async def test_with_fields_param(self, jira: JiraConnector) -> None:
        mock = AsyncMock(return_value={"fields": {}})
        with patch.object(jira, "get", mock):
            await jira.get_issue("PROG-1", fields=["summary", "status"])
        mock.assert_called_once_with("/issue/PROG-1", params={"fields": "summary,status"})


class TestCreateIssue:
    async def test_sends_correct_body(self, jira: JiraConnector) -> None:
        mock = AsyncMock(return_value={"id": "1", "key": "PROG-2"})
        with patch.object(jira, "post", mock):
            result = await jira.create_issue("PROG", "10423", "Test Goal")
        call_body = mock.call_args[1]["json_body"]
        assert call_body["fields"]["project"]["key"] == "PROG"
        assert call_body["fields"]["issuetype"]["id"] == "10423"
        assert call_body["fields"]["summary"] == "Test Goal"
        assert result["key"] == "PROG-2"


class TestUpdateIssue:
    async def test_sends_put_with_fields(self, jira: JiraConnector) -> None:
        mock = AsyncMock(return_value={})
        with patch.object(jira, "put", mock):
            await jira.update_issue("PROG-1", fields={"summary": "Updated"})
        mock.assert_called_once_with("/issue/PROG-1", json_body={"fields": {"summary": "Updated"}})


class TestSearch:
    async def test_uses_jql_via_pagination(self, jira: JiraConnector) -> None:
        mock = AsyncMock(return_value=[{"id": "1"}, {"id": "2"}])
        with patch.object(jira, "post_all_jira", mock):
            results = await jira.search("project = PROG")
        mock.assert_called_once()
        call_kwargs = mock.call_args
        assert call_kwargs[1]["body"]["jql"] == "project = PROG"


class TestGetIssueTypes:
    async def test_extracts_issue_types(self, jira: JiraConnector, sample_prog_issue_types: dict[str, Any]) -> None:
        mock = AsyncMock(return_value=sample_prog_issue_types)
        with patch.object(jira, "get", mock):
            result = await jira.get_issue_types("PROG")
        assert len(result) == 5
        assert result[4]["name"] == "Goal"


class TestCreateVersion:
    async def test_payload(self, jira: JiraConnector) -> None:
        mock = AsyncMock(return_value={"id": "100"})
        with patch.object(jira, "post", mock):
            await jira.create_version("RISK", "HOP Drop 3", release_date="2026-05-06")
        body = mock.call_args[1]["json_body"]
        assert body["name"] == "HOP Drop 3"
        assert body["project"] == "RISK"
        assert body["releaseDate"] == "2026-05-06"


class TestAddIssueLink:
    async def test_payload_structure(self, jira: JiraConnector) -> None:
        mock = AsyncMock(return_value={})
        with patch.object(jira, "post", mock):
            await jira.add_issue_link("PROG-1", "RISK-1", link_type="Relates")
        body = mock.call_args[1]["json_body"]
        assert body["type"]["name"] == "Relates"
        assert body["outwardIssue"]["key"] == "PROG-1"
        assert body["inwardIssue"]["key"] == "RISK-1"


class TestFieldId:
    def test_resolves_from_map(self, jira: JiraConnector) -> None:
        assert jira.field_id("Instructions") == "customfield_10870"

    def test_returns_name_if_not_mapped(self, jira: JiraConnector) -> None:
        assert jira.field_id("summary") == "summary"
