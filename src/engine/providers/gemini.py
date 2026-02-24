"""Gemini LLM provider — calls the Google Generative Language API via httpx."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class GeminiProvider:
    """Provider for Google Gemini models via REST API (no SDK dependency)."""

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash") -> None:
        self._api_key = api_key
        self._model = model
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=120.0, verify=False)
        return self._client

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        response_schema: dict[str, Any] | None = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> str:
        """Send a prompt to Gemini and return the text response.

        If response_schema is provided, uses Gemini's structured output
        (responseMimeType: application/json + responseSchema).
        """
        client = await self._get_client()

        contents = [
            {"role": "user", "parts": [{"text": user_prompt}]},
        ]

        generation_config: dict[str, Any] = {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        }

        if response_schema:
            generation_config["responseMimeType"] = "application/json"
            generation_config["responseSchema"] = response_schema

        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": generation_config,
        }

        if system_prompt:
            body["systemInstruction"] = {
                "parts": [{"text": system_prompt}]
            }

        url = f"{_BASE_URL}/models/{self._model}:generateContent?key={self._api_key}"
        response = await client.post(url, json=body)

        if response.status_code != 200:
            error_text = response.text[:500]
            logger.error("Gemini API error %d: %s", response.status_code, error_text)
            raise RuntimeError(f"Gemini API error {response.status_code}: {error_text}")

        data = response.json()

        # Extract text from the response
        try:
            candidates = data["candidates"]
            finish_reason = candidates[0].get("finishReason", "UNKNOWN")
            if finish_reason not in ("STOP", "UNKNOWN"):
                logger.warning("Gemini finishReason: %s", finish_reason)
            parts = candidates[0]["content"]["parts"]
            text = parts[0]["text"]
        except (KeyError, IndexError) as exc:
            logger.error("Unexpected Gemini response structure: %s", data)
            raise RuntimeError(f"Failed to parse Gemini response: {exc}") from exc

        return text

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
