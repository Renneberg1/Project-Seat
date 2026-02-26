"""Tests for the Gemini LLM provider."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.engine.providers.gemini import GeminiProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(
    status_code: int = 200,
    json_data: dict | None = None,
    text: str = "",
) -> httpx.Response:
    resp = httpx.Response(status_code=status_code)
    if json_data is not None:
        resp._content = httpx._content.json_dumps(json_data).encode()
    else:
        resp._content = text.encode()
    return resp


def _ok_response(text: str = "hello", finish_reason: str = "STOP") -> httpx.Response:
    return _make_response(json_data={
        "candidates": [{
            "finishReason": finish_reason,
            "content": {"parts": [{"text": text}]},
        }],
    })


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGeminiGenerate:
    @pytest.mark.asyncio
    async def test_successful_parse(self):
        provider = GeminiProvider(api_key="test-key", model="gemini-test")
        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _ok_response('{"result": "ok"}')
            result = await provider.generate("system", "user prompt")
            assert result == '{"result": "ok"}'
        await provider.close()

    @pytest.mark.asyncio
    async def test_api_error_raises_runtime_error(self):
        provider = GeminiProvider(api_key="test-key")
        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _make_response(status_code=429, text="Rate limited")
            with pytest.raises(RuntimeError, match="Gemini API error 429"):
                await provider.generate("sys", "user")
        await provider.close()

    @pytest.mark.asyncio
    async def test_finish_reason_warning_logged(self, caplog):
        provider = GeminiProvider(api_key="test-key")
        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _ok_response("truncated", finish_reason="MAX_TOKENS")
            with caplog.at_level(logging.WARNING):
                result = await provider.generate("sys", "user")
            assert result == "truncated"
            assert "MAX_TOKENS" in caplog.text
        await provider.close()

    @pytest.mark.asyncio
    async def test_empty_candidates_raises(self):
        provider = GeminiProvider(api_key="test-key")
        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _make_response(json_data={"candidates": []})
            with pytest.raises(RuntimeError, match="Failed to parse Gemini response"):
                await provider.generate("sys", "user")
        await provider.close()

    @pytest.mark.asyncio
    async def test_system_prompt_in_body(self):
        provider = GeminiProvider(api_key="test-key")
        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _ok_response("ok")
            await provider.generate("my system prompt", "user")
            body = mock_post.call_args[1]["json"]
            assert body["systemInstruction"]["parts"][0]["text"] == "my system prompt"
        await provider.close()

    @pytest.mark.asyncio
    async def test_no_system_prompt_omitted_from_body(self):
        provider = GeminiProvider(api_key="test-key")
        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _ok_response("ok")
            await provider.generate("", "user")
            body = mock_post.call_args[1]["json"]
            assert "systemInstruction" not in body
        await provider.close()

    @pytest.mark.asyncio
    async def test_schema_sets_response_mime_type(self):
        provider = GeminiProvider(api_key="test-key")
        schema = {"type": "object", "properties": {"x": {"type": "string"}}}
        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _ok_response('{"x": "val"}')
            await provider.generate("sys", "user", response_schema=schema)
            body = mock_post.call_args[1]["json"]
            gen_config = body["generationConfig"]
            assert gen_config["responseMimeType"] == "application/json"
            assert gen_config["responseSchema"] == schema
        await provider.close()

    @pytest.mark.asyncio
    async def test_client_reuse(self):
        provider = GeminiProvider(api_key="test-key")
        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _ok_response("a")
            await provider.generate("sys", "p1")
            client1 = provider._client
            mock_post.return_value = _ok_response("b")
            await provider.generate("sys", "p2")
            client2 = provider._client
            assert client1 is client2
        await provider.close()

    @pytest.mark.asyncio
    async def test_close(self):
        provider = GeminiProvider(api_key="test-key")
        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _ok_response("ok")
            await provider.generate("sys", "user")
        assert provider._client is not None
        await provider.close()
        assert provider._client.is_closed
