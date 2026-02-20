"""Tests for the CharterAgent — questions and edits LLM interactions."""

from __future__ import annotations

import json
from typing import Any

import pytest

from src.engine.agent import CharterAgent


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
def sample_sections() -> list[dict[str, str]]:
    return [
        {"name": "Project Name/Release", "content": "HOP Drop 3"},
        {"name": "Commercial Objective", "content": "Expand market share"},
        {"name": "Project Scope — In Scope", "content": "AIM model v2"},
        {"name": "Success Criteria", "content": "95% sensitivity"},
    ]


@pytest.fixture()
def questions_response() -> str:
    return json.dumps({
        "questions": [
            {
                "question": "What is the new target date?",
                "section_name": "Date",
                "why_needed": "The user mentioned a timeline change but no specific date.",
            },
            {
                "question": "Which teams are added to the scope?",
                "section_name": "Project Scope — In Scope",
                "why_needed": "Need to know specific team names for scope update.",
            },
        ],
    })


@pytest.fixture()
def edits_response() -> str:
    return json.dumps({
        "summary": "Updated scope and timeline based on user input.",
        "section_edits": [
            {
                "section_name": "Project Scope — In Scope",
                "proposed_text": "AIM model v2, CTCV integration",
                "rationale": "User requested adding CTCV team to scope.",
                "confidence": 0.9,
            },
            {
                "section_name": "Date",
                "proposed_text": "2027-03-01",
                "rationale": "User specified March 2027 as new target date.",
                "confidence": 0.95,
            },
        ],
    })


# ---------------------------------------------------------------------------
# ask_questions tests
# ---------------------------------------------------------------------------


class TestCharterAgentAskQuestions:

    async def test_returns_parsed_questions(self, sample_sections, questions_response):
        provider = MockProvider(questions_response)
        agent = CharterAgent(provider)

        result = await agent.ask_questions(sample_sections, "Change the timeline and scope")

        assert "questions" in result
        assert len(result["questions"]) == 2
        assert result["questions"][0]["section_name"] == "Date"

    async def test_includes_sections_in_prompt(self, sample_sections, questions_response):
        provider = MockProvider(questions_response)
        agent = CharterAgent(provider)

        await agent.ask_questions(sample_sections, "Change the timeline")

        assert len(provider.generate_calls) == 1
        prompt = provider.generate_calls[0]["user_prompt"]
        assert "HOP Drop 3" in prompt
        assert "Commercial Objective" in prompt

    async def test_includes_user_input_in_prompt(self, sample_sections, questions_response):
        provider = MockProvider(questions_response)
        agent = CharterAgent(provider)

        await agent.ask_questions(sample_sections, "Add CTCV to scope")

        prompt = provider.generate_calls[0]["user_prompt"]
        assert "Add CTCV to scope" in prompt

    async def test_includes_project_context(self, sample_sections, questions_response):
        provider = MockProvider(questions_response)
        agent = CharterAgent(provider)

        await agent.ask_questions(
            sample_sections, "Changes", project_context={"project_name": "HOP Drop 3"}
        )

        prompt = provider.generate_calls[0]["user_prompt"]
        assert "HOP Drop 3" in prompt

    async def test_passes_schema(self, sample_sections, questions_response):
        provider = MockProvider(questions_response)
        agent = CharterAgent(provider)

        await agent.ask_questions(sample_sections, "input")

        assert provider.generate_calls[0]["response_schema"] is not None


# ---------------------------------------------------------------------------
# propose_edits tests
# ---------------------------------------------------------------------------


class TestCharterAgentProposeEdits:

    async def test_returns_parsed_edits(self, sample_sections, edits_response):
        provider = MockProvider(edits_response)
        agent = CharterAgent(provider)

        result = await agent.propose_edits(
            sample_sections, "Add CTCV to scope", [{"question": "Q?", "answer": "A"}]
        )

        assert "summary" in result
        assert len(result["section_edits"]) == 2
        assert result["section_edits"][0]["section_name"] == "Project Scope — In Scope"

    async def test_includes_qa_pairs_in_prompt(self, sample_sections, edits_response):
        provider = MockProvider(edits_response)
        agent = CharterAgent(provider)

        await agent.propose_edits(
            sample_sections,
            "Update scope",
            [{"question": "Which teams?", "answer": "CTCV and YAM"}],
        )

        prompt = provider.generate_calls[0]["user_prompt"]
        assert "Which teams?" in prompt
        assert "CTCV and YAM" in prompt

    async def test_includes_user_input_and_sections(self, sample_sections, edits_response):
        provider = MockProvider(edits_response)
        agent = CharterAgent(provider)

        await agent.propose_edits(
            sample_sections, "New scope", [{"question": "Q", "answer": "A"}]
        )

        prompt = provider.generate_calls[0]["user_prompt"]
        assert "New scope" in prompt
        assert "Success Criteria" in prompt

    async def test_retry_on_invalid_json(self, sample_sections):
        """Agent retries once if first response is invalid JSON."""
        call_count = 0

        class RetryProvider:
            async def generate(self, system_prompt, user_prompt, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return "not valid json"
                return json.dumps({
                    "summary": "Retry succeeded.",
                    "section_edits": [],
                })

            async def close(self):
                pass

        agent = CharterAgent(RetryProvider())
        result = await agent.propose_edits(
            sample_sections, "input", [{"question": "Q", "answer": "A"}]
        )

        assert call_count == 2
        assert result["summary"] == "Retry succeeded."
