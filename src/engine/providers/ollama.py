"""Ollama LLM provider — calls the local Ollama API via httpx."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class OllamaProvider:
    """Provider for local Ollama models via REST API."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3.3:70b",
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=600.0)  # Long timeout for local inference
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
        """Send a prompt to Ollama and return the text response.

        If response_schema is provided, uses Ollama's JSON format enforcement.
        """
        client = await self._get_client()

        body: dict[str, Any] = {
            "model": self._model,
            "prompt": user_prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        if system_prompt:
            body["system"] = system_prompt

        if response_schema:
            body["format"] = response_schema

        url = f"{self._base_url}/api/generate"
        response = await client.post(url, json=body)

        if response.status_code != 200:
            error_text = response.text[:500]
            logger.error("Ollama API error %d: %s", response.status_code, error_text)
            raise RuntimeError(f"Ollama API error {response.status_code}: {error_text}")

        data = response.json()
        text = data.get("response", "")

        if not text:
            logger.error("Empty response from Ollama: %s", data)
            raise RuntimeError("Empty response from Ollama")

        return text

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
