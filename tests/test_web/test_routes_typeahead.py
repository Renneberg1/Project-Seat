"""Tests for typeahead search routes — contract tests with mocked connectors."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch


# ---------------------------------------------------------------------------
# GET /api/typeahead/confluence-pages
# ---------------------------------------------------------------------------


def test_confluence_pages_min_length_returns_empty(client):
    """Query shorter than 2 chars returns empty results (no API call)."""
    result = client.get("/api/typeahead/confluence-pages?q=a")
    assert result.status_code == 200
    assert "ta-result" not in result.text  # no selectable results


def test_confluence_pages_returns_results(client):
    """Valid query returns matching page results."""
    mock_pages = [
        {"id": "123456", "title": "Project Charter", "_expandable": {"space": "/rest/api/space/HPP"}},
        {"id": "789012", "title": "Charter Template", "_expandable": {"space": "/rest/api/space/HPP"}},
    ]
    with patch("src.web.deps.ConfluenceConnector") as MockConn:
        instance = MockConn.return_value
        instance.search_pages_by_title = AsyncMock(return_value=mock_pages)
        instance.close = AsyncMock()

        result = client.get("/api/typeahead/confluence-pages?q=charter")

    assert result.status_code == 200
    assert "123456" in result.text
    assert "Project Charter" in result.text
    assert "Charter Template" in result.text


def test_confluence_pages_with_space_filter(client):
    """Space parameter is passed through to connector."""
    with patch("src.web.deps.ConfluenceConnector") as MockConn:
        instance = MockConn.return_value
        instance.search_pages_by_title = AsyncMock(return_value=[])
        instance.close = AsyncMock()

        result = client.get("/api/typeahead/confluence-pages?q=charter&space=HPP")

    assert result.status_code == 200
    instance.search_pages_by_title.assert_called_once_with("charter", space_key="HPP")


def test_confluence_pages_empty_results(client):
    """No matching pages returns 'No results' message."""
    with patch("src.web.deps.ConfluenceConnector") as MockConn:
        instance = MockConn.return_value
        instance.search_pages_by_title = AsyncMock(return_value=[])
        instance.close = AsyncMock()

        result = client.get("/api/typeahead/confluence-pages?q=nonexistent")

    assert result.status_code == 200
    assert "No results" in result.text


# ---------------------------------------------------------------------------
# GET /api/typeahead/jira-issues
# ---------------------------------------------------------------------------


def test_jira_issues_min_length_returns_empty(client):
    """Query shorter than 2 chars returns empty results."""
    result = client.get("/api/typeahead/jira-issues?q=P")
    assert result.status_code == 200
    assert "ta-result" not in result.text


def test_jira_issues_returns_results(client):
    """Valid query returns matching issue results."""
    mock_issues = [
        {"key": "PROG-256", "fields": {"summary": "HOP Drop 2"}},
        {"key": "PROG-300", "fields": {"summary": "HOP Drop 3"}},
    ]
    with patch("src.web.deps.JiraConnector") as MockConn:
        instance = MockConn.return_value
        instance.search = AsyncMock(return_value=mock_issues)
        instance.close = AsyncMock()

        result = client.get("/api/typeahead/jira-issues?q=HOP")

    assert result.status_code == 200
    assert "PROG-256" in result.text
    assert "HOP Drop 2" in result.text


def test_jira_issues_key_pattern_uses_key_jql(client):
    """Query matching issue key pattern uses key-based JQL."""
    with patch("src.web.deps.JiraConnector") as MockConn:
        instance = MockConn.return_value
        instance.search = AsyncMock(return_value=[
            {"key": "PROG-256", "fields": {"summary": "HOP Drop 2"}},
        ])
        instance.close = AsyncMock()

        result = client.get("/api/typeahead/jira-issues?q=PROG-256")

    assert result.status_code == 200
    # Verify key-based JQL was used
    call_args = instance.search.call_args
    jql = call_args[0][0] if call_args[0] else call_args[1].get("jql", "")
    assert "key" in jql.lower()


def test_jira_issues_with_project_filter(client):
    """Project parameter restricts JQL search."""
    with patch("src.web.deps.JiraConnector") as MockConn:
        instance = MockConn.return_value
        instance.search = AsyncMock(return_value=[])
        instance.close = AsyncMock()

        result = client.get("/api/typeahead/jira-issues?q=drop&project=PROG")

    assert result.status_code == 200
    call_args = instance.search.call_args
    jql = call_args[0][0] if call_args[0] else call_args[1].get("jql", "")
    assert "PROG" in jql


# ---------------------------------------------------------------------------
# GET /api/typeahead/jira-projects
# ---------------------------------------------------------------------------


def test_jira_projects_returns_results(client):
    """Returns matching project results."""
    mock_projects = [
        {"key": "AIM", "name": "AIM Team"},
        {"key": "CTCV", "name": "CTCV Team"},
    ]
    with patch("src.web.deps.JiraConnector") as MockConn:
        instance = MockConn.return_value
        instance.list_projects = AsyncMock(return_value=mock_projects)
        instance.close = AsyncMock()

        result = client.get("/api/typeahead/jira-projects?q=AIM")

    assert result.status_code == 200
    assert "AIM" in result.text
    assert "AIM Team" in result.text


def test_jira_projects_no_query_returns_all(client):
    """No query parameter returns all projects."""
    mock_projects = [{"key": "PROG", "name": "Program"}]
    with patch("src.web.deps.JiraConnector") as MockConn:
        instance = MockConn.return_value
        instance.list_projects = AsyncMock(return_value=mock_projects)
        instance.close = AsyncMock()

        result = client.get("/api/typeahead/jira-projects")

    assert result.status_code == 200
    assert "PROG" in result.text


# ---------------------------------------------------------------------------
# GET /api/typeahead/jira-versions
# ---------------------------------------------------------------------------


def test_jira_versions_no_project_returns_empty(client):
    """Missing project parameter returns empty results."""
    result = client.get("/api/typeahead/jira-versions")
    assert result.status_code == 200
    assert "ta-result" not in result.text


def test_jira_versions_returns_results(client):
    """Valid project returns version results."""
    mock_versions = [
        {"name": "HOP Drop 2", "released": False},
        {"name": "HOP Drop 1", "released": True},
    ]
    with patch("src.web.deps.JiraConnector") as MockConn:
        instance = MockConn.return_value
        instance.get_versions = AsyncMock(return_value=mock_versions)
        instance.close = AsyncMock()

        result = client.get("/api/typeahead/jira-versions?project=AIM")

    assert result.status_code == 200
    assert "HOP Drop 2" in result.text
    assert "unreleased" in result.text
    assert "released" in result.text
