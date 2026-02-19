"""Tests for the base connector — retry, rate-limit, and pagination contracts."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.connectors.base import BaseConnector, ConnectorError


@pytest.fixture()
def connector(test_settings) -> BaseConnector:
    return BaseConnector("https://fake.atlassian.net/rest/api/3", settings=test_settings)


# ---------------------------------------------------------------------------
# _request: Contract tests (happy path)
# ---------------------------------------------------------------------------


async def test_request_success_on_first_try_returns_response(connector, make_response):
    mock_resp = make_response(200, {"ok": True})
    with patch.object(httpx.AsyncClient, "request", new_callable=AsyncMock, return_value=mock_resp):
        result = await connector._request("GET", "/test")

    assert result.status_code == 200


async def test_request_retry_on_500_then_success_returns_ok(connector, make_response):
    fail = make_response(500, {"error": "server"})
    ok = make_response(200, {"ok": True})
    mock = AsyncMock(side_effect=[fail, fail, ok])

    with patch.object(httpx.AsyncClient, "request", mock), \
         patch("src.connectors.base.asyncio.sleep", new_callable=AsyncMock):
        result = await connector._request("GET", "/test")

    assert result.status_code == 200
    assert mock.call_count == 3


async def test_request_429_with_retry_after_header_sleeps_correct_duration(connector, make_response):
    rate_limit = make_response(429, {}, headers={"Retry-After": "2"})
    ok = make_response(200, {"ok": True})
    mock = AsyncMock(side_effect=[rate_limit, ok])
    sleep_mock = AsyncMock()

    with patch.object(httpx.AsyncClient, "request", mock), \
         patch("src.connectors.base.asyncio.sleep", sleep_mock):
        result = await connector._request("GET", "/test")

    assert result.status_code == 200
    sleep_mock.assert_any_call(2.0)


async def test_request_429_without_retry_after_uses_backoff(connector, make_response):
    rate_limit = make_response(429, {})
    ok = make_response(200, {"ok": True})
    mock = AsyncMock(side_effect=[rate_limit, ok])
    sleep_mock = AsyncMock()

    with patch.object(httpx.AsyncClient, "request", mock), \
         patch("src.connectors.base.asyncio.sleep", sleep_mock):
        result = await connector._request("GET", "/test")

    assert result.status_code == 200
    sleep_mock.assert_any_call(1.0)


async def test_request_transport_error_retries_then_succeeds(connector, make_response):
    ok = make_response(200, {"ok": True})
    mock = AsyncMock(side_effect=[httpx.ConnectError("conn refused"), ok])

    with patch.object(httpx.AsyncClient, "request", mock), \
         patch("src.connectors.base.asyncio.sleep", new_callable=AsyncMock):
        result = await connector._request("GET", "/test")

    assert result.status_code == 200


# ---------------------------------------------------------------------------
# _request: Precondition violations and error cases
# ---------------------------------------------------------------------------


async def test_request_exhaust_retries_on_500_raises_connector_error(connector, make_response):
    fail = make_response(500, {"error": "server"})
    mock = AsyncMock(return_value=fail)

    with patch.object(httpx.AsyncClient, "request", mock), \
         patch("src.connectors.base.asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(ConnectorError):
            await connector._request("GET", "/test")

    assert mock.call_count == 3


async def test_request_client_error_400_fails_immediately_no_retry(connector, make_response):
    bad_req = make_response(400, {"error": "bad request"})
    mock = AsyncMock(return_value=bad_req)

    with patch.object(httpx.AsyncClient, "request", mock):
        with pytest.raises(ConnectorError, match="400") as exc_info:
            await connector._request("GET", "/test")

    assert exc_info.value.status_code == 400
    assert mock.call_count == 1


async def test_request_transport_error_exhausted_raises_with_status_zero(connector, make_response):
    mock = AsyncMock(side_effect=httpx.ConnectError("conn refused"))

    with patch.object(httpx.AsyncClient, "request", mock), \
         patch("src.connectors.base.asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(ConnectorError) as exc_info:
            await connector._request("GET", "/test")

    assert exc_info.value.status_code == 0


# ---------------------------------------------------------------------------
# post_all_jira pagination: Contract tests
# ---------------------------------------------------------------------------


async def test_post_all_jira_single_page_returns_all_issues(connector):
    data = {"issues": [{"id": "1"}, {"id": "2"}]}
    with patch.object(connector, "post", new_callable=AsyncMock, return_value=data):
        result = await connector.post_all_jira("/search/jql")

    assert len(result) == 2


async def test_post_all_jira_multiple_pages_follows_next_page_token(connector):
    page1 = {"issues": [{"id": "1"}, {"id": "2"}], "nextPageToken": "token123"}
    page2 = {"issues": [{"id": "3"}]}
    mock = AsyncMock(side_effect=[page1, page2])

    with patch.object(connector, "post", mock):
        result = await connector.post_all_jira("/search/jql", page_size=2)

    assert len(result) == 3
    assert mock.call_count == 2


# ---------------------------------------------------------------------------
# get_all_confluence pagination: Contract tests
# ---------------------------------------------------------------------------


async def test_get_all_confluence_follows_next_link(connector):
    page1 = {"results": [{"id": "1"}], "_links": {"next": "/more"}}
    page2 = {"results": [{"id": "2"}], "_links": {}}
    mock = AsyncMock(side_effect=[page1, page2])

    with patch.object(connector, "get", mock):
        result = await connector.get_all_confluence("/content")

    assert len(result) == 2


async def test_get_all_confluence_stops_without_next_link(connector):
    page1 = {"results": [{"id": "1"}], "_links": {}}
    mock = AsyncMock(return_value=page1)

    with patch.object(connector, "get", mock):
        result = await connector.get_all_confluence("/content")

    assert len(result) == 1
    assert mock.call_count == 1
