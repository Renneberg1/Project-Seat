"""Tests for Jira data models — from_api deserialization contracts."""

from __future__ import annotations

from typing import Any

import pytest

from src.models.jira import JiraIssue, JiraIssueType, JiraVersion


# ---------------------------------------------------------------------------
# JiraIssueType.from_api: Contract tests
# ---------------------------------------------------------------------------


def test_jira_issue_type_from_api_goal(sample_prog_issue_types):
    goal_data = next(
        it for it in sample_prog_issue_types["issueTypes"] if it["name"] == "Goal"
    )

    result = JiraIssueType.from_api(goal_data)

    assert result.id == "10423"
    assert result.name == "Goal"
    assert result.hierarchy_level == 3


def test_jira_issue_type_from_api_epic(sample_prog_issue_types):
    epic_data = next(
        it for it in sample_prog_issue_types["issueTypes"] if it["name"] == "Epic"
    )

    result = JiraIssueType.from_api(epic_data)

    assert result.id == "10000"
    assert result.name == "Epic"
    assert result.hierarchy_level == 1


@pytest.mark.parametrize("data,expected_level", [
    pytest.param({"id": "999", "name": "Custom"}, 0, id="missing-hierarchy-defaults-to-zero"),
    pytest.param({"id": "999", "name": "Custom", "hierarchy_level": 5}, 5, id="underscore-key-fallback"),
])
def test_jira_issue_type_from_api_hierarchy_level_fallback(data, expected_level):
    result = JiraIssueType.from_api(data)

    assert result.hierarchy_level == expected_level


# ---------------------------------------------------------------------------
# JiraVersion.from_api: Contract tests
# ---------------------------------------------------------------------------


def test_jira_version_from_api_released(sample_risk_versions):
    released = next(v for v in sample_risk_versions if v["name"] == "HOP Drop 2")

    result = JiraVersion.from_api(released)

    assert result.id == "11539"
    assert result.name == "HOP Drop 2"
    assert result.released is True
    assert result.release_date == "2026-03-06"


def test_jira_version_from_api_unreleased(sample_risk_versions):
    unreleased = next(v for v in sample_risk_versions if v["name"] == "HOP Drop 3")

    result = JiraVersion.from_api(unreleased)

    assert result.released is False
    assert result.release_date == "2026-05-06"


def test_jira_version_from_api_missing_release_date_returns_none():
    data = {"id": "1", "name": "v1", "projectId": "100", "archived": False, "released": False}

    result = JiraVersion.from_api(data)

    assert result.release_date is None


# ---------------------------------------------------------------------------
# JiraIssue.from_api: Contract tests
# ---------------------------------------------------------------------------


def test_jira_issue_from_api_goal(sample_jira_goal):
    result = JiraIssue.from_api(sample_jira_goal)

    assert result.key == "PROG-256"
    assert result.summary == "HOP Drop 2"
    assert result.status == "In Progress"
    assert result.issue_type == "Goal"
    assert result.project_key == "PROG"
    assert result.labels == ["CTC", "HOP"]
    assert result.due_date == "2026-03-06"
    assert result.fix_versions == []
    assert result.parent_key is None
    assert isinstance(result.description_adf, dict)


def test_jira_issue_from_api_initiative_with_parent(sample_jira_initiative):
    result = JiraIssue.from_api(sample_jira_initiative)

    assert result.key == "AIM-3295"
    assert result.summary == "CTC Model - Drop 2"
    assert result.parent_key == "PROG-256"
    assert result.project_key == "AIM"
    assert result.labels == ["AI", "CTC", "FPL"]


def test_jira_issue_from_api_minimal_dict_uses_safe_defaults():
    data = {"id": "1", "key": "TEST-1", "fields": {}}

    result = JiraIssue.from_api(data)

    assert result.key == "TEST-1"
    assert result.summary == ""
    assert result.status == ""
    assert result.issue_type == ""
    assert result.labels == []
    assert result.parent_key is None
    assert result.fix_versions == []
    assert result.due_date is None
    assert result.description_adf is None
