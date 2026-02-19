"""Tests for Jira data models."""

from __future__ import annotations

from typing import Any

from src.models.jira import JiraIssue, JiraIssueType, JiraVersion


class TestJiraIssueType:
    def test_from_api_goal(self, sample_prog_issue_types: dict[str, Any]) -> None:
        goal_data = next(
            it for it in sample_prog_issue_types["issueTypes"] if it["name"] == "Goal"
        )
        result = JiraIssueType.from_api(goal_data)
        assert result.id == "10423"
        assert result.name == "Goal"
        assert result.hierarchy_level == 3

    def test_from_api_epic(self, sample_prog_issue_types: dict[str, Any]) -> None:
        epic_data = next(
            it for it in sample_prog_issue_types["issueTypes"] if it["name"] == "Epic"
        )
        result = JiraIssueType.from_api(epic_data)
        assert result.id == "10000"
        assert result.name == "Epic"
        assert result.hierarchy_level == 1

    def test_fallback_missing_hierarchy_level(self) -> None:
        data = {"id": "999", "name": "Custom"}
        result = JiraIssueType.from_api(data)
        assert result.hierarchy_level == 0

    def test_fallback_underscore_key(self) -> None:
        data = {"id": "999", "name": "Custom", "hierarchy_level": 5}
        result = JiraIssueType.from_api(data)
        assert result.hierarchy_level == 5


class TestJiraVersion:
    def test_from_api_released(self, sample_risk_versions: list[dict[str, Any]]) -> None:
        released = next(v for v in sample_risk_versions if v["name"] == "HOP Drop 2")
        result = JiraVersion.from_api(released)
        assert result.id == "11539"
        assert result.name == "HOP Drop 2"
        assert result.released is True
        assert result.release_date == "2026-03-06"

    def test_from_api_unreleased(self, sample_risk_versions: list[dict[str, Any]]) -> None:
        unreleased = next(v for v in sample_risk_versions if v["name"] == "HOP Drop 3")
        result = JiraVersion.from_api(unreleased)
        assert result.released is False
        assert result.release_date == "2026-05-06"

    def test_missing_release_date(self) -> None:
        data = {"id": "1", "name": "v1", "projectId": "100", "archived": False, "released": False}
        result = JiraVersion.from_api(data)
        assert result.release_date is None


class TestJiraIssue:
    def test_from_api_goal(self, sample_jira_goal: dict[str, Any]) -> None:
        issue = JiraIssue.from_api(sample_jira_goal)
        assert issue.key == "PROG-256"
        assert issue.summary == "HOP Drop 2"
        assert issue.status == "In Progress"
        assert issue.issue_type == "Goal"
        assert issue.project_key == "PROG"
        assert issue.labels == ["CTC", "HOP"]
        assert issue.due_date == "2026-03-06"
        assert issue.fix_versions == []
        assert issue.parent_key is None
        assert isinstance(issue.description_adf, dict)

    def test_from_api_initiative_with_parent(self, sample_jira_initiative: dict[str, Any]) -> None:
        issue = JiraIssue.from_api(sample_jira_initiative)
        assert issue.key == "AIM-3295"
        assert issue.summary == "CTC Model - Drop 2"
        assert issue.parent_key == "PROG-256"
        assert issue.project_key == "AIM"
        assert issue.labels == ["AI", "CTC", "FPL"]

    def test_minimal_dict_safe_defaults(self) -> None:
        data = {"id": "1", "key": "TEST-1", "fields": {}}
        issue = JiraIssue.from_api(data)
        assert issue.key == "TEST-1"
        assert issue.summary == ""
        assert issue.status == ""
        assert issue.issue_type == ""
        assert issue.labels == []
        assert issue.parent_key is None
        assert issue.fix_versions == []
        assert issue.due_date is None
        assert issue.description_adf is None
