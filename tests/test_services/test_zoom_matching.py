"""Tests for ZoomMatchingService — title matching, fuzzy matching, LLM fallback."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from src.config import Settings, AtlassianSettings, LLMSettings, ZoomSettings
from src.database import init_db
from src.models.zoom import ZoomRecording
from src.repositories.zoom_repo import ZoomRepository
from src.services.zoom_matching import ZoomMatchingService


@pytest.fixture()
def db_path(tmp_path: Path) -> str:
    path = str(tmp_path / "test.db")
    init_db(path)
    return path


@pytest.fixture()
def repo(db_path: str) -> ZoomRepository:
    return ZoomRepository(db_path)


@pytest.fixture()
def test_settings() -> Settings:
    return Settings(
        atlassian=AtlassianSettings(domain="test", email="test@test.com", api_token="fake"),
        llm=LLMSettings(),
        zoom=ZoomSettings(enabled=True),
        db_path=":memory:",
    )


@pytest.fixture()
def service(db_path: str, test_settings: Settings, repo: ZoomRepository) -> ZoomMatchingService:
    return ZoomMatchingService(db_path=db_path, settings=test_settings, zoom_repo=repo)


def _make_recording(**kwargs) -> ZoomRecording:
    defaults = dict(
        id=1, zoom_meeting_uuid="uuid-1", zoom_meeting_id="111",
        topic="Test Meeting", host_email="host@test.com",
        start_time="2026-01-01T10:00:00Z", duration_minutes=30,
        transcript_url="", processing_status="new",
        match_method=None, error_message=None,
        raw_metadata={}, discovery_source="recording",
        created_at="2026-01-01T10:00:00",
    )
    defaults.update(kwargs)
    return ZoomRecording(**defaults)


def _seed_project(db_path: str, name: str, team_keys: list[str] | None = None) -> int:
    """Insert a project and return its ID."""
    import json
    from src.database import get_db
    teams = json.dumps([[k, name] for k in (team_keys or [])])
    with get_db(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO projects (jira_goal_key, name, status, phase, team_projects) VALUES (?, ?, ?, ?, ?)",
            ("PROG-1", name, "active", "planning", teams),
        )
        conn.commit()
        return cursor.lastrowid


class TestTitleMatch:
    """Title-based matching tests."""

    def test_exact_name_match(self, service: ZoomMatchingService, db_path: str) -> None:
        pid = _seed_project(db_path, "HOP Drop 4")
        projects = service._load_active_projects()
        result = service._title_match("HOP Drop 4 Weekly Sync", projects)
        assert pid in result

    def test_team_key_match(self, service: ZoomMatchingService, db_path: str) -> None:
        pid = _seed_project(db_path, "HOP Drop 4", team_keys=["AIM", "CTCV"])
        projects = service._load_active_projects()
        result = service._title_match("AIM Sprint Review", projects)
        assert pid in result

    def test_alias_match(self, service: ZoomMatchingService, db_path: str, repo: ZoomRepository) -> None:
        pid = _seed_project(db_path, "Harrison Offload Platform Drop 4")
        repo.set_aliases(pid, ["HOP", "Drop 4"])
        projects = service._load_active_projects()
        result = service._title_match("HOP Technical Discussion", projects)
        assert pid in result

    def test_no_match(self, service: ZoomMatchingService, db_path: str) -> None:
        _seed_project(db_path, "HOP Drop 4")
        projects = service._load_active_projects()
        result = service._title_match("Company All-Hands", projects)
        assert result == []

    def test_multi_project_match(self, service: ZoomMatchingService, db_path: str) -> None:
        pid1 = _seed_project(db_path, "Project Alpha", team_keys=["AIM"])
        pid2 = _seed_project(db_path, "Project Beta", team_keys=["CTCV"])
        projects = service._load_active_projects()
        result = service._title_match("AIM and CTCV Cross-Team Sync", projects)
        assert pid1 in result
        assert pid2 in result

    def test_fuzzy_match(self, service: ZoomMatchingService, db_path: str) -> None:
        pid = _seed_project(db_path, "HOP Drop 4 Release")
        projects = service._load_active_projects()
        result = service._title_match("HOP Drop 4 Releases Planning", projects)
        assert pid in result


class TestLLMMatch:
    """LLM-based matching tests."""

    @pytest.mark.asyncio
    async def test_llm_fallback(self, service: ZoomMatchingService, db_path: str) -> None:
        pid = _seed_project(db_path, "HOP Drop 4")
        recording = _make_recording(topic="Obscure Meeting Title")

        with patch("src.engine.agent.get_provider") as mock_provider_fn:
            mock_provider = AsyncMock()
            mock_provider_fn.return_value = mock_provider
            mock_provider.generate = AsyncMock(return_value='{"matches": [{"project_id": ' + str(pid) + ', "confidence": 0.9, "reasoning": "test"}]}')

            result = await service.match_recording(recording, "some transcript excerpt")

        assert pid in result
        assert service.last_match_method == "llm"

    @pytest.mark.asyncio
    async def test_llm_low_confidence_rejected(self, service: ZoomMatchingService, db_path: str) -> None:
        pid = _seed_project(db_path, "HOP Drop 4")
        recording = _make_recording(topic="Random Meeting")

        with patch("src.engine.agent.get_provider") as mock_provider_fn:
            mock_provider = AsyncMock()
            mock_provider_fn.return_value = mock_provider
            mock_provider.generate = AsyncMock(return_value='{"matches": [{"project_id": ' + str(pid) + ', "confidence": 0.3, "reasoning": "not sure"}]}')

            result = await service.match_recording(recording, "some transcript")

        assert result == []
