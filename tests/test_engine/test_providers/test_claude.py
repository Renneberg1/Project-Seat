"""Tests for the Claude (Anthropic) LLM provider."""

from __future__ import annotations

import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.engine.providers.claude import ClaudeProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_text_block(text: str) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = text
    return block


def _make_tool_use_block(input_data: dict) -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.input = input_data
    return block


def _make_response(
    content: list | None = None,
    stop_reason: str = "end_turn",
) -> MagicMock:
    resp = MagicMock()
    resp.content = content or []
    resp.stop_reason = stop_reason
    return resp


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestClaudeGenerate:
    @pytest.mark.asyncio
    async def test_successful_plain_text(self):
        provider = ClaudeProvider(api_key="test-key", model="claude-test")
        mock_create = AsyncMock(
            return_value=_make_response(
                content=[_make_text_block("hello world")],
            )
        )
        with patch.object(provider._client.messages, "create", mock_create):
            result = await provider.generate("system", "user prompt")
            assert result == "hello world"
        await provider.close()

    @pytest.mark.asyncio
    async def test_structured_output_via_tool_use(self):
        provider = ClaudeProvider(api_key="test-key")
        schema = {"type": "object", "properties": {"x": {"type": "string"}}}
        tool_data = {"x": "value"}
        mock_create = AsyncMock(
            return_value=_make_response(
                content=[_make_tool_use_block(tool_data)],
                stop_reason="tool_use",
            )
        )
        with patch.object(provider._client.messages, "create", mock_create):
            result = await provider.generate(
                "sys", "user", response_schema=schema
            )
            parsed = json.loads(result)
            assert parsed == {"x": "value"}

            # Verify tool was passed correctly
            call_kwargs = mock_create.call_args[1]
            assert len(call_kwargs["tools"]) == 1
            assert call_kwargs["tools"][0]["name"] == "structured_output"
            assert call_kwargs["tools"][0]["input_schema"] == schema
            assert call_kwargs["tool_choice"] == {
                "type": "tool",
                "name": "structured_output",
            }
        await provider.close()

    @pytest.mark.asyncio
    async def test_api_error_raises_runtime_error(self):
        import anthropic

        provider = ClaudeProvider(api_key="test-key")
        mock_create = AsyncMock(
            side_effect=anthropic.APIStatusError(
                message="Rate limited",
                response=MagicMock(status_code=429),
                body=None,
            )
        )
        with patch.object(provider._client.messages, "create", mock_create):
            with pytest.raises(RuntimeError, match="Claude API error 429"):
                await provider.generate("sys", "user")
        await provider.close()

    @pytest.mark.asyncio
    async def test_missing_tool_use_block_raises(self):
        provider = ClaudeProvider(api_key="test-key")
        schema = {"type": "object", "properties": {"x": {"type": "string"}}}
        # Return only a text block when schema was provided
        mock_create = AsyncMock(
            return_value=_make_response(
                content=[_make_text_block("oops no tool call")],
            )
        )
        with patch.object(provider._client.messages, "create", mock_create):
            with pytest.raises(RuntimeError, match="did not return a tool_use block"):
                await provider.generate("sys", "user", response_schema=schema)
        await provider.close()

    @pytest.mark.asyncio
    async def test_stop_reason_warning_logged(self, caplog):
        provider = ClaudeProvider(api_key="test-key")
        mock_create = AsyncMock(
            return_value=_make_response(
                content=[_make_text_block("truncated")],
                stop_reason="max_tokens",
            )
        )
        with patch.object(provider._client.messages, "create", mock_create):
            with caplog.at_level(logging.WARNING):
                result = await provider.generate("sys", "user")
            assert result == "truncated"
            assert "max_tokens" in caplog.text
        await provider.close()

    @pytest.mark.asyncio
    async def test_system_prompt_passed_when_provided(self):
        provider = ClaudeProvider(api_key="test-key")
        mock_create = AsyncMock(
            return_value=_make_response(content=[_make_text_block("ok")])
        )
        with patch.object(provider._client.messages, "create", mock_create):
            await provider.generate("my system prompt", "user")
            call_kwargs = mock_create.call_args[1]
            assert call_kwargs["system"] == "my system prompt"
        await provider.close()

    @pytest.mark.asyncio
    async def test_empty_system_prompt_omitted(self):
        provider = ClaudeProvider(api_key="test-key")
        mock_create = AsyncMock(
            return_value=_make_response(content=[_make_text_block("ok")])
        )
        with patch.object(provider._client.messages, "create", mock_create):
            await provider.generate("", "user")
            call_kwargs = mock_create.call_args[1]
            assert "system" not in call_kwargs
        await provider.close()

    @pytest.mark.asyncio
    async def test_temperature_and_max_tokens_passed(self):
        provider = ClaudeProvider(api_key="test-key")
        mock_create = AsyncMock(
            return_value=_make_response(content=[_make_text_block("ok")])
        )
        with patch.object(provider._client.messages, "create", mock_create):
            await provider.generate(
                "sys", "user", temperature=0.7, max_tokens=8192
            )
            call_kwargs = mock_create.call_args[1]
            assert call_kwargs["temperature"] == 0.7
            assert call_kwargs["max_tokens"] == 8192
        await provider.close()

    @pytest.mark.asyncio
    async def test_empty_response_raises(self):
        provider = ClaudeProvider(api_key="test-key")
        mock_create = AsyncMock(
            return_value=_make_response(content=[])
        )
        with patch.object(provider._client.messages, "create", mock_create):
            with pytest.raises(RuntimeError, match="no text or tool_use blocks"):
                await provider.generate("sys", "user")
        await provider.close()

    @pytest.mark.asyncio
    async def test_close(self):
        provider = ClaudeProvider(api_key="test-key")
        mock_close = AsyncMock()
        with patch.object(provider._client, "close", mock_close):
            await provider.close()
            mock_close.assert_called_once()
