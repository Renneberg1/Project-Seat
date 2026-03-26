"""Tests for the ContextRequestResolver service."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.context_resolver import ContextRequestResolver


class TestContextRequestResolver:
    @pytest.fixture()
    def resolver(self):
        return ContextRequestResolver()

    async def test_empty_requests_returns_empty(self, resolver):
        result = await resolver.resolve([])
        assert result == []

    async def test_caps_at_max_requests(self, resolver):
        """Only the first 5 requests are resolved."""
        requests = [
            {"type": "jira_issue", "query": f"RISK-{i}", "reason": "test"}
            for i in range(10)
        ]
        with patch.object(resolver, "_resolve_one", new_callable=AsyncMock) as mock:
            mock.return_value = {"type": "jira_issue", "query": "X", "result": "ok"}
            await resolver.resolve(requests)
            assert mock.call_count == 5

    async def test_jira_issue_returns_formatted_text(self, resolver):
        mock_issue = {
            "key": "RISK-200",
            "fields": {
                "summary": "Data labelling inconsistency",
                "status": {"name": "Open"},
                "issuetype": {"name": "Risk"},
                "priority": {"name": "High"},
                "components": [{"name": "CTC Model"}],
                "labels": ["drop4"],
                "description": {"type": "doc", "content": [
                    {"type": "paragraph", "content": [
                        {"type": "text", "text": "The labelling pipeline has inconsistencies."}
                    ]}
                ]},
            },
        }

        mock_jira = MagicMock()
        mock_jira.get_issue = AsyncMock(return_value=mock_issue)
        mock_jira.close = AsyncMock()

        with patch("src.connectors.jira.JiraConnector", return_value=mock_jira):
            result = await resolver.resolve([
                {"type": "jira_issue", "query": "RISK-200", "reason": "Need details"},
            ])

        assert len(result) == 1
        assert result[0]["type"] == "jira_issue"
        assert result[0]["query"] == "RISK-200"
        assert "Data labelling inconsistency" in result[0]["result"]
        assert "CTC Model" in result[0]["result"]
        assert "labelling pipeline" in result[0]["result"]

    async def test_jira_search_returns_results(self, resolver):
        mock_results = [
            {
                "key": "AIM-50",
                "fields": {
                    "summary": "Model retraining pipeline",
                    "status": {"name": "In Progress"},
                    "issuetype": {"name": "Epic"},
                },
            },
        ]

        mock_jira = MagicMock()
        mock_jira.search = AsyncMock(return_value=mock_results)
        mock_jira.close = AsyncMock()

        with patch("src.connectors.jira.JiraConnector", return_value=mock_jira):
            result = await resolver.resolve([
                {"type": "jira_search", "query": "model retraining", "reason": "Find related work"},
            ])

        assert len(result) == 1
        assert "AIM-50" in result[0]["result"]
        assert "Model retraining pipeline" in result[0]["result"]

    async def test_confluence_search_returns_results(self, resolver):
        mock_results = [
            {
                "id": "12345",
                "title": "Performance Testing Protocol",
                "excerpt": "This document describes the performance testing approach...",
            },
        ]

        mock_conf = MagicMock()
        mock_conf.search_pages_by_title = AsyncMock(return_value=mock_results)
        mock_conf.close = AsyncMock()

        with patch("src.connectors.confluence.ConfluenceConnector", return_value=mock_conf):
            result = await resolver.resolve([
                {"type": "confluence_search", "query": "performance testing", "reason": "Referenced in meeting"},
            ])

        assert len(result) == 1
        assert "Performance Testing Protocol" in result[0]["result"]

    async def test_unknown_type_skipped(self, resolver):
        result = await resolver.resolve([
            {"type": "unknown_thing", "query": "test", "reason": "test"},
        ])
        assert result == []

    async def test_empty_query_skipped(self, resolver):
        result = await resolver.resolve([
            {"type": "jira_issue", "query": "", "reason": "test"},
        ])
        assert result == []

    async def test_connector_error_returns_failure_message(self, resolver):
        from src.connectors.base import ConnectorError

        mock_jira = MagicMock()
        mock_jira.get_issue = AsyncMock(
            side_effect=ConnectorError(404, "Not Found")
        )
        mock_jira.close = AsyncMock()

        with patch("src.connectors.jira.JiraConnector", return_value=mock_jira):
            result = await resolver.resolve([
                {"type": "jira_issue", "query": "FAKE-999", "reason": "test"},
            ])

        assert len(result) == 1
        assert "not found" in result[0]["result"].lower() or "failed" in result[0]["result"].lower()

    async def test_parallel_resolution(self, resolver):
        """Multiple requests are resolved in parallel."""
        requests = [
            {"type": "jira_issue", "query": "RISK-1", "reason": "test"},
            {"type": "jira_search", "query": "model", "reason": "test"},
            {"type": "confluence_search", "query": "protocol", "reason": "test"},
        ]

        with patch.object(resolver, "_resolve_one", new_callable=AsyncMock) as mock:
            mock.return_value = {"type": "test", "query": "test", "result": "ok"}
            result = await resolver.resolve(requests)

        assert mock.call_count == 3
        assert len(result) == 3

    def test_extract_adf_text(self):
        adf = {
            "type": "doc",
            "content": [
                {"type": "paragraph", "content": [
                    {"type": "text", "text": "Hello "},
                    {"type": "text", "text": "world"},
                ]},
                {"type": "paragraph", "content": [
                    {"type": "text", "text": "Second paragraph"},
                ]},
            ],
        }
        result = ContextRequestResolver._extract_adf_text(adf)
        assert "Hello" in result
        assert "world" in result
        assert "Second paragraph" in result

    async def test_result_truncated_to_max_chars(self, resolver):
        """Results exceeding _MAX_RESULT_CHARS are truncated."""
        long_text = "A" * 5000

        mock_jira = MagicMock()
        mock_jira.get_issue = AsyncMock(return_value={
            "key": "TEST-1",
            "fields": {
                "summary": long_text,
                "status": {"name": "Open"},
                "issuetype": {"name": "Task"},
                "priority": {"name": "Medium"},
                "components": [],
                "labels": [],
                "description": None,
            },
        })
        mock_jira.close = AsyncMock()

        with patch("src.connectors.jira.JiraConnector", return_value=mock_jira):
            result = await resolver.resolve([
                {"type": "jira_issue", "query": "TEST-1", "reason": "test"},
            ])

        assert len(result[0]["result"]) <= 3000
