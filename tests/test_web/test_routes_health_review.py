"""Tests for Health Review routes — contract tests for GET and POST endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from src.models.project import Project


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project():
    return Project(
        id=1, jira_goal_key="PROG-100", name="Test Project",
        confluence_charter_id="111", confluence_xft_id="222",
        status="active", phase="planning", created_at="2026-01-01",
    )


# ---------------------------------------------------------------------------
# GET /project/{id}/health-review/
# ---------------------------------------------------------------------------


def test_health_review_page_returns_200(client, tmp_db):
    project = _make_project()

    with patch("src.web.deps.DashboardService") as MockDash, \
         patch("src.web.deps.HealthReviewService") as MockSvc:
        MockDash.return_value.get_project_by_id = lambda x: project
        MockDash.return_value.list_projects = lambda: [project]
        instance = MockSvc.return_value
        instance.list_reviews.return_value = []

        result = client.get("/project/1/health-review/")

    assert result.status_code == 200
    assert "Health Review" in result.text


def test_health_review_page_shows_past_reviews(client, tmp_db):
    project = _make_project()
    past_review = {
        "id": 1,
        "health_rating": "Green",
        "health_rationale": "On track",
        "top_concerns": [],
        "positive_observations": ["Good velocity"],
        "questions_for_pm": [],
        "suggested_next_actions": [],
        "created_at": "2026-02-01 10:00:00",
    }

    with patch("src.web.deps.DashboardService") as MockDash, \
         patch("src.web.deps.HealthReviewService") as MockSvc:
        MockDash.return_value.get_project_by_id = lambda x: project
        MockDash.return_value.list_projects = lambda: [project]
        instance = MockSvc.return_value
        instance.list_reviews.return_value = [past_review]

        result = client.get("/project/1/health-review/")

    assert result.status_code == 200
    assert "On track" in result.text


def test_health_review_page_missing_project_404(client, tmp_db):
    with patch("src.web.deps.DashboardService") as MockDash:
        MockDash.return_value.get_project_by_id = lambda x: None
        MockDash.return_value.list_projects = lambda: []

        result = client.get("/project/999/health-review/")

    assert result.status_code == 404


# ---------------------------------------------------------------------------
# POST /project/{id}/health-review/ask
# ---------------------------------------------------------------------------


def test_health_review_ask_returns_questions(client, tmp_db):
    project = _make_project()

    with patch("src.web.deps.DashboardService") as MockDash, \
         patch("src.web.deps.HealthReviewService") as MockSvc:
        MockDash.return_value.get_project_by_id = lambda x: project
        MockDash.return_value.list_projects = lambda: [project]
        instance = MockSvc.return_value
        instance.generate_questions = AsyncMock(return_value=[
            {"question": "How is team morale?", "category": "Team", "why_needed": "Cannot infer"},
        ])

        result = client.post("/project/1/health-review/ask")

    assert result.status_code == 200
    assert "How is team morale?" in result.text


def test_health_review_ask_no_questions(client, tmp_db):
    project = _make_project()

    with patch("src.web.deps.DashboardService") as MockDash, \
         patch("src.web.deps.HealthReviewService") as MockSvc:
        MockDash.return_value.get_project_by_id = lambda x: project
        MockDash.return_value.list_projects = lambda: [project]
        instance = MockSvc.return_value
        instance.generate_questions = AsyncMock(return_value=[])

        result = client.post("/project/1/health-review/ask")

    assert result.status_code == 200
    assert "No Questions Needed" in result.text


# ---------------------------------------------------------------------------
# POST /project/{id}/health-review/analyze
# ---------------------------------------------------------------------------


def test_health_review_analyze_returns_review(client, tmp_db):
    project = _make_project()

    mock_review = {
        "health_rating": "Amber",
        "health_rationale": "Some concerns remain.",
        "top_concerns": [
            {"area": "Risks", "severity": "High", "evidence": "3 open", "recommendation": "Triage"},
        ],
        "positive_observations": ["Good docs"],
        "questions_for_pm": ["Check RISK-101"],
        "suggested_next_actions": ["Conduct risk review"],
    }

    with patch("src.web.deps.DashboardService") as MockDash, \
         patch("src.web.deps.HealthReviewService") as MockSvc:
        MockDash.return_value.get_project_by_id = lambda x: project
        MockDash.return_value.list_projects = lambda: [project]
        instance = MockSvc.return_value
        instance.generate_review = AsyncMock(return_value=mock_review)
        instance.save_review.return_value = 42

        result = client.post(
            "/project/1/health-review/analyze",
            data={"question_0": "Morale?", "answer_0": "Good"},
        )

    assert result.status_code == 200
    assert "Amber" in result.text
    assert "Some concerns remain." in result.text
    assert "Good docs" in result.text
