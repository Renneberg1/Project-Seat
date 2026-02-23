"""Project domain models and spin-up request."""

from __future__ import annotations

import json
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
    dhf_draft_root_id: str | None = None
    dhf_released_root_id: str | None = None
    pi_version: str | None = None
    default_component: str | None = None
    default_label: str | None = None
    team_projects: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_row(cls, row: Any) -> Project:
        # Parse team_projects JSON — backward-compat: list → dict keyed by project name
        raw_teams: dict[str, str] = {}
        if "team_projects" in row.keys() and row["team_projects"]:
            parsed = json.loads(row["team_projects"])
            if isinstance(parsed, list):
                raw_teams = {k: row["name"] for k in parsed}
            elif isinstance(parsed, dict):
                raw_teams = parsed

        return cls(
            id=row["id"],
            jira_goal_key=row["jira_goal_key"],
            name=row["name"],
            confluence_charter_id=row["confluence_charter_id"],
            confluence_xft_id=row["confluence_xft_id"],
            status=row["status"],
            phase=row["phase"],
            created_at=row["created_at"],
            dhf_draft_root_id=row["dhf_draft_root_id"] if "dhf_draft_root_id" in row.keys() else None,
            dhf_released_root_id=row["dhf_released_root_id"] if "dhf_released_root_id" in row.keys() else None,
            pi_version=row["pi_version"] if "pi_version" in row.keys() else None,
            default_component=row["default_component"] if "default_component" in row.keys() else None,
            default_label=row["default_label"] if "default_label" in row.keys() else None,
            team_projects=raw_teams,
        )


@dataclass
class SpinUpRequest:
    project_name: str
    program: str
    team_projects: dict[str, str]
    target_date: str
    labels: list[str]
    goal_summary: str
    confluence_space_key: str = ""  # Filled from settings at creation time
    pi_version: str = ""
