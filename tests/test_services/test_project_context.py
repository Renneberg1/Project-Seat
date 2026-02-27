"""Tests for ProjectContextService — parallel fetch logic and per-source error isolation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.project import Project
from src.services.project_context import ProjectContextService, ProjectContextData


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def project():
    return Project(
        id=1,
        jira_goal_key="PROG-100",
        name="Test Project",
        confluence_charter_id="111",
        confluence_xft_id="222",
        status="active",
        phase="development",
        created_at="2026-01-01T00:00:00",
        team_projects=[["AIM", "Drop 1"]],
    )


@pytest.fixture
def service():
    settings = MagicMock()
    settings.db_path = ":memory:"
    return ProjectContextService(db_path=":memory:", settings=settings)


# ---------------------------------------------------------------------------
# Basic gather tests
# ---------------------------------------------------------------------------


class TestGatherBasic:
    """Test that gather returns correct defaults when no flags are set."""

    @pytest.mark.asyncio
    async def test_no_flags_returns_empty_context(self, service, project):
        data = await service.gather(project)
        assert isinstance(data, ProjectContextData)
        assert data.project is project
        assert data.existing_risks == []
        assert data.existing_decisions == []
        assert data.charter_content is None
        assert data.xft_content is None
        assert data.summary is None
        assert data.initiatives == []
        assert data.team_reports == []
        assert data.snapshots == []
        assert data.dhf_docs == []
        assert data.releases == []
        assert data.meeting_summaries == []


# ---------------------------------------------------------------------------
# Individual source tests
# ---------------------------------------------------------------------------


class TestGatherSources:
    """Test that each source flag fetches the correct data."""

    @pytest.mark.asyncio
    async def test_risks_fetched(self, service, project):
        mock_risks = [{"key": "RISK-1", "summary": "Test", "status": "Open"}]
        with patch.object(service, "_fetch_risk_summaries", new_callable=AsyncMock, return_value=mock_risks):
            data = await service.gather(project, risks=True)
        assert data.existing_risks == mock_risks

    @pytest.mark.asyncio
    async def test_decisions_fetched(self, service, project):
        mock_decisions = [{"key": "RISK-2", "summary": "Decision", "status": "Decided"}]
        with patch.object(service, "_fetch_decision_summaries", new_callable=AsyncMock, return_value=mock_decisions):
            data = await service.gather(project, decisions=True)
        assert data.existing_decisions == mock_decisions

    @pytest.mark.asyncio
    async def test_charter_fetched(self, service, project):
        with patch.object(service, "_fetch_page_body", new_callable=AsyncMock, return_value="<h1>Charter</h1>"):
            data = await service.gather(project, charter=True)
        assert data.charter_content == "<h1>Charter</h1>"

    @pytest.mark.asyncio
    async def test_xft_fetched(self, service, project):
        with patch.object(service, "_fetch_page_body", new_callable=AsyncMock, return_value="<h1>XFT</h1>"):
            data = await service.gather(project, xft=True)
        assert data.xft_content == "<h1>XFT</h1>"

    @pytest.mark.asyncio
    async def test_summary_fetched(self, service, project):
        mock_summary = MagicMock()
        with patch.object(service, "_fetch_summary", new_callable=AsyncMock, return_value=mock_summary):
            data = await service.gather(project, summary=True)
        assert data.summary is mock_summary

    @pytest.mark.asyncio
    async def test_team_reports_fetched(self, service, project):
        mock_reports = [MagicMock()]
        with patch.object(service, "_fetch_team_reports", new_callable=AsyncMock, return_value=mock_reports):
            data = await service.gather(project, team_reports=True)
        assert data.team_reports == mock_reports

    @pytest.mark.asyncio
    async def test_snapshots_fetched(self, service, project):
        mock_snaps = [{"date": "2026-02-20", "sp_total": 100, "sp_done": 50}]
        with patch.object(service, "_fetch_snapshots", new_callable=AsyncMock, return_value=mock_snaps):
            data = await service.gather(project, snapshots=True)
        assert data.snapshots == mock_snaps

    @pytest.mark.asyncio
    async def test_releases_fetched(self, service, project):
        mock_releases = [{"name": "v1.0", "locked": True}]
        with patch.object(service, "_fetch_releases", new_callable=AsyncMock, return_value=mock_releases):
            data = await service.gather(project, releases=True)
        assert data.releases == mock_releases

    @pytest.mark.asyncio
    async def test_meeting_summaries_fetched(self, service, project):
        mock_meetings = [{"summary": "Sprint review"}]
        with patch.object(service, "_fetch_meeting_summaries", new_callable=AsyncMock, return_value=mock_meetings):
            data = await service.gather(project, meeting_summaries=True)
        assert data.meeting_summaries == mock_meetings


# ---------------------------------------------------------------------------
# Parallel execution and error isolation
# ---------------------------------------------------------------------------


class TestErrorIsolation:
    """Test that one failing source doesn't block others."""

    @pytest.mark.asyncio
    async def test_risk_failure_does_not_block_charter(self, service, project):
        """When risks return empty (connector error caught internally), charter still works."""
        with patch.object(
            service, "_fetch_risk_summaries",
            new_callable=AsyncMock, return_value=[],  # simulates caught connector error
        ), patch.object(
            service, "_fetch_page_body",
            new_callable=AsyncMock, return_value="<h1>Charter</h1>",
        ):
            data = await service.gather(project, risks=True, charter=True)
        assert data.existing_risks == []
        assert data.charter_content == "<h1>Charter</h1>"

    @pytest.mark.asyncio
    async def test_multiple_sources_fetched_in_parallel(self, service, project):
        """Verify multiple flags trigger parallel fetches and all results are assigned."""
        with patch.object(
            service, "_fetch_risk_summaries",
            new_callable=AsyncMock, return_value=[{"key": "R-1", "summary": "r", "status": "Open"}],
        ), patch.object(
            service, "_fetch_decision_summaries",
            new_callable=AsyncMock, return_value=[{"key": "D-1", "summary": "d", "status": "Decided"}],
        ), patch.object(
            service, "_fetch_page_body",
            new_callable=AsyncMock, return_value="<body/>",
        ), patch.object(
            service, "_fetch_summary",
            new_callable=AsyncMock, return_value=MagicMock(),
        ):
            data = await service.gather(
                project, risks=True, decisions=True, charter=True, summary=True,
            )
        assert len(data.existing_risks) == 1
        assert len(data.existing_decisions) == 1
        assert data.charter_content == "<body/>"
        assert data.summary is not None


# ---------------------------------------------------------------------------
# Internal fetch methods — error handling
# ---------------------------------------------------------------------------


class TestFetchMethods:
    """Test that individual _fetch_* methods catch errors and return defaults."""

    @pytest.mark.asyncio
    async def test_fetch_risk_summaries_returns_empty_on_error(self, service, project):
        mock_jira = MagicMock()
        mock_jira.search = AsyncMock(side_effect=RuntimeError("fail"))
        mock_jira.close = AsyncMock()
        with patch("src.connectors.jira.JiraConnector", return_value=mock_jira):
            result = await service._fetch_risk_summaries(project)
        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_decision_summaries_returns_empty_on_error(self, service, project):
        mock_jira = MagicMock()
        mock_jira.search = AsyncMock(side_effect=RuntimeError("fail"))
        mock_jira.close = AsyncMock()
        with patch("src.connectors.jira.JiraConnector", return_value=mock_jira):
            result = await service._fetch_decision_summaries(project)
        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_page_body_returns_none_when_no_id(self, service):
        result = await service._fetch_page_body(None)
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_page_body_returns_none_on_error(self, service):
        mock_conf = MagicMock()
        mock_conf.get_page = AsyncMock(side_effect=RuntimeError("fail"))
        mock_conf.close = AsyncMock()
        with patch("src.connectors.confluence.ConfluenceConnector", return_value=mock_conf):
            result = await service._fetch_page_body("12345")
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_goal_metadata_returns_empty_on_error(self, service, project):
        mock_jira = MagicMock()
        mock_jira.get_issue = AsyncMock(side_effect=RuntimeError("fail"))
        mock_jira.close = AsyncMock()
        with patch("src.connectors.jira.JiraConnector", return_value=mock_jira):
            result = await service._fetch_goal_metadata(project)
        assert result == ([], [])


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------


class TestCaching:
    """Test cache_key and cache_ttl behaviour."""

    @pytest.mark.asyncio
    async def test_cached_result_returned(self, service, project):
        """When cache has data, no fetches should happen."""
        cached_data = ProjectContextData(project=project)
        cached_data.existing_risks = [{"key": "RISK-99", "summary": "cached", "status": "Open"}]

        with patch("src.services.project_context.cache") as mock_cache:
            mock_cache.get.return_value = cached_data
            data = await service.gather(
                project, risks=True, cache_key="test:ctx", cache_ttl=600,
            )
        assert data.existing_risks[0]["key"] == "RISK-99"
        mock_cache.set.assert_not_called()  # didn't re-fetch and re-cache

    @pytest.mark.asyncio
    async def test_cache_miss_stores_result(self, service, project):
        """On cache miss, result should be stored."""
        with patch("src.services.project_context.cache") as mock_cache, \
             patch.object(service, "_fetch_risk_summaries", new_callable=AsyncMock, return_value=[]):
            mock_cache.get.return_value = None
            await service.gather(
                project, risks=True, cache_key="test:ctx", cache_ttl=600,
            )
        mock_cache.set.assert_called_once()
        args = mock_cache.set.call_args
        assert args[0][0] == "test:ctx"
        assert args[0][2] == 600
