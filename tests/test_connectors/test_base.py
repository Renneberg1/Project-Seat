"""Tests for the base connector — retry, rate-limit, and pagination logic."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.connectors.base import BaseConnector, ConnectorError
from tests.conftest import make_response


@pytest.fixture()
def connector(test_settings) -> BaseConnector:
    return BaseConnector("https://fake.atlassian.net/rest/api/3", settings=test_settings)


class TestRequest:
    async def test_success_on_first_try(self, connector: BaseConnector) -> None:
        mock_resp = make_response(200, {"ok": True})
        with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=mock_resp):
            resp = await connector._request("GET", "/test")
        assert resp.status_code == 200

    async def test_retry_on_500_then_success(self, connector: BaseConnector) -> None:
        fail = make_response(500, {"error": "server"})
        ok = make_response(200, {"ok": True})
        mock = AsyncMock(side_effect=[fail, fail, ok])
        with patch.object(httpx.AsyncClient, "request", mock), \
             patch("src.connectors.base.asyncio.sleep", new_callable=AsyncMock):
            resp = await connector._request("GET", "/test")
        assert resp.status_code == 200
        assert mock.call_count == 3

    async def test_exhaust_retries_on_500(self, connector: BaseConnector) -> None:
        fail = make_response(500, {"error": "server"})
        mock = AsyncMock(return_value=fail)
        with patch.object(httpx.AsyncClient, "request", mock), \
             patch("src.connectors.base.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(ConnectorError):
                await connector._request("GET", "/test")
        assert mock.call_count == 3

    async def test_429_with_retry_after_header(self, connector: BaseConnector) -> None:
        rate_limit = make_response(429, {}, headers={"Retry-After": "2"})
        ok = make_response(200, {"ok": True})
        mock = AsyncMock(side_effect=[rate_limit, ok])
        sleep_mock = AsyncMock()
        with patch.object(httpx.AsyncClient, "request", mock), \
             patch("src.connectors.base.asyncio.sleep", sleep_mock):
            resp = await connector._request("GET", "/test")
        assert resp.status_code == 200
        sleep_mock.assert_any_call(2.0)

    async def test_429_without_retry_after_uses_backoff(self, connector: BaseConnector) -> None:
        rate_limit = make_response(429, {})
        ok = make_response(200, {"ok": True})
        mock = AsyncMock(side_effect=[rate_limit, ok])
        sleep_mock = AsyncMock()
        with patch.object(httpx.AsyncClient, "request", mock), \
             patch("src.connectors.base.asyncio.sleep", sleep_mock):
            resp = await connector._request("GET", "/test")
        assert resp.status_code == 200
        # First attempt (attempt=0): backoff = 1.0 * 2^0 = 1.0
        sleep_mock.assert_any_call(1.0)

    async def test_client_error_400_no_retry(self, connector: BaseConnector) -> None:
        bad_req = make_response(400, {"error": "bad request"})
        mock = AsyncMock(return_value=bad_req)
        with patch.object(httpx.AsyncClient, "request", mock):
            with pytest.raises(ConnectorError) as exc_info:
                await connector._request("GET", "/test")
        assert exc_info.value.status_code == 400
        assert mock.call_count == 1

    async def test_transport_error_retries_then_success(self, connector: BaseConnector) -> None:
        ok = make_response(200, {"ok": True})
        mock = AsyncMock(side_effect=[httpx.ConnectError("conn refused"), ok])
        with patch.object(httpx.AsyncClient, "request", mock), \
             patch("src.connectors.base.asyncio.sleep", new_callable=AsyncMock):
            resp = await connector._request("GET", "/test")
        assert resp.status_code == 200

    async def test_transport_error_exhausted(self, connector: BaseConnector) -> None:
        mock = AsyncMock(side_effect=httpx.ConnectError("conn refused"))
        with patch.object(httpx.AsyncClient, "request", mock), \
             patch("src.connectors.base.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(ConnectorError) as exc_info:
                await connector._request("GET", "/test")
        assert exc_info.value.status_code == 0


class TestPaginationJira:
    async def test_single_page(self, connector: BaseConnector) -> None:
        data = {"issues": [{"id": "1"}, {"id": "2"}]}
        with patch.object(connector, "post", new_callable=AsyncMock, return_value=data):
            results = await connector.post_all_jira("/search/jql")
        assert len(results) == 2

    async def test_multiple_pages(self, connector: BaseConnector) -> None:
        page1 = {"issues": [{"id": "1"}, {"id": "2"}], "nextPageToken": "token123"}
        page2 = {"issues": [{"id": "3"}]}
        mock = AsyncMock(side_effect=[page1, page2])
        with patch.object(connector, "post", mock):
            results = await connector.post_all_jira("/search/jql", page_size=2)
        assert len(results) == 3
        assert mock.call_count == 2


class TestPaginationConfluence:
    async def test_follows_next_link(self, connector: BaseConnector) -> None:
        page1 = {"results": [{"id": "1"}], "_links": {"next": "/more"}}
        page2 = {"results": [{"id": "2"}], "_links": {}}
        mock = AsyncMock(side_effect=[page1, page2])
        with patch.object(connector, "get", mock):
            results = await connector.get_all_confluence("/content")
        assert len(results) == 2

    async def test_stops_without_next(self, connector: BaseConnector) -> None:
        page1 = {"results": [{"id": "1"}], "_links": {}}
        mock = AsyncMock(return_value=page1)
        with patch.object(connector, "get", mock):
            results = await connector.get_all_confluence("/content")
        assert len(results) == 1
        assert mock.call_count == 1
