"""Tests for Charter routes — contract tests for GET and POST endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from src.models.charter import CharterSuggestion, CharterSuggestionStatus
from src.models.project import Project


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project(charter_id="111"):
    return Project(
        id=1, jira_goal_key="PROG-100", name="Test Project",
        confluence_charter_id=charter_id, confluence_xft_id="222",
        status="active", phase="planning", created_at="2026-01-01",
    )


def _make_suggestion(**overrides):
    defaults = dict(
        id=1, project_id=1, section_name="Commercial Objective",
        current_text="Old", proposed_text="New",
        rationale="User asked", confidence=0.85,
        proposed_payload="{}", proposed_preview="",
        analysis_summary="Updated",
        status=CharterSuggestionStatus.PENDING,
        approval_item_id=None, created_at="2026-01-01",
    )
    defaults.update(overrides)
    return CharterSuggestion(**defaults)


# ---------------------------------------------------------------------------
# GET /project/{id}/charter/
# ---------------------------------------------------------------------------


def test_charter_page_returns_200(client, tmp_db):
    project = _make_project()

    with patch("src.web.routes.charter.DashboardService") as MockDash, \
         patch("src.web.routes.charter.CharterService") as MockSvc:
        MockDash.return_value.get_project_by_id = lambda x: project
        MockDash.return_value.list_projects = lambda: [project]
        instance = MockSvc.return_value
        instance.fetch_charter_sections = AsyncMock(return_value=[
            {"name": "Date", "content": "2026-01-01"},
        ])
        instance.list_suggestions.return_value = []

        result = client.get("/project/1/charter/")

    assert result.status_code == 200
    assert "Charter" in result.text


def test_charter_page_shows_sections(client, tmp_db):
    project = _make_project()

    with patch("src.web.routes.charter.DashboardService") as MockDash, \
         patch("src.web.routes.charter.CharterService") as MockSvc:
        MockDash.return_value.get_project_by_id = lambda x: project
        MockDash.return_value.list_projects = lambda: [project]
        instance = MockSvc.return_value
        instance.fetch_charter_sections = AsyncMock(return_value=[
            {"name": "Commercial Objective", "content": "Launch product"},
        ])
        instance.list_suggestions.return_value = []

        result = client.get("/project/1/charter/")

    assert "Commercial Objective" in result.text
    assert "Launch product" in result.text


def test_charter_page_missing_project_404(client, tmp_db):
    with patch("src.web.routes.charter.DashboardService") as MockDash:
        MockDash.return_value.get_project_by_id = lambda x: None
        MockDash.return_value.list_projects = lambda: []

        result = client.get("/project/999/charter/")

    assert result.status_code == 404


# ---------------------------------------------------------------------------
# POST /project/{id}/charter/ask
# ---------------------------------------------------------------------------


def test_charter_ask_returns_questions(client, tmp_db):
    project = _make_project()

    with patch("src.web.routes.charter.DashboardService") as MockDash, \
         patch("src.web.routes.charter.CharterService") as MockSvc:
        MockDash.return_value.get_project_by_id = lambda x: project
        MockDash.return_value.list_projects = lambda: [project]
        instance = MockSvc.return_value
        instance.generate_questions = AsyncMock(return_value=[
            {"question": "What date?", "section_name": "Date", "why_needed": "Missing"},
        ])

        result = client.post(
            "/project/1/charter/ask",
            data={"user_input": "Change the timeline"},
        )

    assert result.status_code == 200
    assert "What date?" in result.text


def test_charter_ask_no_charter_page_400(client, tmp_db):
    project = _make_project(charter_id=None)

    with patch("src.web.routes.charter.DashboardService") as MockDash:
        MockDash.return_value.get_project_by_id = lambda x: project
        MockDash.return_value.list_projects = lambda: [project]

        result = client.post(
            "/project/1/charter/ask",
            data={"user_input": "Change something"},
        )

    assert result.status_code == 400


# ---------------------------------------------------------------------------
# POST /project/{id}/charter/analyze
# ---------------------------------------------------------------------------


def test_charter_analyze_returns_suggestions(client, tmp_db):
    project = _make_project()

    mock_sug = _make_suggestion(proposed_text="2027-01-01", section_name="Date")

    with patch("src.web.routes.charter.DashboardService") as MockDash, \
         patch("src.web.routes.charter.CharterService") as MockSvc:
        MockDash.return_value.get_project_by_id = lambda x: project
        MockDash.return_value.list_projects = lambda: [project]
        instance = MockSvc.return_value
        instance.analyze_charter_update = AsyncMock(return_value=[mock_sug])

        result = client.post(
            "/project/1/charter/analyze",
            data={"user_input": "New date", "question_0": "Q?", "answer_0": "A"},
        )

    assert result.status_code == 200
    assert "2027-01-01" in result.text


# ---------------------------------------------------------------------------
# Accept / Reject
# ---------------------------------------------------------------------------


def test_accept_suggestion_returns_updated_row(client, tmp_db):
    project = _make_project()
    mock_sug = _make_suggestion(
        status=CharterSuggestionStatus.QUEUED, approval_item_id=42,
    )

    with patch("src.web.routes.charter.DashboardService") as MockDash, \
         patch("src.web.routes.charter.CharterService") as MockSvc:
        MockDash.return_value.get_project_by_id = lambda x: project
        MockDash.return_value.list_projects = lambda: [project]
        instance = MockSvc.return_value
        instance.accept_suggestion.return_value = mock_sug

        result = client.post("/project/1/charter/suggestions/1/accept")

    assert result.status_code == 200
    assert "queued" in result.text


def test_reject_suggestion_returns_updated_row(client, tmp_db):
    project = _make_project()
    mock_sug = _make_suggestion(status=CharterSuggestionStatus.REJECTED)

    with patch("src.web.routes.charter.DashboardService") as MockDash, \
         patch("src.web.routes.charter.CharterService") as MockSvc:
        MockDash.return_value.get_project_by_id = lambda x: project
        MockDash.return_value.list_projects = lambda: [project]
        instance = MockSvc.return_value
        instance.reject_suggestion.return_value = mock_sug

        result = client.post("/project/1/charter/suggestions/1/reject")

    assert result.status_code == 200
    assert "rejected" in result.text
