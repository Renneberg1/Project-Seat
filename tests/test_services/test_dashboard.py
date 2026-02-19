"""Tests for dashboard service."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.connectors.base import ConnectorError
from src.database import get_db, init_db
from src.models.dashboard import InitiativeDetail, InitiativeSummary, ProjectSummary
from src.models.project import Project
from src.services.dashboard import DashboardService


def _insert_project(db_path: str, name: str = "Test Project", goal_key: str = "PROG-100", phase: str = "planning") -> int:
    with get_db(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO projects (jira_goal_key, name, status, phase) VALUES (?, ?, ?, ?)",
            (goal_key, name, "active", phase),
        )
        conn.commit()
        return cursor.lastrowid


def _make_jira_issue_response(key: str = "PROG-100", status: str = "In Progress", due: str | None = None) -> dict:
    return {
        "id": "10000",
        "key": key,
        "fields": {
            "summary": "Test Project",
            "status": {"name": status},
            "issuetype": {"name": "Goal"},
            "project": {"key": "PROG"},
            "labels": [],
            "fixVersions": [],
            "duedate": due,
            "parent": None,
            "description": None,
        },
    }


def _make_search_results(count: int, status: str = "Open") -> list[dict]:
    return [
        {"fields": {"status": {"name": status}}}
        for _ in range(count)
    ]


class TestListProjects:
    def test_returns_projects(self, tmp_db: str) -> None:
        _insert_project(tmp_db, "Alpha", "PROG-1")
        _insert_project(tmp_db, "Beta", "PROG-2")
        service = DashboardService(db_path=tmp_db)
        projects = service.list_projects()
        assert len(projects) == 2
        names = {p.name for p in projects}
        assert names == {"Alpha", "Beta"}

    def test_returns_empty_list(self, tmp_db: str) -> None:
        service = DashboardService(db_path=tmp_db)
        assert service.list_projects() == []


class TestUpdatePhase:
    def test_updates_phase(self, tmp_db: str) -> None:
        pid = _insert_project(tmp_db, phase="planning")
        service = DashboardService(db_path=tmp_db)
        service.update_phase(pid, "development")

        with get_db(tmp_db) as conn:
            row = conn.execute("SELECT phase FROM projects WHERE id = ?", (pid,)).fetchone()
        assert row["phase"] == "development"

    def test_invalid_phase_raises(self, tmp_db: str) -> None:
        pid = _insert_project(tmp_db)
        service = DashboardService(db_path=tmp_db)
        with pytest.raises(ValueError, match="Invalid phase"):
            service.update_phase(pid, "nonexistent")


class TestGetProjectSummary:
    @pytest.mark.asyncio
    async def test_returns_correct_counts(self, tmp_db: str, test_settings) -> None:
        pid = _insert_project(tmp_db)
        service = DashboardService(db_path=tmp_db, settings=test_settings)
        project = service.list_projects()[0]

        mock_jira = MagicMock()
        mock_jira.get_issue = AsyncMock(return_value=_make_jira_issue_response())
        mock_jira.search = AsyncMock(side_effect=[
            _make_search_results(3, "Open"),      # risks
            _make_search_results(2, "Open"),       # decisions
            _make_search_results(4, "Open"),       # initiatives
        ])
        mock_jira.close = AsyncMock()

        with patch("src.services.dashboard.JiraConnector", return_value=mock_jira):
            summary = await service.get_project_summary(project)

        assert summary.goal is not None
        assert summary.goal.key == "PROG-100"
        assert summary.risk_count == 3
        assert summary.open_risk_count == 3
        assert summary.decision_count == 2
        assert summary.initiative_count == 4
        assert summary.error is None

    @pytest.mark.asyncio
    async def test_jira_error_returns_error_string(self, tmp_db: str, test_settings) -> None:
        _insert_project(tmp_db)
        service = DashboardService(db_path=tmp_db, settings=test_settings)
        project = service.list_projects()[0]

        mock_jira = MagicMock()
        mock_jira.get_issue = AsyncMock(side_effect=ConnectorError(503, "Service Unavailable"))
        mock_jira.search = AsyncMock(return_value=[])
        mock_jira.close = AsyncMock()

        with patch("src.services.dashboard.JiraConnector", return_value=mock_jira):
            summary = await service.get_project_summary(project)

        assert summary.goal is None
        assert summary.error is not None
        assert "503" in summary.error
        assert summary.risk_count == 0


class TestGetAllSummaries:
    @pytest.mark.asyncio
    async def test_parallelizes_calls(self, tmp_db: str, test_settings) -> None:
        _insert_project(tmp_db, "Alpha", "PROG-1")
        _insert_project(tmp_db, "Beta", "PROG-2")
        service = DashboardService(db_path=tmp_db, settings=test_settings)

        mock_jira = MagicMock()
        mock_jira.get_issue = AsyncMock(return_value=_make_jira_issue_response())
        mock_jira.search = AsyncMock(return_value=[])
        mock_jira.close = AsyncMock()

        with patch("src.services.dashboard.JiraConnector", return_value=mock_jira):
            summaries = await service.get_all_summaries()

        assert len(summaries) == 2

    @pytest.mark.asyncio
    async def test_empty_projects_returns_empty(self, tmp_db: str, test_settings) -> None:
        service = DashboardService(db_path=tmp_db, settings=test_settings)
        summaries = await service.get_all_summaries()
        assert summaries == []


class TestGetProjectById:
    def test_returns_project(self, tmp_db: str) -> None:
        pid = _insert_project(tmp_db, "Alpha", "PROG-1")
        service = DashboardService(db_path=tmp_db)
        project = service.get_project_by_id(pid)
        assert project is not None
        assert project.name == "Alpha"
        assert project.jira_goal_key == "PROG-1"

    def test_returns_none_for_missing(self, tmp_db: str) -> None:
        service = DashboardService(db_path=tmp_db)
        assert service.get_project_by_id(999) is None


class TestGetInitiatives:
    @pytest.mark.asyncio
    async def test_returns_initiative_summaries(self, tmp_db: str, test_settings) -> None:
        pid = _insert_project(tmp_db, "Alpha", "PROG-1")
        service = DashboardService(db_path=tmp_db, settings=test_settings)
        project = service.list_projects()[0]

        initiative_data = [{
            "id": "20000", "key": "AIM-100",
            "fields": {
                "summary": "Feature A", "status": {"name": "In Progress"},
                "issuetype": {"name": "Initiative"}, "project": {"key": "AIM"},
                "labels": [], "fixVersions": [], "duedate": None, "parent": None,
                "description": None,
            },
        }]
        epic_data = [
            {"key": "AIM-200", "fields": {"status": {"name": "Done"}}},
            {"key": "AIM-201", "fields": {"status": {"name": "In Progress"}}},
        ]
        task_data_200 = [
            {"fields": {"status": {"name": "Done"}}},
            {"fields": {"status": {"name": "Done"}}},
        ]
        task_data_201 = [
            {"fields": {"status": {"name": "Open"}}},
        ]

        mock_jira = MagicMock()
        mock_jira.search = AsyncMock(side_effect=[
            initiative_data,  # initiatives
            epic_data,        # epics for AIM-100
            task_data_200,    # tasks for AIM-200
            task_data_201,    # tasks for AIM-201
        ])
        mock_jira.close = AsyncMock()

        with patch("src.services.dashboard.JiraConnector", return_value=mock_jira):
            results = await service.get_initiatives(project)

        assert len(results) == 1
        assert results[0].issue.key == "AIM-100"
        assert results[0].epic_count == 2
        assert results[0].done_epic_count == 1
        assert results[0].task_count == 3
        assert results[0].done_task_count == 2

    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self, tmp_db: str, test_settings) -> None:
        pid = _insert_project(tmp_db, "Alpha", "PROG-1")
        service = DashboardService(db_path=tmp_db, settings=test_settings)
        project = service.list_projects()[0]

        mock_jira = MagicMock()
        mock_jira.search = AsyncMock(side_effect=ConnectorError(503, "Unavailable"))
        mock_jira.close = AsyncMock()

        with patch("src.services.dashboard.JiraConnector", return_value=mock_jira):
            results = await service.get_initiatives(project)

        assert results == []


class TestGetInitiativeDetail:
    @pytest.mark.asyncio
    async def test_returns_detail(self, tmp_db: str, test_settings) -> None:
        service = DashboardService(db_path=tmp_db, settings=test_settings)

        initiative_data = {
            "id": "20000", "key": "AIM-100",
            "fields": {
                "summary": "Feature A", "status": {"name": "In Progress"},
                "issuetype": {"name": "Initiative"}, "project": {"key": "AIM"},
                "labels": [], "fixVersions": [], "duedate": None, "parent": None,
                "description": None,
            },
        }
        epic_data = [{
            "id": "20001", "key": "AIM-200",
            "fields": {
                "summary": "Epic 1", "status": {"name": "In Progress"},
                "issuetype": {"name": "Epic"}, "project": {"key": "AIM"},
                "labels": [], "fixVersions": [], "duedate": None, "parent": None,
                "description": None,
            },
        }]
        task_data = [{
            "id": "20002", "key": "AIM-300",
            "fields": {
                "summary": "Task 1", "status": {"name": "To Do"},
                "issuetype": {"name": "Task"}, "project": {"key": "AIM"},
                "labels": [], "fixVersions": [], "duedate": None, "parent": None,
                "description": None,
            },
        }]

        mock_jira = MagicMock()
        mock_jira.get_issue = AsyncMock(return_value=initiative_data)
        mock_jira.search = AsyncMock(side_effect=[
            epic_data,   # child epics
            task_data,   # tasks for AIM-200
        ])
        mock_jira.close = AsyncMock()

        with patch("src.services.dashboard.JiraConnector", return_value=mock_jira):
            detail = await service.get_initiative_detail("AIM-100")

        assert detail is not None
        assert detail.issue.key == "AIM-100"
        assert len(detail.epics) == 1
        assert detail.epics[0].issue.key == "AIM-200"
        assert len(detail.epics[0].tasks) == 1
        assert detail.epics[0].tasks[0].key == "AIM-300"

    @pytest.mark.asyncio
    async def test_returns_none_on_error(self, tmp_db: str, test_settings) -> None:
        service = DashboardService(db_path=tmp_db, settings=test_settings)

        mock_jira = MagicMock()
        mock_jira.get_issue = AsyncMock(side_effect=ConnectorError(404, "Not Found"))
        mock_jira.close = AsyncMock()

        with patch("src.services.dashboard.JiraConnector", return_value=mock_jira):
            detail = await service.get_initiative_detail("FAKE-999")

        assert detail is None
