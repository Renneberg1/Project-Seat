"""Claude LLM provider — calls the Anthropic Messages API via the official SDK."""

from __future__ import annotations

import json
import logging
from typing import Any

import anthropic
import httpx

logger = logging.getLogger(__name__)


class ClaudeProvider:
    """Provider for Anthropic Claude models via the official SDK.

    Uses tool_use for structured output when a response_schema is provided,
    guaranteeing schema-compliant JSON without fence-stripping or retries.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-20250514",
        *,
        verify_ssl: bool = True,
    ) -> None:
        self._model = model
        # Pass a custom httpx client when SSL verification is disabled
        # (e.g. corporate proxy with self-signed certs)
        http_client = httpx.AsyncClient(verify=verify_ssl, timeout=120.0) if not verify_ssl else None
        self._client = anthropic.AsyncAnthropic(api_key=api_key, http_client=http_client)

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        response_schema: dict[str, Any] | None = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> str:
        """Send a prompt to Claude and return the text response.

        If response_schema is provided, uses tool_use to enforce structured
        JSON output matching the schema.
        """
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": user_prompt}],
        }

        if system_prompt:
            kwargs["system"] = system_prompt

        if response_schema:
            kwargs["tools"] = [
                {
                    "name": "structured_output",
                    "description": "Return the structured analysis result.",
                    "input_schema": response_schema,
                }
            ]
            kwargs["tool_choice"] = {"type": "tool", "name": "structured_output"}

        try:
            response = await self._client.messages.create(**kwargs)
        except anthropic.APIStatusError as exc:
            logger.error("Claude API error %d: %s", exc.status_code, str(exc)[:500])
            raise RuntimeError(
                f"Claude API error {exc.status_code}: {str(exc)[:500]}"
            ) from exc

        # Log non-standard stop reasons
        if response.stop_reason not in ("end_turn", "tool_use"):
            logger.warning("Claude stop_reason: %s", response.stop_reason)

        if response_schema:
            # Extract the tool call input (guaranteed valid JSON by the API)
            for block in response.content:
                if block.type == "tool_use":
                    return json.dumps(block.input)
            raise RuntimeError(
                "Claude did not return a tool_use block despite tool_choice being forced"
            )

        # Plain text mode
        for block in response.content:
            if block.type == "text":
                return block.text

        raise RuntimeError("Claude response contained no text or tool_use blocks")

    async def close(self) -> None:
        await self._client.close()
