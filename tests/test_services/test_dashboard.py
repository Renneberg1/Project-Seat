"""Tests for dashboard service — local DB queries and live Jira enrichment."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.connectors.base import ConnectorError
from src.database import get_db
from src.services.dashboard import DashboardService


def _insert_project(db_path, name="Test Project", goal_key="PROG-100", phase="planning"):
    with get_db(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO projects (jira_goal_key, name, status, phase) VALUES (?, ?, ?, ?)",
            (goal_key, name, "active", phase),
        )
        conn.commit()
        return cursor.lastrowid


# ---------------------------------------------------------------------------
# list_projects: Incoming query — assert return value
# ---------------------------------------------------------------------------


def test_list_projects_returns_all_projects(tmp_db):
    _insert_project(tmp_db, "Alpha", "PROG-1")
    _insert_project(tmp_db, "Beta", "PROG-2")
    service = DashboardService(db_path=tmp_db)

    result = service.list_projects()

    assert len(result) == 2
    names = {p.name for p in result}
    assert names == {"Alpha", "Beta"}


def test_list_projects_returns_empty_list_when_no_projects(tmp_db):
    service = DashboardService(db_path=tmp_db)

    result = service.list_projects()

    assert result == []


# ---------------------------------------------------------------------------
# get_project_by_id: Incoming query — assert return value
# ---------------------------------------------------------------------------


def test_get_project_by_id_returns_project(tmp_db):
    pid = _insert_project(tmp_db, "Alpha", "PROG-1")
    service = DashboardService(db_path=tmp_db)

    result = service.get_project_by_id(pid)

    assert result is not None
    assert result.name == "Alpha"
    assert result.jira_goal_key == "PROG-1"


def test_get_project_by_id_returns_none_for_missing(tmp_db):
    service = DashboardService(db_path=tmp_db)

    result = service.get_project_by_id(999)

    assert result is None


# ---------------------------------------------------------------------------
# update_phase: Incoming command — assert side effect
# ---------------------------------------------------------------------------


def test_update_phase_updates_database(tmp_db):
    pid = _insert_project(tmp_db, phase="planning")
    service = DashboardService(db_path=tmp_db)

    result = service.update_phase(pid, "development")

    with get_db(tmp_db) as conn:
        row = conn.execute("SELECT phase FROM projects WHERE id = ?", (pid,)).fetchone()
    assert row["phase"] == "development"


def test_update_phase_invalid_phase_raises_value_error(tmp_db):
    pid = _insert_project(tmp_db)
    service = DashboardService(db_path=tmp_db)

    with pytest.raises(ValueError, match="Invalid phase"):
        service.update_phase(pid, "nonexistent")


# ---------------------------------------------------------------------------
# get_project_summary: Incoming query (async) — assert return value
# ---------------------------------------------------------------------------


async def test_get_project_summary_returns_correct_counts(tmp_db, test_settings, make_jira_issue_response):
    _insert_project(tmp_db)
    service = DashboardService(db_path=tmp_db, settings=test_settings)
    project = service.list_projects()[0]
    mock_jira = MagicMock()
    mock_jira.get_issue = AsyncMock(return_value=make_jira_issue_response())
    mock_jira.search = AsyncMock(side_effect=[
        [{"id": str(i), "key": f"RISK-{i}", "fields": {"summary": f"Risk {i}", "status": {"name": "Open"}, "issuetype": {"name": "Risk"}, "project": {"key": "RISK"}}} for i in range(3)],  # risks
        [{"id": str(i), "key": f"RISK-{100+i}", "fields": {"summary": f"Decision {i}", "status": {"name": "Open"}, "issuetype": {"name": "Project Issue"}, "project": {"key": "RISK"}}} for i in range(2)],  # decisions
        [{"fields": {"status": {"name": "Open"}}}] * 4,  # initiatives (still count-only)
    ])
    mock_jira.close = AsyncMock()

    with patch("src.services.dashboard.JiraConnector", return_value=mock_jira):
        result = await service.get_project_summary(project)

    assert result.goal is not None
    assert result.goal.key == "PROG-100"
    assert result.risk_count == 3
    assert result.open_risk_count == 3
    assert result.decision_count == 2
    assert result.initiative_count == 4
    assert result.error is None


async def test_get_project_summary_jira_error_returns_error_string(tmp_db, test_settings):
    _insert_project(tmp_db)
    service = DashboardService(db_path=tmp_db, settings=test_settings)
    project = service.list_projects()[0]
    mock_jira = MagicMock()
    mock_jira.get_issue = AsyncMock(side_effect=ConnectorError(503, "Service Unavailable"))
    mock_jira.search = AsyncMock(return_value=[])
    mock_jira.close = AsyncMock()

    with patch("src.services.dashboard.JiraConnector", return_value=mock_jira):
        result = await service.get_project_summary(project)

    assert result.goal is None
    assert result.error is not None
    assert "503" in result.error
    assert result.risk_count == 0


# ---------------------------------------------------------------------------
# get_all_summaries: Incoming query (async) — assert return value
# ---------------------------------------------------------------------------


async def test_get_all_summaries_returns_summary_per_project(tmp_db, test_settings, make_jira_issue_response):
    _insert_project(tmp_db, "Alpha", "PROG-1")
    _insert_project(tmp_db, "Beta", "PROG-2")
    service = DashboardService(db_path=tmp_db, settings=test_settings)
    mock_jira = MagicMock()
    mock_jira.get_issue = AsyncMock(return_value=make_jira_issue_response())
    mock_jira.search = AsyncMock(return_value=[])
    mock_jira.close = AsyncMock()

    with patch("src.services.dashboard.JiraConnector", return_value=mock_jira):
        result = await service.get_all_summaries()

    assert len(result) == 2


async def test_get_all_summaries_empty_projects_returns_empty(tmp_db, test_settings):
    service = DashboardService(db_path=tmp_db, settings=test_settings)

    result = await service.get_all_summaries()

    assert result == []


# ---------------------------------------------------------------------------
# get_initiatives: Incoming query (async) — assert return value
# ---------------------------------------------------------------------------


async def test_get_initiatives_returns_summaries_with_counts(tmp_db, test_settings):
    _insert_project(tmp_db, "Alpha", "PROG-1")
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
        initiative_data, epic_data, task_data_200, task_data_201,
    ])
    mock_jira.close = AsyncMock()

    with patch("src.services.dashboard.JiraConnector", return_value=mock_jira):
        result = await service.get_initiatives(project)

    assert len(result) == 1
    assert result[0].issue.key == "AIM-100"
    assert result[0].epic_count == 2
    assert result[0].done_epic_count == 1
    assert result[0].task_count == 3
    assert result[0].done_task_count == 2


async def test_get_initiatives_connector_error_returns_empty(tmp_db, test_settings):
    _insert_project(tmp_db, "Alpha", "PROG-1")
    service = DashboardService(db_path=tmp_db, settings=test_settings)
    project = service.list_projects()[0]
    mock_jira = MagicMock()
    mock_jira.search = AsyncMock(side_effect=ConnectorError(503, "Unavailable"))
    mock_jira.close = AsyncMock()

    with patch("src.services.dashboard.JiraConnector", return_value=mock_jira):
        result = await service.get_initiatives(project)

    assert result == []


# ---------------------------------------------------------------------------
# get_initiative_detail: Incoming query (async) — assert return value
# ---------------------------------------------------------------------------


async def test_get_initiative_detail_returns_full_hierarchy(tmp_db, test_settings):
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
    mock_jira.search = AsyncMock(side_effect=[epic_data, task_data])
    mock_jira.close = AsyncMock()

    with patch("src.services.dashboard.JiraConnector", return_value=mock_jira):
        result = await service.get_initiative_detail("AIM-100")

    assert result is not None
    assert result.issue.key == "AIM-100"
    assert len(result.epics) == 1
    assert result.epics[0].issue.key == "AIM-200"
    assert len(result.epics[0].tasks) == 1
    assert result.epics[0].tasks[0].key == "AIM-300"


async def test_get_initiative_detail_connector_error_returns_none(tmp_db, test_settings):
    service = DashboardService(db_path=tmp_db, settings=test_settings)
    mock_jira = MagicMock()
    mock_jira.get_issue = AsyncMock(side_effect=ConnectorError(404, "Not Found"))
    mock_jira.close = AsyncMock()

    with patch("src.services.dashboard.JiraConnector", return_value=mock_jira):
        result = await service.get_initiative_detail("FAKE-999")

    assert result is None
