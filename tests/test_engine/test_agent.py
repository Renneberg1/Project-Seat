"""Tests for the LLM agent layer — provider factory, mock provider, TranscriptAgent."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.config import LLMSettings
from src.engine.agent import TranscriptAgent, get_provider


# ---------------------------------------------------------------------------
# Provider factory tests
# ---------------------------------------------------------------------------


class TestGetProvider:

    def test_gemini_provider(self):
        settings = LLMSettings(provider="gemini", api_key="test-key", model="gemini-2.5-flash")
        provider = get_provider(settings)
        from src.engine.providers.gemini import GeminiProvider
        assert isinstance(provider, GeminiProvider)

    def test_ollama_provider(self, monkeypatch):
        monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434")
        settings = LLMSettings(provider="ollama", api_key="", model="llama3.3:70b")
        provider = get_provider(settings)
        from src.engine.providers.ollama import OllamaProvider
        assert isinstance(provider, OllamaProvider)

    def test_unknown_provider_raises(self):
        settings = LLMSettings(provider="unknown_provider", api_key="", model="")
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            get_provider(settings)


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
# TranscriptAgent tests
# ---------------------------------------------------------------------------


class TestTranscriptAgent:

    @pytest.fixture()
    def sample_llm_response(self) -> str:
        return json.dumps({
            "meeting_summary": "Team discussed model performance risks and UI redesign postponement.",
            "suggestions": [
                {
                    "type": "risk",
                    "title": "Performance regression in CTC E2E model",
                    "background": "The high-res training showed a drop in accuracy.",
                    "impact_analysis": "Could delay Drop 2 timeline by 5 days.",
                    "mitigation": "Run MRMC evaluation. Compare old vs new model.",
                    "evidence": "Sarah said: 'The high-res training showed a drop in accuracy metrics.'",
                    "priority": "High",
                    "timeline_impact_days": 5,
                    "confidence": 0.85,
                    "confluence_section_title": None,
                    "confluence_content": None,
                },
                {
                    "type": "decision",
                    "title": "Postpone UI redesign to Drop 3",
                    "background": "Team decided to defer UI work.",
                    "impact_analysis": "Reduces Drop 2 scope.",
                    "mitigation": "Track in Drop 3 backlog.",
                    "evidence": "Sarah: 'We also decided to postpone the UI redesign to Drop 3.'",
                    "priority": "Medium",
                    "timeline_impact_days": None,
                    "confidence": 0.9,
                    "confluence_section_title": None,
                    "confluence_content": None,
                },
            ],
        })

    @pytest.fixture()
    def project_context(self) -> dict[str, Any]:
        return {
            "project_name": "HOP Drop 2",
            "jira_goal_key": "PROG-256",
            "existing_risks": [
                {"key": "RISK-100", "summary": "Existing risk", "status": "Open"},
            ],
            "existing_decisions": [],
            "charter_content": "<p>Charter content here</p>",
            "xft_content": "<p>XFT content here</p>",
        }

    async def test_analyze_returns_parsed_json(self, sample_llm_response, project_context):
        provider = MockProvider(sample_llm_response)
        agent = TranscriptAgent(provider)

        result = await agent.analyze_transcript(
            transcript_text="Thomas: We need to discuss risks.",
            project_context=project_context,
        )

        assert "meeting_summary" in result
        assert len(result["suggestions"]) == 2
        assert result["suggestions"][0]["type"] == "risk"
        assert result["suggestions"][1]["type"] == "decision"

    async def test_analyze_calls_provider_with_context(self, sample_llm_response, project_context):
        provider = MockProvider(sample_llm_response)
        agent = TranscriptAgent(provider)

        await agent.analyze_transcript(
            transcript_text="Sample transcript",
            project_context=project_context,
        )

        assert len(provider.generate_calls) == 1
        call = provider.generate_calls[0]
        assert "PROG-256" in call["user_prompt"]
        assert "HOP Drop 2" in call["user_prompt"]
        assert "RISK-100" in call["user_prompt"]
        assert call["response_schema"] is not None

    async def test_analyze_retries_on_invalid_json(self, project_context):
        """Agent should retry once if first response is invalid JSON."""
        call_count = 0

        class RetryProvider:
            async def generate(self, system_prompt, user_prompt, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return "not valid json"
                return json.dumps({
                    "meeting_summary": "Retry succeeded.",
                    "suggestions": [],
                })

            async def close(self):
                pass

        agent = TranscriptAgent(RetryProvider())
        result = await agent.analyze_transcript("text", project_context)

        assert call_count == 2
        assert result["meeting_summary"] == "Retry succeeded."
