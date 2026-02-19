"""Jira data models — normalized representations of API responses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class JiraIssueType:
    id: str
    name: str
    hierarchy_level: int

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> JiraIssueType:
        return cls(
            id=str(data["id"]),
            name=data["name"],
            hierarchy_level=data.get("hierarchyLevel", data.get("hierarchy_level", 0)),
        )


@dataclass
class JiraVersion:
    id: str
    name: str
    project_id: str
    archived: bool
    released: bool
    release_date: str | None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> JiraVersion:
        return cls(
            id=str(data["id"]),
            name=data["name"],
            project_id=str(data.get("projectId", "")),
            archived=data.get("archived", False),
            released=data.get("released", False),
            release_date=data.get("releaseDate"),
        )


@dataclass
class JiraIssue:
    id: str
    key: str
    summary: str
    status: str
    issue_type: str
    project_key: str
    labels: list[str]
    parent_key: str | None
    fix_versions: list[str]
    due_date: str | None
    description_adf: dict[str, Any] | None
    release_priority: str | None = None
    pi_state: str | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> JiraIssue:
        fields = data.get("fields", {})
        status_obj = fields.get("status", {})
        issue_type_obj = fields.get("issuetype", {})
        project_obj = fields.get("project", {})
        parent_obj = fields.get("parent")
        versions = fields.get("fixVersions", [])

        # Release priority — try both known custom field IDs
        rp_raw = fields.get("customfield_12812") or fields.get("customfield_11054")
        release_priority = rp_raw.get("value") if isinstance(rp_raw, dict) else None

        # PI State (customfield_13530)
        state_raw = fields.get("customfield_13530")
        pi_state = state_raw.get("value") if isinstance(state_raw, dict) else None

        return cls(
            id=str(data["id"]),
            key=data["key"],
            summary=fields.get("summary", ""),
            status=status_obj.get("name", ""),
            issue_type=issue_type_obj.get("name", ""),
            project_key=project_obj.get("key", ""),
            labels=fields.get("labels", []),
            parent_key=parent_obj.get("key") if parent_obj else None,
            fix_versions=[v.get("name", "") for v in versions],
            due_date=fields.get("duedate"),
            description_adf=fields.get("description"),
            release_priority=release_priority,
            pi_state=pi_state,
        )
