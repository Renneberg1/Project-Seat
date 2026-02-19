"""Tests for the Jira connector — outgoing commands and queries."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.connectors.jira import JiraConnector


@pytest.fixture()
def jira(test_settings) -> JiraConnector:
    return JiraConnector(settings=test_settings)


# ---------------------------------------------------------------------------
# get_issue: Incoming query — assert return value
# ---------------------------------------------------------------------------


async def test_get_issue_returns_issue_data(jira):
    sample = {"id": "1", "key": "PROG-1", "fields": {}}
    mock = AsyncMock(return_value=sample)

    with patch.object(jira, "get", mock):
        result = await jira.get_issue("PROG-1")

    mock.assert_called_once_with("/issue/PROG-1", params=None)
    assert result["key"] == "PROG-1"


async def test_get_issue_with_fields_passes_comma_separated_params(jira):
    mock = AsyncMock(return_value={"fields": {}})

    with patch.object(jira, "get", mock):
        result = await jira.get_issue("PROG-1", fields=["summary", "status"])

    mock.assert_called_once_with("/issue/PROG-1", params={"fields": "summary,status"})


# ---------------------------------------------------------------------------
# create_issue: Outgoing command — assert message sent
# ---------------------------------------------------------------------------


async def test_create_issue_sends_correct_body(jira):
    mock = AsyncMock(return_value={"id": "1", "key": "PROG-2"})

    with patch.object(jira, "post", mock):
        result = await jira.create_issue("PROG", "10423", "Test Goal")

    call_body = mock.call_args[1]["json_body"]
    assert call_body["fields"]["project"]["key"] == "PROG"
    assert call_body["fields"]["issuetype"]["id"] == "10423"
    assert call_body["fields"]["summary"] == "Test Goal"
    assert result["key"] == "PROG-2"


async def test_create_issue_merges_extra_fields(jira):
    mock = AsyncMock(return_value={"id": "1", "key": "PROG-3"})
    extra = {"labels": ["release"], "duedate": "2026-09-01"}

    with patch.object(jira, "post", mock):
        result = await jira.create_issue("PROG", "10423", "Goal", fields=extra)

    call_body = mock.call_args[1]["json_body"]
    assert call_body["fields"]["labels"] == ["release"]
    assert call_body["fields"]["duedate"] == "2026-09-01"


# ---------------------------------------------------------------------------
# update_issue: Outgoing command — assert message sent
# ---------------------------------------------------------------------------


async def test_update_issue_sends_put_with_fields(jira):
    mock = AsyncMock(return_value={})

    with patch.object(jira, "put", mock):
        result = await jira.update_issue("PROG-1", fields={"summary": "Updated"})

    mock.assert_called_once_with("/issue/PROG-1", json_body={"fields": {"summary": "Updated"}})


# ---------------------------------------------------------------------------
# search: Outgoing command — assert message sent
# ---------------------------------------------------------------------------


async def test_search_delegates_to_post_all_jira_with_jql(jira):
    mock = AsyncMock(return_value=[{"id": "1"}, {"id": "2"}])

    with patch.object(jira, "post_all_jira", mock):
        result = await jira.search("project = PROG")

    assert mock.call_count == 1
    call_kwargs = mock.call_args
    assert call_kwargs[1]["body"]["jql"] == "project = PROG"


async def test_search_passes_fields_in_body(jira):
    mock = AsyncMock(return_value=[])

    with patch.object(jira, "post_all_jira", mock):
        result = await jira.search("project = PROG", fields=["summary", "status"])

    body = mock.call_args[1]["body"]
    assert body["fields"] == ["summary", "status"]


# ---------------------------------------------------------------------------
# get_issue_types: Incoming query — assert return value
# ---------------------------------------------------------------------------


async def test_get_issue_types_returns_list(jira, sample_prog_issue_types):
    mock = AsyncMock(return_value=sample_prog_issue_types)

    with patch.object(jira, "get", mock):
        result = await jira.get_issue_types("PROG")

    assert len(result) == 5
    assert result[4]["name"] == "Goal"


# ---------------------------------------------------------------------------
# create_version: Outgoing command — assert message sent
# ---------------------------------------------------------------------------


async def test_create_version_sends_correct_payload(jira):
    mock = AsyncMock(return_value={"id": "100"})

    with patch.object(jira, "post", mock):
        result = await jira.create_version("RISK", "HOP Drop 3", release_date="2026-05-06")

    body = mock.call_args[1]["json_body"]
    assert body["name"] == "HOP Drop 3"
    assert body["project"] == "RISK"
    assert body["releaseDate"] == "2026-05-06"


async def test_create_version_without_release_date_omits_key(jira):
    mock = AsyncMock(return_value={"id": "101"})

    with patch.object(jira, "post", mock):
        result = await jira.create_version("RISK", "HOP Drop 3")

    body = mock.call_args[1]["json_body"]
    assert "releaseDate" not in body


# ---------------------------------------------------------------------------
# add_issue_link: Outgoing command — assert message sent
# ---------------------------------------------------------------------------


async def test_add_issue_link_sends_correct_structure(jira):
    mock = AsyncMock(return_value={})

    with patch.object(jira, "post", mock):
        result = await jira.add_issue_link("PROG-1", "RISK-1", link_type="Relates")

    body = mock.call_args[1]["json_body"]
    assert body["type"]["name"] == "Relates"
    assert body["outwardIssue"]["key"] == "PROG-1"
    assert body["inwardIssue"]["key"] == "RISK-1"


# ---------------------------------------------------------------------------
# field_id: Incoming query — assert return value
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name,expected", [
    pytest.param("Instructions", "customfield_10870", id="mapped-field"),
    pytest.param("summary", "summary", id="unmapped-falls-through"),
])
def test_field_id_resolves_or_falls_through(jira, name, expected):
    result = jira.field_id(name)

    assert result == expected
