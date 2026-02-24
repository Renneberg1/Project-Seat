"""Tests for the RiskRefineAgent — evaluation, Q&A loop, and retry."""

from __future__ import annotations

import json
from typing import Any

import pytest

from src.engine.agent import RiskRefineAgent


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
            "temperature": temperature,
        })
        return self._response

    async def close(self) -> None:
        pass


SAMPLE_DRAFT = {
    "title": "Model accuracy regression",
    "background": "High-res training showed accuracy drop",
    "impact_analysis": "Could delay timeline",
    "mitigation": "Run evaluation",
    "priority": "High",
    "timeline_impact_days": "5",
    "evidence": "Sarah said accuracy dropped",
}

SATISFIED_RESPONSE = json.dumps({
    "satisfied": True,
    "quality_assessment": "The risk is well-documented with specific impact and mitigation.",
    "questions": [],
    "refined_risk": {
        "title": "Model accuracy regression in CTC E2E pipeline",
        "background": "High-res training showed accuracy drop in CTC E2E model.",
        "impact_analysis": "Could delay Drop 2 by 5 days. Severity: Medium, Probability: High.",
        "mitigation": "Run MRMC evaluation comparing old vs new model. Revert if threshold not met.",
        "priority": "High",
        "timeline_impact_days": 5,
        "evidence": "Sarah said: 'The high-res training showed a drop in accuracy metrics.'",
    },
})

QUESTIONS_RESPONSE = json.dumps({
    "satisfied": False,
    "quality_assessment": "The title is too vague and mitigation lacks specifics.",
    "questions": [
        {
            "question": "What specific accuracy metrics dropped?",
            "field": "background",
            "why_needed": "Quantifying the regression helps assess severity.",
        },
        {
            "question": "Who will run the MRMC evaluation?",
            "field": "mitigation",
            "why_needed": "Mitigation steps should be assignable.",
        },
    ],
    "refined_risk": {
        "title": "Model accuracy regression in CTC E2E pipeline",
        "background": "High-res training showed accuracy drop.",
        "impact_analysis": "Could delay timeline.",
        "mitigation": "Run evaluation.",
        "priority": "High",
        "timeline_impact_days": 5,
        "evidence": "Sarah said accuracy dropped",
    },
})


class TestRiskRefineAgent:

    async def test_refine_returns_satisfied(self):
        provider = MockProvider(SATISFIED_RESPONSE)
        agent = RiskRefineAgent(provider)

        result = await agent.refine(
            suggestion_type="risk",
            current_draft=SAMPLE_DRAFT,
            existing_items=[],
            qa_history=[],
            round_number=1,
        )

        assert result["satisfied"] is True
        assert result["questions"] == []
        assert "title" in result["refined_risk"]

    async def test_refine_returns_questions(self):
        provider = MockProvider(QUESTIONS_RESPONSE)
        agent = RiskRefineAgent(provider)

        result = await agent.refine(
            suggestion_type="risk",
            current_draft=SAMPLE_DRAFT,
            existing_items=[],
            qa_history=[],
            round_number=1,
        )

        assert result["satisfied"] is False
        assert len(result["questions"]) == 2
        assert result["questions"][0]["field"] == "background"

    async def test_refine_includes_existing_items_in_prompt(self):
        provider = MockProvider(SATISFIED_RESPONSE)
        agent = RiskRefineAgent(provider)

        existing = [{"key": "RISK-100", "summary": "Existing risk", "status": "Open"}]
        await agent.refine(
            suggestion_type="risk",
            current_draft=SAMPLE_DRAFT,
            existing_items=existing,
            qa_history=[],
            round_number=1,
        )

        assert len(provider.generate_calls) == 1
        prompt = provider.generate_calls[0]["user_prompt"]
        assert "RISK-100" in prompt
        assert "Existing risk" in prompt

    async def test_refine_includes_qa_history_in_prompt(self):
        provider = MockProvider(SATISFIED_RESPONSE)
        agent = RiskRefineAgent(provider)

        qa = [{"question": "How bad?", "answer": "Pretty bad"}]
        await agent.refine(
            suggestion_type="risk",
            current_draft=SAMPLE_DRAFT,
            existing_items=[],
            qa_history=qa,
            round_number=2,
        )

        prompt = provider.generate_calls[0]["user_prompt"]
        assert "How bad?" in prompt
        assert "Pretty bad" in prompt
        assert "Round 2/" in prompt

    async def test_refine_final_round_instruction(self):
        provider = MockProvider(SATISFIED_RESPONSE)
        agent = RiskRefineAgent(provider)

        await agent.refine(
            suggestion_type="risk",
            current_draft=SAMPLE_DRAFT,
            existing_items=[],
            qa_history=[],
            round_number=5,
            max_rounds=5,
        )

        prompt = provider.generate_calls[0]["user_prompt"]
        assert "final round" in prompt.lower()
        assert "satisfied=true" in prompt.lower()

    async def test_refine_decision_type(self):
        provider = MockProvider(SATISFIED_RESPONSE)
        agent = RiskRefineAgent(provider)

        await agent.refine(
            suggestion_type="decision",
            current_draft=SAMPLE_DRAFT,
            existing_items=[],
            qa_history=[],
            round_number=1,
        )

        prompt = provider.generate_calls[0]["user_prompt"]
        assert "Decision" in prompt

    async def test_refine_retries_on_invalid_json(self):
        """Agent should retry once if first response is invalid JSON."""
        call_count = 0

        class RetryProvider:
            async def generate(self, system_prompt, user_prompt, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return "not valid json"
                return SATISFIED_RESPONSE

            async def close(self):
                pass

        agent = RiskRefineAgent(RetryProvider())
        result = await agent.refine(
            suggestion_type="risk",
            current_draft=SAMPLE_DRAFT,
            existing_items=[],
            qa_history=[],
            round_number=1,
        )

        assert call_count == 2
        assert result["satisfied"] is True

    async def test_refine_strips_markdown_fences(self):
        fenced = f"```json\n{SATISFIED_RESPONSE}\n```"
        provider = MockProvider(fenced)
        agent = RiskRefineAgent(provider)

        result = await agent.refine(
            suggestion_type="risk",
            current_draft=SAMPLE_DRAFT,
            existing_items=[],
            qa_history=[],
            round_number=1,
        )

        assert result["satisfied"] is True
