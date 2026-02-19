"""Tests for Confluence v2 API methods."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.connectors.base import ConnectorError
from src.connectors.confluence import ConfluenceConnector


@pytest.fixture()
def confluence(test_settings) -> ConfluenceConnector:
    return ConfluenceConnector(settings=test_settings)


# ---------------------------------------------------------------------------
# _v2_url: Incoming query — assert return value
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path,expected_suffix", [
    pytest.param("/pages/12345/children", "/pages/12345/children", id="nested-path"),
    pytest.param("/pages", "/pages", id="root-path"),
])
def test_v2_url_builds_correct_absolute_url(confluence, path, expected_suffix):
    result = confluence._v2_url(path)

    assert result == f"https://test-company.atlassian.net/wiki/api/v2{expected_suffix}"


# ---------------------------------------------------------------------------
# get_child_pages_v2: Incoming query — assert return value
# ---------------------------------------------------------------------------


async def test_get_child_pages_v2_delegates_to_v2_get_all(confluence):
    mock = AsyncMock(return_value=[{"id": "1", "title": "Child 1"}])

    with patch.object(confluence, "_v2_get_all", mock):
        result = await confluence.get_child_pages_v2("12345")

    mock.assert_called_once_with("/pages/12345/children")
    assert len(result) == 1


async def test_v2_get_all_follows_cursor_pagination(confluence):
    page1 = {
        "results": [{"id": "1"}],
        "_links": {"next": "/wiki/api/v2/pages/12345/children?cursor=abc"},
    }
    page2 = {
        "results": [{"id": "2"}],
        "_links": {},
    }
    mock = AsyncMock(side_effect=[page1, page2])

    with patch.object(confluence, "get", mock):
        result = await confluence._v2_get_all("/pages/12345/children")

    assert len(result) == 2
    assert result[0]["id"] == "1"
    assert result[1]["id"] == "2"
    assert mock.call_count == 2


# ---------------------------------------------------------------------------
# get_page_v2: Incoming query — assert return value
# ---------------------------------------------------------------------------


async def test_get_page_v2_calls_correct_url_and_returns_data(confluence):
    sample = {"id": "123", "title": "Test", "_links": {"webui": "/wiki/page/123"}}
    mock = AsyncMock(return_value=sample)

    with patch.object(confluence, "get", mock):
        result = await confluence.get_page_v2("123")

    expected_url = "https://test-company.atlassian.net/wiki/api/v2/pages/123"
    mock.assert_called_once_with(expected_url)
    assert result["_links"]["webui"] == "/wiki/page/123"


# ---------------------------------------------------------------------------
# get_page_versions: Incoming query — assert return value
# ---------------------------------------------------------------------------


async def test_get_page_versions_returns_results_with_limit(confluence):
    data = {"results": [{"number": 3}, {"number": 2}]}
    mock = AsyncMock(return_value=data)

    with patch.object(confluence, "get", mock):
        result = await confluence.get_page_versions("123", limit=5)

    assert len(result) == 2
    call_args = mock.call_args
    assert call_args[1]["params"]["limit"] == 5


# ---------------------------------------------------------------------------
# get_content_property: Incoming query — assert return value
# ---------------------------------------------------------------------------


async def test_get_content_property_returns_property_data(confluence):
    sample = {"key": "sc-dm-document-metadata", "value": {"documentId": "abc"}}
    mock = AsyncMock(return_value=sample)

    with patch.object(confluence, "get", mock):
        result = await confluence.get_content_property("123", "sc-dm-document-metadata")

    assert result["value"]["documentId"] == "abc"
    mock.assert_called_once_with("/content/123/property/sc-dm-document-metadata")


async def test_get_content_property_returns_none_on_404(confluence):
    mock = AsyncMock(side_effect=ConnectorError(404, "Not found"))

    with patch.object(confluence, "get", mock):
        result = await confluence.get_content_property("123", "missing-key")

    assert result is None


async def test_get_content_property_raises_on_non_404_error(confluence):
    mock = AsyncMock(side_effect=ConnectorError(500, "Server error"))

    with patch.object(confluence, "get", mock):
        with pytest.raises(ConnectorError):
            await confluence.get_content_property("123", "some-key")


# ---------------------------------------------------------------------------
# get_user_display_name: Incoming query — assert return value
# ---------------------------------------------------------------------------


async def test_get_user_display_name_returns_name(confluence):
    mock = AsyncMock(return_value={"displayName": "Jane Doe"})

    with patch.object(confluence, "get", mock):
        result = await confluence.get_user_display_name("user-123")

    assert result == "Jane Doe"
    mock.assert_called_once_with("/user", params={"accountId": "user-123"})


async def test_get_user_display_name_returns_account_id_on_error(confluence):
    mock = AsyncMock(side_effect=ConnectorError(404, "Not found"))

    with patch.object(confluence, "get", mock):
        result = await confluence.get_user_display_name("user-123")

    assert result == "user-123"
