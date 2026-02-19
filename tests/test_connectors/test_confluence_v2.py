"""Tests for Confluence v2 API methods."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.connectors.confluence import ConfluenceConnector


@pytest.fixture()
def confluence(test_settings) -> ConfluenceConnector:
    return ConfluenceConnector(settings=test_settings)


class TestV2Url:
    def test_builds_correct_url(self, confluence: ConfluenceConnector) -> None:
        url = confluence._v2_url("/pages/12345/children")
        assert url == "https://test-company.atlassian.net/wiki/api/v2/pages/12345/children"

    def test_root_path(self, confluence: ConfluenceConnector) -> None:
        url = confluence._v2_url("/pages")
        assert url == "https://test-company.atlassian.net/wiki/api/v2/pages"


class TestGetChildPagesV2:
    async def test_calls_v2_get_all(self, confluence: ConfluenceConnector) -> None:
        mock = AsyncMock(return_value=[{"id": "1", "title": "Child 1"}])
        with patch.object(confluence, "_v2_get_all", mock):
            result = await confluence.get_child_pages_v2("12345")
        mock.assert_called_once_with("/pages/12345/children")
        assert len(result) == 1

    async def test_cursor_pagination(self, confluence: ConfluenceConnector) -> None:
        """Test that _v2_get_all follows cursor links."""
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


class TestGetPageV2:
    async def test_calls_v2_url(self, confluence: ConfluenceConnector) -> None:
        sample = {"id": "123", "title": "Test", "_links": {"webui": "/wiki/page/123"}}
        mock = AsyncMock(return_value=sample)
        with patch.object(confluence, "get", mock):
            result = await confluence.get_page_v2("123")
        expected_url = "https://test-company.atlassian.net/wiki/api/v2/pages/123"
        mock.assert_called_once_with(expected_url)
        assert result["_links"]["webui"] == "/wiki/page/123"


class TestGetPageVersions:
    async def test_returns_results(self, confluence: ConfluenceConnector) -> None:
        data = {"results": [{"number": 3}, {"number": 2}]}
        mock = AsyncMock(return_value=data)
        with patch.object(confluence, "get", mock):
            result = await confluence.get_page_versions("123", limit=5)
        assert len(result) == 2
        call_args = mock.call_args
        assert call_args[1]["params"]["limit"] == 5


class TestGetContentProperty:
    async def test_returns_property(self, confluence: ConfluenceConnector) -> None:
        sample = {"key": "sc-dm-document-metadata", "value": {"documentId": "abc"}}
        mock = AsyncMock(return_value=sample)
        with patch.object(confluence, "get", mock):
            result = await confluence.get_content_property("123", "sc-dm-document-metadata")
        assert result["value"]["documentId"] == "abc"
        mock.assert_called_once_with("/content/123/property/sc-dm-document-metadata")

    async def test_returns_none_on_404(self, confluence: ConfluenceConnector) -> None:
        from src.connectors.base import ConnectorError

        mock = AsyncMock(side_effect=ConnectorError(404, "Not found"))
        with patch.object(confluence, "get", mock):
            result = await confluence.get_content_property("123", "missing-key")
        assert result is None

    async def test_raises_on_other_errors(self, confluence: ConfluenceConnector) -> None:
        from src.connectors.base import ConnectorError

        mock = AsyncMock(side_effect=ConnectorError(500, "Server error"))
        with patch.object(confluence, "get", mock):
            with pytest.raises(ConnectorError):
                await confluence.get_content_property("123", "some-key")


class TestGetUserDisplayName:
    async def test_returns_name(self, confluence: ConfluenceConnector) -> None:
        mock = AsyncMock(return_value={"displayName": "Jane Doe"})
        with patch.object(confluence, "get", mock):
            name = await confluence.get_user_display_name("user-123")
        assert name == "Jane Doe"
        mock.assert_called_once_with("/user", params={"accountId": "user-123"})

    async def test_returns_id_on_error(self, confluence: ConfluenceConnector) -> None:
        from src.connectors.base import ConnectorError

        mock = AsyncMock(side_effect=ConnectorError(404, "Not found"))
        with patch.object(confluence, "get", mock):
            name = await confluence.get_user_display_name("user-123")
        assert name == "user-123"
