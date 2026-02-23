"""Tests for the HealthReviewService — context gathering, LLM calls, DB persistence."""

from __future__ import annotations

import json
import sqlite3
from unittest.mock import AsyncMock, patch

import pytest

from src.database import init_db
from src.models.project import Project
from src.services.health_review import HealthReviewService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO projects (id, jira_goal_key, name, status, phase, "
        "confluence_charter_id, confluence_xft_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (1, "PROG-100", "Test Project", "active", "planning", "111", "222"),
    )
    conn.commit()
    conn.close()
    return path


def _make_project() -> Project:
    return Project(
        id=1, jira_goal_key="PROG-100", name="Test Project",
        confluence_charter_id="111", confluence_xft_id="222",
        status="active", phase="planning", created_at="2026-01-01",
    )


# ---------------------------------------------------------------------------
# generate_questions
# ---------------------------------------------------------------------------


class TestGenerateQuestions:

    async def test_calls_agent_and_returns_questions(self, db_path):
        service = HealthReviewService(db_path=db_path)
        project = _make_project()

        mock_questions = [
            {"question": "Team morale?", "category": "Team", "why_needed": "Cannot infer"},
        ]

        mock_provider = AsyncMock()
        mock_provider.close = AsyncMock()

        with patch.object(service, "gather_all_context", new_callable=AsyncMock) as mock_gather, \
             patch("src.engine.agent.get_provider", return_value=mock_provider), \
             patch("src.engine.agent.HealthReviewAgent") as MockAgent:
            mock_gather.return_value = {"project_name": "Test Project"}
            instance = MockAgent.return_value
            instance.ask_questions = AsyncMock(return_value={"questions": mock_questions})

            result = await service.generate_questions(project)

        assert len(result) == 1
        assert result[0]["question"] == "Team morale?"


# ---------------------------------------------------------------------------
# generate_review
# ---------------------------------------------------------------------------


class TestGenerateReview:

    async def test_calls_agent_and_returns_review(self, db_path):
        service = HealthReviewService(db_path=db_path)
        project = _make_project()

        mock_review = {
            "health_rating": "Green",
            "health_rationale": "On track",
            "top_concerns": [],
            "positive_observations": ["Good velocity"],
            "questions_for_pm": [],
            "suggested_next_actions": ["Continue as planned"],
        }

        mock_provider = AsyncMock()
        mock_provider.close = AsyncMock()

        with patch.object(service, "gather_all_context", new_callable=AsyncMock) as mock_gather, \
             patch("src.engine.agent.get_provider", return_value=mock_provider), \
             patch("src.engine.agent.HealthReviewAgent") as MockAgent:
            mock_gather.return_value = {"project_name": "Test Project"}
            instance = MockAgent.return_value
            instance.generate_review = AsyncMock(return_value=mock_review)

            result = await service.generate_review(
                project, [{"question": "Q?", "answer": "A"}]
            )

        assert result["health_rating"] == "Green"
        assert result["positive_observations"] == ["Good velocity"]


# ---------------------------------------------------------------------------
# save_review / list_reviews / get_review
# ---------------------------------------------------------------------------


class TestReviewPersistence:

    def test_save_and_get_review(self, db_path):
        service = HealthReviewService(db_path=db_path)

        review = {
            "health_rating": "Amber",
            "health_rationale": "Some concerns",
            "top_concerns": [
                {"area": "Risk", "severity": "High", "evidence": "5 open", "recommendation": "Triage"}
            ],
            "positive_observations": ["Good docs"],
            "questions_for_pm": [],
            "suggested_next_actions": ["Review risks"],
        }

        review_id = service.save_review(1, review)
        assert review_id is not None

        fetched = service.get_review(review_id)
        assert fetched is not None
        assert fetched["health_rating"] == "Amber"
        assert fetched["id"] == review_id
        assert len(fetched["top_concerns"]) == 1

    def test_list_reviews(self, db_path):
        service = HealthReviewService(db_path=db_path)

        service.save_review(1, {"health_rating": "Green", "health_rationale": "Good"})
        service.save_review(1, {"health_rating": "Amber", "health_rationale": "OK"})

        reviews = service.list_reviews(1)
        assert len(reviews) == 2
        # Newest first
        assert reviews[0]["health_rating"] == "Amber"
        assert reviews[1]["health_rating"] == "Green"

    def test_list_reviews_empty(self, db_path):
        service = HealthReviewService(db_path=db_path)
        assert service.list_reviews(1) == []

    def test_get_review_not_found(self, db_path):
        service = HealthReviewService(db_path=db_path)
        assert service.get_review(999) is None
