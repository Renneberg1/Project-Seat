"""Tests for dashboard data models."""

from __future__ import annotations

from src.models.dashboard import (
    PIPELINE_PHASES,
    VALID_PHASES,
    EpicWithTasks,
    InitiativeDetail,
    InitiativeSummary,
    ProjectSummary,
)
from src.models.jira import JiraIssue
from src.models.project import Project


def _make_project(**overrides) -> Project:
    defaults = dict(
        id=1,
        jira_goal_key="PROG-100",
        name="Test Project",
        confluence_charter_id=None,
        confluence_xft_id=None,
        status="active",
        phase="planning",
        created_at="2026-01-01T00:00:00",
    )
    defaults.update(overrides)
    return Project(**defaults)


def _make_goal() -> JiraIssue:
    return JiraIssue(
        id="10000",
        key="PROG-100",
        summary="Test Project",
        status="In Progress",
        issue_type="Goal",
        project_key="PROG",
        labels=[],
        parent_key=None,
        fix_versions=[],
        due_date="2026-06-01",
        description_adf=None,
    )


class TestProjectSummary:
    def test_creation_with_all_fields(self) -> None:
        project = _make_project()
        goal = _make_goal()
        summary = ProjectSummary(
            project=project,
            goal=goal,
            risk_count=5,
            open_risk_count=3,
            decision_count=2,
            initiative_count=4,
            error=None,
        )
        assert summary.project.name == "Test Project"
        assert summary.goal is not None
        assert summary.goal.status == "In Progress"
        assert summary.risk_count == 5
        assert summary.open_risk_count == 3
        assert summary.decision_count == 2
        assert summary.initiative_count == 4
        assert summary.error is None

    def test_creation_with_error(self) -> None:
        project = _make_project()
        summary = ProjectSummary(
            project=project,
            goal=None,
            risk_count=0,
            open_risk_count=0,
            decision_count=0,
            initiative_count=0,
            error="HTTP 503: Service Unavailable",
        )
        assert summary.goal is None
        assert summary.error == "HTTP 503: Service Unavailable"
        assert summary.risk_count == 0


class TestInitiativeSummary:
    def test_creation(self) -> None:
        issue = _make_goal()
        summary = InitiativeSummary(
            issue=issue,
            epic_count=5,
            task_count=20,
            done_epic_count=2,
            done_task_count=10,
        )
        assert summary.issue.key == "PROG-100"
        assert summary.epic_count == 5
        assert summary.task_count == 20
        assert summary.done_epic_count == 2
        assert summary.done_task_count == 10


class TestEpicWithTasks:
    def test_creation(self) -> None:
        epic = _make_goal()
        task = JiraIssue(
            id="10001", key="AIM-200", summary="Task 1",
            status="To Do", issue_type="Task", project_key="AIM",
            labels=[], parent_key="AIM-100", fix_versions=[],
            due_date=None, description_adf=None,
        )
        ewt = EpicWithTasks(issue=epic, tasks=[task])
        assert ewt.issue.key == "PROG-100"
        assert len(ewt.tasks) == 1
        assert ewt.tasks[0].key == "AIM-200"

    def test_empty_tasks(self) -> None:
        epic = _make_goal()
        ewt = EpicWithTasks(issue=epic, tasks=[])
        assert len(ewt.tasks) == 0


class TestInitiativeDetail:
    def test_creation(self) -> None:
        initiative = _make_goal()
        epic = JiraIssue(
            id="10001", key="AIM-100", summary="Epic 1",
            status="In Progress", issue_type="Epic", project_key="AIM",
            labels=[], parent_key=None, fix_versions=[],
            due_date=None, description_adf=None,
        )
        task = JiraIssue(
            id="10002", key="AIM-200", summary="Task 1",
            status="To Do", issue_type="Task", project_key="AIM",
            labels=[], parent_key="AIM-100", fix_versions=[],
            due_date=None, description_adf=None,
        )
        detail = InitiativeDetail(
            issue=initiative,
            epics=[EpicWithTasks(issue=epic, tasks=[task])],
        )
        assert detail.issue.key == "PROG-100"
        assert len(detail.epics) == 1
        assert detail.epics[0].issue.key == "AIM-100"
        assert len(detail.epics[0].tasks) == 1

    def test_empty_epics(self) -> None:
        initiative = _make_goal()
        detail = InitiativeDetail(issue=initiative, epics=[])
        assert len(detail.epics) == 0


class TestPipelinePhases:
    def test_has_six_entries(self) -> None:
        assert len(PIPELINE_PHASES) == 6

    def test_correct_values(self) -> None:
        values = [v for v, _ in PIPELINE_PHASES]
        assert values == [
            "planning", "development", "dhf_update",
            "verification", "validation", "release",
        ]

    def test_valid_phases_matches(self) -> None:
        assert VALID_PHASES == {v for v, _ in PIPELINE_PHASES}
