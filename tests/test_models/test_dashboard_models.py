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


# ---------------------------------------------------------------------------
# ProjectSummary: Contract tests
# ---------------------------------------------------------------------------


def test_project_summary_creation_with_all_fields(make_project, make_jira_issue):
    project = make_project()
    goal = make_jira_issue()

    result = ProjectSummary(
        project=project,
        goal=goal,
        risk_count=5,
        open_risk_count=3,
        decision_count=2,
        initiative_count=4,
        error=None,
    )

    assert result.project.name == "Test Project"
    assert result.goal is not None
    assert result.goal.status == "In Progress"
    assert result.risk_count == 5
    assert result.open_risk_count == 3
    assert result.decision_count == 2
    assert result.initiative_count == 4
    assert result.error is None


def test_project_summary_creation_with_error_and_no_goal(make_project):
    project = make_project()

    result = ProjectSummary(
        project=project,
        goal=None,
        risk_count=0,
        open_risk_count=0,
        decision_count=0,
        initiative_count=0,
        error="HTTP 503: Service Unavailable",
    )

    assert result.goal is None
    assert result.error == "HTTP 503: Service Unavailable"
    assert result.risk_count == 0


# ---------------------------------------------------------------------------
# InitiativeSummary: Contract tests
# ---------------------------------------------------------------------------


def test_initiative_summary_creation(make_jira_issue):
    issue = make_jira_issue(issue_type="Initiative")

    result = InitiativeSummary(
        issue=issue,
        epic_count=5,
        task_count=20,
        done_epic_count=2,
        done_task_count=10,
    )

    assert result.issue.key == "PROG-100"
    assert result.epic_count == 5
    assert result.task_count == 20
    assert result.done_epic_count == 2
    assert result.done_task_count == 10


# ---------------------------------------------------------------------------
# EpicWithTasks: Contract tests
# ---------------------------------------------------------------------------


def test_epic_with_tasks_creation(make_jira_issue):
    epic = make_jira_issue(key="AIM-100", issue_type="Epic")
    task = make_jira_issue(key="AIM-200", issue_type="Task", parent_key="AIM-100")

    result = EpicWithTasks(issue=epic, tasks=[task])

    assert result.issue.key == "AIM-100"
    assert len(result.tasks) == 1
    assert result.tasks[0].key == "AIM-200"


def test_epic_with_tasks_empty_tasks(make_jira_issue):
    epic = make_jira_issue(issue_type="Epic")

    result = EpicWithTasks(issue=epic, tasks=[])

    assert len(result.tasks) == 0


# ---------------------------------------------------------------------------
# InitiativeDetail: Contract tests
# ---------------------------------------------------------------------------


def test_initiative_detail_creation(make_jira_issue):
    initiative = make_jira_issue(issue_type="Initiative")
    epic = make_jira_issue(key="AIM-100", issue_type="Epic")
    task = make_jira_issue(key="AIM-200", issue_type="Task", parent_key="AIM-100")

    result = InitiativeDetail(
        issue=initiative,
        epics=[EpicWithTasks(issue=epic, tasks=[task])],
    )

    assert result.issue.key == "PROG-100"
    assert len(result.epics) == 1
    assert result.epics[0].issue.key == "AIM-100"
    assert len(result.epics[0].tasks) == 1


def test_initiative_detail_empty_epics(make_jira_issue):
    initiative = make_jira_issue(issue_type="Initiative")

    result = InitiativeDetail(issue=initiative, epics=[])

    assert len(result.epics) == 0


# ---------------------------------------------------------------------------
# PIPELINE_PHASES constant: Contract tests
# ---------------------------------------------------------------------------


def test_pipeline_phases_has_six_entries():
    result = len(PIPELINE_PHASES)

    assert result == 6


def test_pipeline_phases_values_in_correct_order():
    result = [v for v, _ in PIPELINE_PHASES]

    assert result == [
        "planning", "development", "dhf_update",
        "verification", "validation", "release",
    ]


def test_valid_phases_matches_pipeline_phases():
    result = VALID_PHASES

    assert result == {v for v, _ in PIPELINE_PHASES}
