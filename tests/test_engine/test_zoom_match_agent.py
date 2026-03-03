"""Tests for ZoomMatchAgent — response parsing."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from src.engine.agent import ZoomMatchAgent


@pytest.fixture()
def mock_provider() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def agent(mock_provider: AsyncMock) -> ZoomMatchAgent:
    return ZoomMatchAgent(mock_provider)


@pytest.mark.asyncio
async def test_classify_meeting_parses_response(agent: ZoomMatchAgent, mock_provider: AsyncMock) -> None:
    """classify_meeting returns parsed JSON with matches."""
    mock_provider.generate = AsyncMock(return_value=json.dumps({
        "matches": [
            {"project_id": 1, "confidence": 0.95, "reasoning": "Topic mentions HOP Drop 4"},
            {"project_id": 3, "confidence": 0.75, "reasoning": "AIM team key in transcript"},
        ]
    }))

    result = await agent.classify_meeting(
        topic="HOP Drop 4 Sprint Review",
        host_email="pm@company.com",
        transcript_excerpt="We discussed the AIM integration...",
        active_projects=[
            {"id": 1, "name": "HOP Drop 4", "team_keys": ["AIM"], "aliases": []},
            {"id": 2, "name": "Other Project", "team_keys": ["YAM"], "aliases": []},
            {"id": 3, "name": "AIM Standalone", "team_keys": ["AIM"], "aliases": []},
        ],
    )

    assert len(result["matches"]) == 2
    assert result["matches"][0]["project_id"] == 1
    assert result["matches"][0]["confidence"] == 0.95


@pytest.mark.asyncio
async def test_classify_meeting_empty_matches(agent: ZoomMatchAgent, mock_provider: AsyncMock) -> None:
    """General meetings return empty matches."""
    mock_provider.generate = AsyncMock(return_value=json.dumps({"matches": []}))

    result = await agent.classify_meeting(
        topic="Company All-Hands",
        host_email="ceo@company.com",
        transcript_excerpt="Today we celebrate...",
        active_projects=[
            {"id": 1, "name": "HOP Drop 4", "team_keys": [], "aliases": []},
        ],
    )

    assert result["matches"] == []


@pytest.mark.asyncio
async def test_classify_retries_on_invalid_json(agent: ZoomMatchAgent, mock_provider: AsyncMock) -> None:
    """Agent retries once on invalid JSON."""
    mock_provider.generate = AsyncMock(side_effect=[
        "Not valid JSON at all",
        json.dumps({"matches": [{"project_id": 1, "confidence": 0.8, "reasoning": "retry worked"}]}),
    ])

    result = await agent.classify_meeting(
        topic="Test", host_email="", transcript_excerpt="",
        active_projects=[{"id": 1, "name": "Test", "team_keys": [], "aliases": []}],
    )

    assert len(result["matches"]) == 1
    assert mock_provider.generate.call_count == 2
