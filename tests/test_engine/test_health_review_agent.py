"""Tests for the HealthReviewAgent — questions and review LLM interactions."""

from __future__ import annotations

import json
from typing import Any

import pytest

from src.engine.agent import HealthReviewAgent


# ---------------------------------------------------------------------------
# Mock provider
# ---------------------------------------------------------------------------


class MockProvider:
    """A mock LLM provider that returns a predetermined response."""

    def __init__(self, response: str):
        self._response = response
        self.generate_calls: list[dict[str, Any]] = []

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        response_schema: dict[str, Any] | None = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> str:
        self.generate_calls.append({
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "response_schema": response_schema,
        })
        return self._response

    async def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_context() -> dict[str, Any]:
    return {
        "project_name": "HOP Drop 3",
        "goal": {
            "key": "PROG-256",
            "summary": "HOP Drop 3",
            "status": "In Progress",
            "due_date": "2026-06-01",
        },
        "risk_count": 5,
        "open_risk_count": 3,
        "decision_count": 2,
    }


@pytest.fixture()
def questions_response() -> str:
    return json.dumps({
        "questions": [
            {
                "question": "How is team morale?",
                "category": "Team",
                "why_needed": "Cannot determine team health from Jira data alone.",
            },
            {
                "question": "Are there any budget constraints?",
                "category": "Budget",
                "why_needed": "No budget data available in the project tools.",
            },
        ],
    })


@pytest.fixture()
def review_response() -> str:
    return json.dumps({
        "health_rating": "Amber",
        "health_rationale": "Project is progressing but risk register needs attention.",
        "top_concerns": [
            {
                "area": "Risk Management",
                "severity": "High",
                "evidence": "3 of 5 risks remain open with no mitigation plans.",
                "recommendation": "Schedule risk review meeting within 2 weeks.",
            },
        ],
        "positive_observations": [
            "Team velocity is consistent over the last 4 sprints.",
        ],
        "questions_for_pm": [
            "Why has RISK-101 been open for 60 days without progress?",
        ],
        "suggested_next_actions": [
            "Conduct risk review meeting to triage open risks.",
            "Update Charter with revised timeline.",
        ],
    })


# ---------------------------------------------------------------------------
# ask_questions tests
# ---------------------------------------------------------------------------


class TestHealthReviewAgentAskQuestions:

    async def test_returns_parsed_questions(self, sample_context, questions_response):
        provider = MockProvider(questions_response)
        agent = HealthReviewAgent(provider)

        result = await agent.ask_questions(sample_context)

        assert "questions" in result
        assert len(result["questions"]) == 2
        assert result["questions"][0]["category"] == "Team"

    async def test_includes_project_data_in_prompt(self, sample_context, questions_response):
        provider = MockProvider(questions_response)
        agent = HealthReviewAgent(provider)

        await agent.ask_questions(sample_context)

        assert len(provider.generate_calls) == 1
        prompt = provider.generate_calls[0]["user_prompt"]
        assert "HOP Drop 3" in prompt
        assert "PROG-256" in prompt

    async def test_passes_schema(self, sample_context, questions_response):
        provider = MockProvider(questions_response)
        agent = HealthReviewAgent(provider)

        await agent.ask_questions(sample_context)

        assert provider.generate_calls[0]["response_schema"] is not None


# ---------------------------------------------------------------------------
# generate_review tests
# ---------------------------------------------------------------------------


class TestHealthReviewAgentGenerateReview:

    async def test_returns_parsed_review(self, sample_context, review_response):
        provider = MockProvider(review_response)
        agent = HealthReviewAgent(provider)

        result = await agent.generate_review(
            sample_context, [{"question": "Morale?", "answer": "Good"}]
        )

        assert result["health_rating"] == "Amber"
        assert len(result["top_concerns"]) == 1
        assert result["top_concerns"][0]["severity"] == "High"

    async def test_includes_qa_pairs_in_prompt(self, sample_context, review_response):
        provider = MockProvider(review_response)
        agent = HealthReviewAgent(provider)

        await agent.generate_review(
            sample_context,
            [{"question": "Team morale?", "answer": "Excellent"}],
        )

        prompt = provider.generate_calls[0]["user_prompt"]
        assert "Team morale?" in prompt
        assert "Excellent" in prompt

    async def test_includes_project_data_in_prompt(self, sample_context, review_response):
        provider = MockProvider(review_response)
        agent = HealthReviewAgent(provider)

        await agent.generate_review(sample_context, [])

        prompt = provider.generate_calls[0]["user_prompt"]
        assert "HOP Drop 3" in prompt
        assert "risk_register" in prompt

    async def test_retry_on_invalid_json(self, sample_context):
        """Agent retries once if first response is invalid JSON."""
        call_count = 0

        class RetryProvider:
            async def generate(self, system_prompt, user_prompt, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return "not valid json"
                return json.dumps({
                    "health_rating": "Green",
                    "health_rationale": "Retry succeeded.",
                    "top_concerns": [],
                    "positive_observations": [],
                    "questions_for_pm": [],
                    "suggested_next_actions": [],
                })

            async def close(self):
                pass

        agent = HealthReviewAgent(RetryProvider())
        result = await agent.generate_review(sample_context, [])

        assert call_count == 2
        assert result["health_rationale"] == "Retry succeeded."
