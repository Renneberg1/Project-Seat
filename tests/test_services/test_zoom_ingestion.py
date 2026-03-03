"""Tests for ZoomIngestionService — polling logic, deduplication, status transitions."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import Settings, AtlassianSettings, LLMSettings, ZoomSettings
from src.database import init_db
from src.repositories.zoom_repo import ZoomRepository
from src.services.zoom_ingestion import ZoomIngestionService


@pytest.fixture()
def zoom_settings() -> ZoomSettings:
    return ZoomSettings(
        client_id="test-client",
        client_secret="test-secret",
        redirect_uri="http://localhost:8000/zoom/callback",
        user_id="me",
        enabled=True,
    )


@pytest.fixture()
def test_settings(zoom_settings: ZoomSettings) -> Settings:
    return Settings(
        atlassian=AtlassianSettings(
            domain="test", email="test@test.com", api_token="fake",
        ),
        llm=LLMSettings(),
        zoom=zoom_settings,
        db_path=":memory:",
    )


@pytest.fixture()
def db_path(tmp_path: Path) -> str:
    path = str(tmp_path / "test.db")
    init_db(path)
    return path


@pytest.fixture()
def repo(db_path: str) -> ZoomRepository:
    return ZoomRepository(db_path)


@pytest.fixture()
def service(db_path: str, test_settings: Settings, repo: ZoomRepository) -> ZoomIngestionService:
    return ZoomIngestionService(db_path=db_path, settings=test_settings, zoom_repo=repo)


def test_deduplication(repo: ZoomRepository) -> None:
    """Same UUID is not inserted twice."""
    repo.insert_recording(
        zoom_meeting_uuid="uuid-1",
        zoom_meeting_id="123",
        topic="Meeting 1",
        host_email="host@test.com",
        start_time="2026-01-01T10:00:00Z",
        duration_minutes=30,
        transcript_url="https://zoom.us/download/1",
        raw_metadata={"id": "123"},
    )

    existing = repo.get_by_uuid("uuid-1")
    assert existing is not None
    assert existing.topic == "Meeting 1"


def test_status_transitions(repo: ZoomRepository) -> None:
    """Recording status transitions correctly."""
    rec_id = repo.insert_recording(
        zoom_meeting_uuid="uuid-2",
        zoom_meeting_id="456",
        topic="Meeting 2",
        host_email="host@test.com",
        start_time="2026-01-01T10:00:00Z",
        duration_minutes=60,
        transcript_url="",
        raw_metadata={},
    )

    rec = repo.get_by_id(rec_id)
    assert rec.processing_status == "new"

    repo.update_status(rec_id, "downloaded")
    rec = repo.get_by_id(rec_id)
    assert rec.processing_status == "downloaded"

    repo.update_status(rec_id, "matched", match_method="title")
    rec = repo.get_by_id(rec_id)
    assert rec.processing_status == "matched"
    assert rec.match_method == "title"

    repo.update_status(rec_id, "failed", error_message="Network error")
    rec = repo.get_by_id(rec_id)
    assert rec.processing_status == "failed"
    assert rec.error_message == "Network error"


def test_list_by_status(repo: ZoomRepository) -> None:
    """list_by_status filters correctly."""
    repo.insert_recording(
        zoom_meeting_uuid="uuid-a", zoom_meeting_id="1", topic="A",
        host_email="", start_time="2026-01-01T00:00:00Z",
        duration_minutes=0, transcript_url="", raw_metadata={},
    )
    rec2 = repo.insert_recording(
        zoom_meeting_uuid="uuid-b", zoom_meeting_id="2", topic="B",
        host_email="", start_time="2026-01-02T00:00:00Z",
        duration_minutes=0, transcript_url="", raw_metadata={},
    )
    repo.update_status(rec2, "matched")

    new_recs = repo.list_by_status("new")
    matched_recs = repo.list_by_status("matched")

    assert len(new_recs) == 1
    assert len(matched_recs) == 1
    assert new_recs[0].topic == "A"
    assert matched_recs[0].topic == "B"


def test_project_mapping(repo: ZoomRepository) -> None:
    """Project meeting mappings work correctly."""
    # Need to create a project first
    from src.database import get_db
    with get_db(repo._db_path) as conn:
        conn.execute(
            "INSERT INTO projects (jira_goal_key, name, status, phase) VALUES (?, ?, ?, ?)",
            ("PROG-1", "Test", "active", "planning"),
        )
        conn.commit()

    rec_id = repo.insert_recording(
        zoom_meeting_uuid="uuid-map", zoom_meeting_id="99", topic="Map Test",
        host_email="", start_time="2026-01-01T00:00:00Z",
        duration_minutes=0, transcript_url="", raw_metadata={},
    )

    repo.add_project_mapping(rec_id, 1)
    pids = repo.get_project_ids_for_recording(rec_id)
    assert pids == [1]

    # Duplicate mapping is ignored (INSERT OR IGNORE)
    repo.add_project_mapping(rec_id, 1)
    pids = repo.get_project_ids_for_recording(rec_id)
    assert pids == [1]


def test_sync_timestamp(repo: ZoomRepository) -> None:
    """Last sync timestamp is stored and retrieved."""
    assert repo.get_last_sync_time() is None

    repo.set_last_sync_time("2026-01-15")
    assert repo.get_last_sync_time() == "2026-01-15"

    repo.set_last_sync_time("2026-01-20")
    assert repo.get_last_sync_time() == "2026-01-20"


def test_aliases(repo: ZoomRepository) -> None:
    """Project aliases CRUD."""
    from src.database import get_db
    with get_db(repo._db_path) as conn:
        conn.execute(
            "INSERT INTO projects (jira_goal_key, name, status, phase) VALUES (?, ?, ?, ?)",
            ("PROG-1", "Test", "active", "planning"),
        )
        conn.commit()

    assert repo.get_aliases(1) == []

    repo.set_aliases(1, ["HOP", "Handoffs", "Drop 4"])
    assert repo.get_aliases(1) == ["HOP", "Handoffs", "Drop 4"]

    repo.set_aliases(1, ["HOP Only"])
    assert repo.get_aliases(1) == ["HOP Only"]

    all_aliases = repo.get_all_aliases()
    assert all_aliases == {1: ["HOP Only"]}


@pytest.mark.asyncio
async def test_fetch_new_recordings(service: ZoomIngestionService, repo: ZoomRepository) -> None:
    """fetch_new_recordings creates recording rows from Zoom API data."""
    mock_meetings = [
        {
            "uuid": "uuid-fetch-1",
            "id": "111",
            "topic": "Fetch Test",
            "host_email": "host@test.com",
            "start_time": "2026-01-10T10:00:00Z",
            "duration": 45,
            "recording_files": [
                {"recording_type": "audio_transcript", "file_type": "TRANSCRIPT", "download_url": "https://zoom.us/dl/1"},
            ],
        }
    ]

    with patch("src.connectors.zoom.ZoomConnector") as MockZoom:
        zoom_instance = AsyncMock()
        MockZoom.return_value = zoom_instance
        zoom_instance.list_recordings = AsyncMock(return_value=mock_meetings)

        count = await service.fetch_new_recordings()

    assert count == 1
    rec = repo.get_by_uuid("uuid-fetch-1")
    assert rec is not None
    assert rec.topic == "Fetch Test"
    assert rec.transcript_url == "https://zoom.us/dl/1"


@pytest.mark.asyncio
async def test_fetch_skips_duplicates(service: ZoomIngestionService, repo: ZoomRepository) -> None:
    """fetch_new_recordings skips already-known UUIDs."""
    repo.insert_recording(
        zoom_meeting_uuid="uuid-dup", zoom_meeting_id="222", topic="Old",
        host_email="", start_time="2026-01-01T00:00:00Z",
        duration_minutes=10, transcript_url="", raw_metadata={},
    )

    mock_meetings = [
        {"uuid": "uuid-dup", "id": "222", "topic": "Old", "host_email": "",
         "start_time": "2026-01-01T00:00:00Z", "duration": 10, "recording_files": []},
    ]

    with patch("src.connectors.zoom.ZoomConnector") as MockZoom:
        zoom_instance = AsyncMock()
        MockZoom.return_value = zoom_instance
        zoom_instance.list_recordings = AsyncMock(return_value=mock_meetings)

        count = await service.fetch_new_recordings()

    assert count == 0
