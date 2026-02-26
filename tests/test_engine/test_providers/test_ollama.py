"""Tests for the Ollama LLM provider."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.engine.providers.ollama import OllamaProvider


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


def _ok_response(text: str = "hello") -> httpx.Response:
    return _make_response(json_data={"response": text})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOllamaGenerate:
    @pytest.mark.asyncio
    async def test_successful_parse(self):
        provider = OllamaProvider()
        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _ok_response('{"result": "ok"}')
            result = await provider.generate("system", "user prompt")
            assert result == '{"result": "ok"}'
        await provider.close()

    @pytest.mark.asyncio
    async def test_api_error_raises_runtime_error(self):
        provider = OllamaProvider()
        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _make_response(status_code=500, text="Internal error")
            with pytest.raises(RuntimeError, match="Ollama API error 500"):
                await provider.generate("sys", "user")
        await provider.close()

    @pytest.mark.asyncio
    async def test_empty_response_raises(self):
        provider = OllamaProvider()
        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _make_response(json_data={"response": ""})
            with pytest.raises(RuntimeError, match="Empty response from Ollama"):
                await provider.generate("sys", "user")
        await provider.close()

    @pytest.mark.asyncio
    async def test_schema_sets_format_param(self):
        provider = OllamaProvider()
        schema = {"type": "object", "properties": {"x": {"type": "string"}}}
        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _ok_response('{"x": "val"}')
            await provider.generate("sys", "user", response_schema=schema)
            body = mock_post.call_args[1]["json"]
            assert body["format"] == schema
        await provider.close()

    @pytest.mark.asyncio
    async def test_system_prompt_in_body(self):
        provider = OllamaProvider()
        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _ok_response("ok")
            await provider.generate("my system prompt", "user")
            body = mock_post.call_args[1]["json"]
            assert body["system"] == "my system prompt"
        await provider.close()

    @pytest.mark.asyncio
    async def test_no_system_prompt_omitted(self):
        provider = OllamaProvider()
        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _ok_response("ok")
            await provider.generate("", "user")
            body = mock_post.call_args[1]["json"]
            assert "system" not in body
        await provider.close()

    @pytest.mark.asyncio
    async def test_client_reuse(self):
        provider = OllamaProvider()
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
        provider = OllamaProvider()
        with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _ok_response("ok")
            await provider.generate("sys", "user")
        assert provider._client is not None
        await provider.close()
        assert provider._client.is_closed
