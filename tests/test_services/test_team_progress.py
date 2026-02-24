"""Tests for TeamProgressService — per-team fix version progress tracking."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.cache import cache
from src.connectors.base import ConnectorError
from src.models.project import Project
from src.services.team_progress import (
    TeamProgressService,
    TeamVersionReport,
    _aggregate,
    _get_story_points,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project(**overrides) -> Project:
    defaults = dict(
        id=1, jira_goal_key="PROG-100", name="HOP Drop 2",
        confluence_charter_id=None, confluence_xft_id=None,
        status="active", phase="planning", created_at="2026-01-01",
        team_projects=[["AIM", "HOP Drop 2"], ["CTCV", "HOP Drop 2"]],
    )
    defaults.update(overrides)
    return Project(**defaults)


def _make_issue(
    project_key: str = "AIM",
    status_category: str = "Done",
    status_name: str = "Done",
    priority: str = "Medium",
    sp_next_gen: float | None = None,
    sp_classic: float | None = None,
    fix_versions: list[str] | None = None,
) -> dict:
    fv = [{"name": v} for v in (fix_versions or [])]
    return {
        "key": f"{project_key}-1",
        "fields": {
            "project": {"key": project_key},
            "status": {
                "name": status_name,
                "statusCategory": {"name": status_category},
            },
            "issuetype": {"name": "Task"},
            "priority": {"name": priority},
            "customfield_10016": sp_next_gen,
            "customfield_10026": sp_classic,
            "fixVersions": fv,
        },
    }


# ---------------------------------------------------------------------------
# _aggregate tests
# ---------------------------------------------------------------------------


class TestAggregate:
    def test_empty_issues(self):
        report = _aggregate("AIM", "v1", [])
        assert report.total_issues == 0
        assert report.done_count == 0
        assert report.pct_done_issues == 0

    def test_groups_by_status_category(self):
        issues = [
            _make_issue(status_category="Done"),
            _make_issue(status_category="Done"),
            _make_issue(status_category="In Progress"),
            _make_issue(status_category="To Do"),
        ]
        report = _aggregate("AIM", "v1", issues)
        assert report.total_issues == 4
        assert report.done_count == 2
        assert report.in_progress_count == 1
        assert report.todo_count == 1
        assert report.pct_done_issues == 50

    def test_custom_status_names_classify_by_category(self):
        """Custom status names (e.g. 'Awaiting Review') still classify correctly."""
        issues = [
            _make_issue(status_category="Done", status_name="Verified"),
            _make_issue(status_category="In Progress", status_name="Awaiting Review"),
            _make_issue(status_category="To Do", status_name="Backlog"),
        ]
        report = _aggregate("AIM", "v1", issues)
        assert report.done_count == 1
        assert report.in_progress_count == 1
        assert report.todo_count == 1

    def test_blocker_count(self):
        issues = [
            _make_issue(priority="Blocker"),
            _make_issue(priority="Blocker"),
            _make_issue(priority="High"),
        ]
        report = _aggregate("AIM", "v1", issues)
        assert report.blocker_count == 2

    def test_story_points_prefers_next_gen_field(self):
        issues = [
            _make_issue(status_category="Done", sp_next_gen=5.0, sp_classic=3.0),
        ]
        report = _aggregate("AIM", "v1", issues)
        assert report.sp_total == 5.0
        assert report.sp_done == 5.0
        assert report.sp_missing_count == 0

    def test_story_points_falls_back_to_classic(self):
        issues = [
            _make_issue(status_category="In Progress", sp_next_gen=None, sp_classic=8.0),
        ]
        report = _aggregate("AIM", "v1", issues)
        assert report.sp_total == 8.0
        assert report.sp_done == 0.0
        assert report.sp_missing_count == 0

    def test_sp_missing_count(self):
        issues = [
            _make_issue(sp_next_gen=None, sp_classic=None),
            _make_issue(sp_next_gen=3.0),
        ]
        report = _aggregate("AIM", "v1", issues)
        assert report.sp_missing_count == 1
        assert report.sp_total == 3.0

    def test_pct_done_sp(self):
        issues = [
            _make_issue(status_category="Done", sp_next_gen=4.0),
            _make_issue(status_category="In Progress", sp_next_gen=6.0),
        ]
        report = _aggregate("AIM", "v1", issues)
        assert report.sp_total == 10.0
        assert report.sp_done == 4.0
        assert report.pct_done_sp == 40


# ---------------------------------------------------------------------------
# _get_story_points tests
# ---------------------------------------------------------------------------


class TestGetStoryPoints:
    def test_next_gen_wins(self):
        assert _get_story_points({"customfield_10016": 5, "customfield_10026": 3}) == 5.0

    def test_classic_fallback(self):
        assert _get_story_points({"customfield_10016": None, "customfield_10026": 8}) == 8.0

    def test_none_when_both_missing(self):
        assert _get_story_points({"customfield_10016": None, "customfield_10026": None}) is None

    def test_none_when_keys_absent(self):
        assert _get_story_points({}) is None


# ---------------------------------------------------------------------------
# TeamProgressService tests
# ---------------------------------------------------------------------------


class TestTeamProgressService:
    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        cache.clear()
        yield
        cache.clear()

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_team_projects(self):
        project = _make_project(team_projects=[])
        service = TeamProgressService()
        result = await service.get_team_reports(project)
        assert result == []

    @pytest.mark.asyncio
    async def test_groups_by_team(self):
        project = _make_project(team_projects=[["AIM", "HOP Drop 2"], ["CTCV", "HOP Drop 2"]])
        mock_issues = [
            _make_issue(project_key="AIM", status_category="Done", sp_next_gen=3, fix_versions=["HOP Drop 2"]),
            _make_issue(project_key="AIM", status_category="In Progress", sp_next_gen=2, fix_versions=["HOP Drop 2"]),
            _make_issue(project_key="CTCV", status_category="To Do", sp_next_gen=5, fix_versions=["HOP Drop 2"]),
        ]

        with patch("src.services.team_progress.JiraConnector") as MockJira:
            instance = MockJira.return_value
            instance.search = AsyncMock(return_value=mock_issues)
            instance.close = AsyncMock()

            service = TeamProgressService()
            reports = await service.get_team_reports(project)

        assert len(reports) == 2
        aim = reports[0]
        assert aim.team_key == "AIM"
        assert aim.total_issues == 2
        assert aim.done_count == 1
        assert aim.in_progress_count == 1

        ctcv = reports[1]
        assert ctcv.team_key == "CTCV"
        assert ctcv.total_issues == 1
        assert ctcv.todo_count == 1

    @pytest.mark.asyncio
    async def test_handles_connector_error(self):
        project = _make_project(team_projects=[["AIM", "HOP Drop 2"], ["CTCV", "HOP Drop 2"]])

        with patch("src.services.team_progress.JiraConnector") as MockJira:
            instance = MockJira.return_value
            instance.search = AsyncMock(side_effect=ConnectorError(500, "timeout"))
            instance.close = AsyncMock()

            service = TeamProgressService()
            reports = await service.get_team_reports(project)

        assert len(reports) == 2
        for r in reports:
            assert r.error is not None
            assert "timeout" in r.error
            assert r.total_issues == 0

    @pytest.mark.asyncio
    async def test_uses_cache(self):
        project = _make_project(team_projects=[["AIM", "HOP Drop 2"]])
        mock_issues = [_make_issue(project_key="AIM", status_category="Done", fix_versions=["HOP Drop 2"])]

        with patch("src.services.team_progress.JiraConnector") as MockJira:
            instance = MockJira.return_value
            instance.search = AsyncMock(return_value=mock_issues)
            instance.close = AsyncMock()

            service = TeamProgressService()
            reports1 = await service.get_team_reports(project)
            reports2 = await service.get_team_reports(project)

        # Search should only be called once (second call hits cache)
        instance.search.assert_called_once()
        assert reports1 == reports2

    @pytest.mark.asyncio
    async def test_totals_computation(self):
        """Verify that summing reports across teams produces correct totals."""
        project = _make_project(team_projects=[["AIM", "HOP Drop 2"], ["CTCV", "HOP Drop 2"]])
        mock_issues = [
            _make_issue(project_key="AIM", status_category="Done", sp_next_gen=3, fix_versions=["HOP Drop 2"]),
            _make_issue(project_key="CTCV", status_category="Done", sp_next_gen=5, fix_versions=["HOP Drop 2"]),
            _make_issue(project_key="CTCV", status_category="In Progress", sp_next_gen=2, fix_versions=["HOP Drop 2"]),
        ]

        with patch("src.services.team_progress.JiraConnector") as MockJira:
            instance = MockJira.return_value
            instance.search = AsyncMock(return_value=mock_issues)
            instance.close = AsyncMock()

            service = TeamProgressService()
            reports = await service.get_team_reports(project)

        total_issues = sum(r.total_issues for r in reports)
        total_done = sum(r.done_count for r in reports)
        total_sp = sum(r.sp_total for r in reports)
        total_sp_done = sum(r.sp_done for r in reports)

        assert total_issues == 3
        assert total_done == 2
        assert total_sp == 10.0
        assert total_sp_done == 8.0

    @pytest.mark.asyncio
    async def test_different_version_names_per_team(self):
        """Teams with different version names issue separate JQL queries."""
        project = _make_project(team_projects=[["AIM", "HOP Drop 2"], ["CTCV", "HOP Drop 3"]])

        aim_issues = [_make_issue(project_key="AIM", status_category="Done", sp_next_gen=3, fix_versions=["HOP Drop 2"])]
        ctcv_issues = [_make_issue(project_key="CTCV", status_category="In Progress", sp_next_gen=5, fix_versions=["HOP Drop 3"])]

        with patch("src.services.team_progress.JiraConnector") as MockJira:
            instance = MockJira.return_value
            # Return different issues for each JQL call
            instance.search = AsyncMock(side_effect=[aim_issues, ctcv_issues])
            instance.close = AsyncMock()

            service = TeamProgressService()
            reports = await service.get_team_reports(project)

        assert len(reports) == 2
        assert reports[0].team_key == "AIM"
        assert reports[0].version_name == "HOP Drop 2"
        assert reports[0].total_issues == 1
        assert reports[1].team_key == "CTCV"
        assert reports[1].version_name == "HOP Drop 3"
        assert reports[1].total_issues == 1

        # Two separate JQL queries should have been made
        assert instance.search.call_count == 2
