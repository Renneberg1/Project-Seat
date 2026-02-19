"""Tests for the Confluence connector — v1 API methods."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.connectors.confluence import ConfluenceConnector


@pytest.fixture()
def confluence(test_settings) -> ConfluenceConnector:
    return ConfluenceConnector(settings=test_settings)


# ---------------------------------------------------------------------------
# get_page: Incoming query — assert return value
# ---------------------------------------------------------------------------


async def test_get_page_returns_page_data(confluence):
    sample = {"id": "123", "title": "Test Page"}
    mock = AsyncMock(return_value=sample)

    with patch.object(confluence, "get", mock):
        result = await confluence.get_page("123")

    mock.assert_called_once_with("/content/123", params=None)
    assert result["title"] == "Test Page"


async def test_get_page_with_expand_passes_params(confluence):
    mock = AsyncMock(return_value={"id": "123"})

    with patch.object(confluence, "get", mock):
        result = await confluence.get_page("123", expand=["body.storage", "version"])

    mock.assert_called_once_with("/content/123", params={"expand": "body.storage,version"})


# ---------------------------------------------------------------------------
# get_page_children: Incoming query — assert return value
# ---------------------------------------------------------------------------


async def test_get_page_children_delegates_to_get_all_confluence(confluence):
    mock = AsyncMock(return_value=[{"id": "1"}, {"id": "2"}])

    with patch.object(confluence, "get_all_confluence", mock):
        result = await confluence.get_page_children("123")

    mock.assert_called_once_with("/content/123/child/page")
    assert len(result) == 2


# ---------------------------------------------------------------------------
# create_page: Outgoing command — assert message sent
# ---------------------------------------------------------------------------


async def test_create_page_with_parent_includes_ancestors(confluence):
    mock = AsyncMock(return_value={"id": "999", "title": "New Page"})

    with patch.object(confluence, "post", mock):
        result = await confluence.create_page("HPP", "New Page", "<p>Hello</p>", parent_id="123")

    body = mock.call_args[1]["json_body"]
    assert body["type"] == "page"
    assert body["title"] == "New Page"
    assert body["space"]["key"] == "HPP"
    assert body["body"]["storage"]["value"] == "<p>Hello</p>"
    assert body["ancestors"] == [{"id": "123"}]


async def test_create_page_without_parent_omits_ancestors(confluence):
    mock = AsyncMock(return_value={"id": "999"})

    with patch.object(confluence, "post", mock):
        result = await confluence.create_page("HPP", "Top-level Page", "<p>Hi</p>")

    body = mock.call_args[1]["json_body"]
    assert "ancestors" not in body


# ---------------------------------------------------------------------------
# search_pages: Outgoing command — assert message sent
# ---------------------------------------------------------------------------


async def test_search_pages_builds_correct_cql(confluence):
    mock = AsyncMock(return_value=[{"id": "1"}])

    with patch.object(confluence, "get_all_confluence", mock):
        result = await confluence.search_pages("HPP", "HOP Program")

    call_kwargs = mock.call_args[1]
    assert 'space="HPP"' in call_kwargs["params"]["cql"]
    assert 'title="HOP Program"' in call_kwargs["params"]["cql"]
    assert len(result) == 1
