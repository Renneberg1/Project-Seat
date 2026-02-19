"""Dashboard data models — project summaries and pipeline phases."""

from __future__ import annotations

from dataclasses import dataclass

from src.models.jira import JiraIssue
from src.models.project import Project

# Pipeline phases in display order: (db_value, human_label)
PIPELINE_PHASES: list[tuple[str, str]] = [
    ("planning", "Planning"),
    ("development", "Development"),
    ("dhf_update", "DHF Update"),
    ("verification", "Verification"),
    ("validation", "Validation"),
    ("release", "Release"),
]

VALID_PHASES: set[str] = {value for value, _ in PIPELINE_PHASES}


@dataclass
class ProjectSummary:
    project: Project
    goal: JiraIssue | None
    risk_count: int
    open_risk_count: int
    decision_count: int
    initiative_count: int
    error: str | None


@dataclass
class InitiativeSummary:
    issue: JiraIssue
    epic_count: int
    task_count: int
    done_epic_count: int
    done_task_count: int


@dataclass
class EpicWithTasks:
    issue: JiraIssue
    tasks: list[JiraIssue]


@dataclass
class InitiativeDetail:
    issue: JiraIssue
    epics: list[EpicWithTasks]


@dataclass
class ProductIdeaSummary:
    total_count: int
    open_count: int
    done_count: int
    feature_count: int
    minor_feature_count: int
    idea_count: int
    defect_count: int
    must_have_count: int = 0
