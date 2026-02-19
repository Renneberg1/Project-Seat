"""Project domain models and spin-up request."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Project:
    id: int
    jira_goal_key: str
    name: str
    confluence_charter_id: str | None
    confluence_xft_id: str | None
    status: str
    phase: str
    created_at: str

    @classmethod
    def from_row(cls, row: Any) -> Project:
        return cls(
            id=row["id"],
            jira_goal_key=row["jira_goal_key"],
            name=row["name"],
            confluence_charter_id=row["confluence_charter_id"],
            confluence_xft_id=row["confluence_xft_id"],
            status=row["status"],
            phase=row["phase"],
            created_at=row["created_at"],
        )


@dataclass
class SpinUpRequest:
    project_name: str
    program: str
    team_projects: list[str]
    target_date: str
    labels: list[str]
    goal_summary: str
    confluence_space_key: str = "HPP"
