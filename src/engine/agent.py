"""LLM agent layer — provider-agnostic interface for all LLM interactions."""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol, runtime_checkable

from src.config import LLMSettings

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Provider protocol
# ------------------------------------------------------------------

@runtime_checkable
class LLMProvider(Protocol):
    """Protocol that all LLM providers must implement."""

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        response_schema: dict[str, Any] | None = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> str: ...

    async def close(self) -> None: ...


# ------------------------------------------------------------------
# Provider factory
# ------------------------------------------------------------------

def get_provider(settings: LLMSettings) -> LLMProvider:
    """Instantiate the configured LLM provider.

    Reads LLM_PROVIDER env to decide which backend to use:
    - "gemini" -> GeminiProvider (Google Generative Language API)
    - "ollama" -> OllamaProvider (local Ollama server)
    """
    import os

    provider = settings.provider.lower()

    if provider == "gemini":
        from src.engine.providers.gemini import GeminiProvider

        return GeminiProvider(
            api_key=settings.api_key,
            model=settings.model or "gemini-2.5-flash",
            verify_ssl=settings.verify_ssl,
        )

    elif provider == "ollama":
        from src.engine.providers.ollama import OllamaProvider

        base_url = os.getenv("LLM_BASE_URL", "http://localhost:11434")
        return OllamaProvider(
            base_url=base_url,
            model=settings.model or "llama3.3:70b",
        )

    else:
        raise ValueError(
            f"Unknown LLM provider: '{provider}'. "
            f"Set LLM_PROVIDER to 'gemini' or 'ollama'."
        )


# ------------------------------------------------------------------
# Base Agent — shared retry + fence-stripping logic
# ------------------------------------------------------------------

class BaseAgent:
    """Common base for all LLM agents.

    Provides ``_generate_with_retry`` (JSON parse with one retry) and
    ``_strip_fences`` (remove markdown code fences from LLM output).
    """

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    @staticmethod
    def _strip_fences(text: str) -> str:
        """Remove markdown code fences from LLM output."""
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        return text.strip()

    async def _generate_with_retry(
        self,
        system_prompt: str,
        user_prompt: str,
        schema: dict[str, Any],
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        """Generate and parse JSON, retrying once on parse failure."""
        raw = await self._provider.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_schema=schema,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        try:
            return json.loads(self._strip_fences(raw))
        except json.JSONDecodeError:
            logger.warning(
                "LLM returned invalid JSON (len=%d), retrying. Raw: %s",
                len(raw), raw[:500],
            )

        correction = (
            "\n\nIMPORTANT: Your previous response was not valid JSON. "
            "Please respond with ONLY valid JSON matching the required schema. "
            "No markdown, no explanation — just the JSON object."
        )
        raw = await self._provider.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt + correction,
            response_schema=schema,
            temperature=0.2,
            max_tokens=max_tokens,
        )

        return json.loads(self._strip_fences(raw))


# ------------------------------------------------------------------
# Transcript Agent
# ------------------------------------------------------------------

class TranscriptAgent(BaseAgent):
    """Analyzes meeting transcripts using the configured LLM provider."""

    async def analyze_transcript(
        self,
        transcript_text: str,
        project_context: dict[str, Any],
    ) -> dict[str, Any]:
        """Run transcript analysis and return structured suggestions.

        Args:
            transcript_text: The raw transcript text.
            project_context: Assembled context about the project
                (existing risks, decisions, Charter/XFT content).

        Returns:
            Parsed JSON with meeting_summary and suggestions list.
        """
        from src.engine.prompts.transcript import (
            SYSTEM_PROMPT,
            TRANSCRIPT_ANALYSIS_SCHEMA,
            build_user_prompt,
        )

        user_prompt = build_user_prompt(transcript_text, project_context)

        return await self._generate_with_retry(
            SYSTEM_PROMPT, user_prompt, TRANSCRIPT_ANALYSIS_SCHEMA,
            temperature=0.3, max_tokens=4096,
        )


# ------------------------------------------------------------------
# Charter Agent
# ------------------------------------------------------------------

class CharterAgent(BaseAgent):
    """Two-step Charter update agent: ask questions, then propose edits."""

    async def ask_questions(
        self,
        current_sections: list[dict[str, str]],
        user_input: str,
        project_context: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Step 1: Identify gaps in the user's description.

        Returns parsed JSON with a ``questions`` list.
        """
        from src.engine.prompts.charter import (
            QUESTIONS_SYSTEM_PROMPT,
            CHARTER_QUESTIONS_SCHEMA,
            build_questions_prompt,
        )

        user_prompt = build_questions_prompt(current_sections, user_input, project_context)
        return await self._generate_with_retry(
            QUESTIONS_SYSTEM_PROMPT, user_prompt, CHARTER_QUESTIONS_SCHEMA,
            max_tokens=2048,
        )

    async def propose_edits(
        self,
        current_sections: list[dict[str, str]],
        user_input: str,
        qa_pairs: list[dict[str, str]],
        project_context: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Step 2: Propose precise section edits.

        Returns parsed JSON with ``summary`` and ``section_edits`` list.
        """
        from src.engine.prompts.charter import (
            EDITS_SYSTEM_PROMPT,
            CHARTER_EDITS_SCHEMA,
            build_edits_prompt,
        )

        user_prompt = build_edits_prompt(
            current_sections, user_input, qa_pairs, project_context
        )
        return await self._generate_with_retry(
            EDITS_SYSTEM_PROMPT, user_prompt, CHARTER_EDITS_SCHEMA,
        )


# ------------------------------------------------------------------
# Health Review Agent
# ------------------------------------------------------------------

class HealthReviewAgent(BaseAgent):
    """Two-step Health Review agent: ask questions, then produce review."""

    async def ask_questions(
        self,
        project_context: dict[str, Any],
    ) -> dict[str, Any]:
        """Step 1: Identify what can't be determined from data alone.

        Returns parsed JSON with a ``questions`` list.
        """
        from src.engine.prompts.health_review import (
            QUESTIONS_SYSTEM_PROMPT,
            HEALTH_QUESTIONS_SCHEMA,
            build_questions_prompt,
        )

        user_prompt = build_questions_prompt(project_context)
        return await self._generate_with_retry(
            QUESTIONS_SYSTEM_PROMPT, user_prompt, HEALTH_QUESTIONS_SCHEMA,
            max_tokens=16384,
        )

    async def generate_review(
        self,
        project_context: dict[str, Any],
        qa_pairs: list[dict[str, str]],
    ) -> dict[str, Any]:
        """Step 2: Produce a structured health review.

        Returns parsed JSON with health_rating, top_concerns, etc.
        """
        from src.engine.prompts.health_review import (
            REVIEW_SYSTEM_PROMPT,
            HEALTH_REVIEW_SCHEMA,
            build_review_prompt,
        )

        user_prompt = build_review_prompt(project_context, qa_pairs)
        return await self._generate_with_retry(
            REVIEW_SYSTEM_PROMPT, user_prompt, HEALTH_REVIEW_SCHEMA,
        )


# ------------------------------------------------------------------
# CEO Review Agent
# ------------------------------------------------------------------

class CeoReviewAgent(BaseAgent):
    """Two-step CEO Review agent: ask questions, then produce update."""

    async def ask_questions(
        self,
        metrics: dict[str, Any],
        pm_notes: str,
    ) -> dict[str, Any]:
        """Step 1: Identify what can't be determined from data alone.

        Returns parsed JSON with a ``questions`` list.
        """
        from src.engine.prompts.ceo_review import (
            QUESTIONS_SYSTEM_PROMPT,
            CEO_QUESTIONS_SCHEMA,
            build_questions_prompt,
        )

        user_prompt = build_questions_prompt(metrics, pm_notes)
        return await self._generate_with_retry(
            QUESTIONS_SYSTEM_PROMPT, user_prompt, CEO_QUESTIONS_SCHEMA,
            max_tokens=16384,
        )

    async def generate_review(
        self,
        metrics: dict[str, Any],
        pm_notes: str,
        qa_pairs: list[dict[str, str]],
    ) -> dict[str, Any]:
        """Step 2: Produce a CEO-level status update.

        Returns parsed JSON with health_indicator, commentaries, etc.
        """
        from src.engine.prompts.ceo_review import (
            REVIEW_SYSTEM_PROMPT,
            CEO_REVIEW_SCHEMA,
            build_review_prompt,
        )

        user_prompt = build_review_prompt(metrics, pm_notes, qa_pairs)
        return await self._generate_with_retry(
            REVIEW_SYSTEM_PROMPT, user_prompt, CEO_REVIEW_SCHEMA,
        )


# ------------------------------------------------------------------
# Risk Refine Agent
# ------------------------------------------------------------------

class RiskRefineAgent(BaseAgent):
    """Iterative risk/decision refinement via Q&A loop."""

    async def refine(
        self,
        suggestion_type: str,
        current_draft: dict[str, str],
        existing_items: list[dict[str, str]],
        qa_history: list[dict[str, str]],
        round_number: int,
        max_rounds: int = 5,
    ) -> dict[str, Any]:
        """Evaluate the draft and either ask questions or mark satisfied.

        Returns parsed JSON with satisfied, quality_assessment, questions, refined_risk.
        """
        from src.engine.prompts.risk_refine import (
            SYSTEM_PROMPT,
            RISK_REFINE_SCHEMA,
            build_refine_prompt,
        )

        user_prompt = build_refine_prompt(
            suggestion_type=suggestion_type,
            current_draft=current_draft,
            existing_items=existing_items,
            qa_history=qa_history,
            round_number=round_number,
            max_rounds=max_rounds,
        )

        return await self._generate_with_retry(
            SYSTEM_PROMPT, user_prompt, RISK_REFINE_SCHEMA,
            temperature=0.3,
            max_tokens=4096,
        )


# ------------------------------------------------------------------
# Closure Agent
# ------------------------------------------------------------------

class ClosureAgent(BaseAgent):
    """Two-step Closure Report agent: ask questions, then produce report."""

    async def ask_questions(
        self,
        metrics: dict[str, Any],
        pm_notes: str,
    ) -> dict[str, Any]:
        """Step 1: Identify what can't be determined from data alone.

        Returns parsed JSON with a ``questions`` list.
        """
        from src.engine.prompts.closure import (
            QUESTIONS_SYSTEM_PROMPT,
            CLOSURE_QUESTIONS_SCHEMA,
            build_questions_prompt,
        )

        user_prompt = build_questions_prompt(metrics, pm_notes)
        return await self._generate_with_retry(
            QUESTIONS_SYSTEM_PROMPT, user_prompt, CLOSURE_QUESTIONS_SCHEMA,
            max_tokens=16384,
        )

    async def generate_report(
        self,
        metrics: dict[str, Any],
        pm_notes: str,
        qa_pairs: list[dict[str, str]],
    ) -> dict[str, Any]:
        """Step 2: Produce the closure report narrative sections.

        Returns parsed JSON with final_delivery_outcome, success_criteria_assessments,
        and lessons_learned.
        """
        from src.engine.prompts.closure import (
            REPORT_SYSTEM_PROMPT,
            CLOSURE_REPORT_SCHEMA,
            build_report_prompt,
        )

        user_prompt = build_report_prompt(metrics, pm_notes, qa_pairs)
        return await self._generate_with_retry(
            REPORT_SYSTEM_PROMPT, user_prompt, CLOSURE_REPORT_SCHEMA,
            max_tokens=16384,
        )
