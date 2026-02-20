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
# Transcript Agent
# ------------------------------------------------------------------

class TranscriptAgent:
    """Analyzes meeting transcripts using the configured LLM provider."""

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

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

        # First attempt
        raw = await self._provider.generate(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_schema=TRANSCRIPT_ANALYSIS_SCHEMA,
            temperature=0.3,
            max_tokens=4096,
        )

        try:
            result = json.loads(raw)
            return result
        except json.JSONDecodeError:
            logger.warning("LLM returned invalid JSON, retrying with correction suffix")

        # Retry with correction hint
        correction = (
            "\n\nIMPORTANT: Your previous response was not valid JSON. "
            "Please respond with ONLY valid JSON matching the required schema. "
            "No markdown, no explanation — just the JSON object."
        )
        raw = await self._provider.generate(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt + correction,
            response_schema=TRANSCRIPT_ANALYSIS_SCHEMA,
            temperature=0.2,
            max_tokens=4096,
        )

        # Strip markdown fences if present
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]

        return json.loads(text)


# ------------------------------------------------------------------
# Charter Agent
# ------------------------------------------------------------------

class CharterAgent:
    """Two-step Charter update agent: ask questions, then propose edits."""

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

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
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Charter LLM returned invalid JSON, retrying")

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

        text = raw.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]

        return json.loads(text)
