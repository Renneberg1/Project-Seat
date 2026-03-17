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
async def test_same_day_sync_still_fetches(service: ZoomIngestionService, repo: ZoomRepository) -> None:
    """When last sync is today, recordings should still be fetched (not skipped)."""
    from datetime import date

    repo.set_last_sync_time(date.today().isoformat())

    mock_meetings = [
        {
            "uuid": "uuid-same-day",
            "id": "333",
            "topic": "Same Day Meeting",
            "host_email": "host@test.com",
            "start_time": f"{date.today().isoformat()}T14:00:00Z",
            "duration": 30,
            "recording_files": [
                {"recording_type": "audio_transcript", "download_url": "https://zoom.us/dl/3"},
            ],
        }
    ]

    with patch("src.connectors.zoom.ZoomConnector") as MockZoom:
        zoom_instance = AsyncMock()
        MockZoom.return_value = zoom_instance
        zoom_instance.list_recordings = AsyncMock(return_value=mock_meetings)

        count = await service.fetch_new_recordings()

    assert count == 1
    rec = repo.get_by_uuid("uuid-same-day")
    assert rec is not None
    assert rec.topic == "Same Day Meeting"


@pytest.mark.asyncio
async def test_fetch_transcript_only_meetings(service: ZoomIngestionService, repo: ZoomRepository) -> None:
    """fetch_transcript_only_meetings discovers meetings with live transcripts but no recording."""
    past_meetings = [
        {
            "uuid": "uuid-transcript-1",
            "id": "500",
            "topic": "Transcript Only Meeting",
            "host_email": "host@test.com",
            "start_time": "2026-01-10T14:00:00Z",
            "duration": 60,
        },
        {
            "uuid": "uuid-no-transcript",
            "id": "501",
            "topic": "No Transcript Meeting",
            "host_email": "host@test.com",
            "start_time": "2026-01-10T15:00:00Z",
            "duration": 30,
        },
    ]

    # First meeting has a transcript, second does not
    async def mock_get_transcript(uuid):
        if uuid == "uuid-transcript-1":
            return {"download_url": "https://zoom.us/transcript/dl/t1"}
        return None

    with patch("src.connectors.zoom.ZoomConnector") as MockZoom:
        zoom_instance = AsyncMock()
        MockZoom.return_value = zoom_instance
        zoom_instance.list_past_meetings = AsyncMock(return_value=past_meetings)
        zoom_instance.get_meeting_transcript = AsyncMock(side_effect=mock_get_transcript)

        count = await service.fetch_transcript_only_meetings()

    assert count == 1
    rec = repo.get_by_uuid("uuid-transcript-1")
    assert rec is not None
    assert rec.topic == "Transcript Only Meeting"
    assert rec.discovery_source == "transcript"
    assert rec.transcript_url == "https://zoom.us/transcript/dl/t1"

    # Meeting without transcript should not be inserted
    assert repo.get_by_uuid("uuid-no-transcript") is None


@pytest.mark.asyncio
async def test_fetch_transcript_only_skips_known(service: ZoomIngestionService, repo: ZoomRepository) -> None:
    """fetch_transcript_only_meetings skips meetings already known from recordings sync."""
    # Pre-insert a recording (from the recordings API)
    repo.insert_recording(
        zoom_meeting_uuid="uuid-already-known", zoom_meeting_id="600",
        topic="Already Known", host_email="", start_time="2026-01-01T00:00:00Z",
        duration_minutes=30, transcript_url="https://zoom.us/dl/old", raw_metadata={},
    )

    past_meetings = [
        {
            "uuid": "uuid-already-known",
            "id": "600",
            "topic": "Already Known",
            "host_email": "",
            "start_time": "2026-01-01T00:00:00Z",
            "duration": 30,
        },
    ]

    with patch("src.connectors.zoom.ZoomConnector") as MockZoom:
        zoom_instance = AsyncMock()
        MockZoom.return_value = zoom_instance
        zoom_instance.list_past_meetings = AsyncMock(return_value=past_meetings)
        zoom_instance.get_meeting_transcript = AsyncMock()

        count = await service.fetch_transcript_only_meetings()

    assert count == 0
    # get_meeting_transcript should never be called for known UUIDs
    zoom_instance.get_meeting_transcript.assert_not_awaited()


@pytest.mark.asyncio
async def test_full_sync_includes_transcript_only(service: ZoomIngestionService, repo: ZoomRepository) -> None:
    """run_full_sync calls both fetch_new_recordings and fetch_transcript_only_meetings."""
    with patch.object(service, "fetch_new_recordings", new_callable=AsyncMock, return_value=2) as mock_rec, \
         patch.object(service, "fetch_transcript_only_meetings", new_callable=AsyncMock, return_value=1) as mock_trans:
        # No new recordings to process
        repo_list = patch.object(repo, "list_by_status", return_value=[])
        with repo_list:
            stats = await service.run_full_sync()

    mock_rec.assert_awaited_once()
    mock_trans.assert_awaited_once()
    assert stats["fetched"] == 2
    assert stats["transcript_only"] == 1


@pytest.mark.asyncio
async def test_download_transcript_routes_by_source(service: ZoomIngestionService, repo: ZoomRepository) -> None:
    """download_transcript uses download_meeting_transcript for transcript-only recordings."""
    rec_id = repo.insert_recording(
        zoom_meeting_uuid="uuid-trans-dl", zoom_meeting_id="700",
        topic="Transcript DL", host_email="", start_time="2026-01-01T00:00:00Z",
        duration_minutes=30, transcript_url="https://zoom.us/transcript/dl/t700",
        raw_metadata={}, discovery_source="transcript",
    )

    vtt = b"WEBVTT\n\nHello"

    with patch("src.connectors.zoom.ZoomConnector") as MockZoom:
        zoom_instance = AsyncMock()
        MockZoom.return_value = zoom_instance
        zoom_instance.download_meeting_transcript = AsyncMock(return_value=vtt)
        zoom_instance.download_transcript = AsyncMock(return_value=b"wrong")

        result = await service.download_transcript(rec_id)

    assert result == vtt
    zoom_instance.download_meeting_transcript.assert_awaited_once()
    zoom_instance.download_transcript.assert_not_awaited()


@pytest.mark.asyncio
async def test_fetch_meeting_by_uuid_found(service: ZoomIngestionService, repo: ZoomRepository) -> None:
    """fetch_meeting_by_uuid inserts a transcript-only recording when transcript exists."""
    transcript_meta = {
        "download_url": "https://zoom.us/transcript/dl/manual",
        "meeting_topic": "Manual Lookup Meeting",
        "meeting_start_time": "2026-03-05T09:00:00Z",
    }

    with patch("src.connectors.zoom.ZoomConnector") as MockZoom:
        zoom_instance = AsyncMock()
        MockZoom.return_value = zoom_instance
        zoom_instance.get_meeting_transcript = AsyncMock(return_value=transcript_meta)

        rec_id = await service.fetch_meeting_by_uuid("manual-uuid-1")

    assert rec_id is not None
    rec = repo.get_by_id(rec_id)
    assert rec is not None
    assert rec.discovery_source == "transcript"
    assert rec.topic == "Manual Lookup Meeting"
    assert rec.transcript_url == "https://zoom.us/transcript/dl/manual"


@pytest.mark.asyncio
async def test_fetch_meeting_by_uuid_no_transcript(service: ZoomIngestionService, repo: ZoomRepository) -> None:
    """fetch_meeting_by_uuid returns None when meeting has no transcript."""
    with patch("src.connectors.zoom.ZoomConnector") as MockZoom:
        zoom_instance = AsyncMock()
        MockZoom.return_value = zoom_instance
        zoom_instance.get_meeting_transcript = AsyncMock(return_value=None)

        rec_id = await service.fetch_meeting_by_uuid("no-transcript-uuid")

    assert rec_id is None


@pytest.mark.asyncio
async def test_fetch_meeting_by_uuid_already_known(service: ZoomIngestionService, repo: ZoomRepository) -> None:
    """fetch_meeting_by_uuid returns existing ID for already-known UUID."""
    existing_id = repo.insert_recording(
        zoom_meeting_uuid="known-uuid", zoom_meeting_id="999",
        topic="Already Known", host_email="", start_time="2026-01-01T00:00:00Z",
        duration_minutes=30, transcript_url="https://zoom.us/dl/old", raw_metadata={},
    )

    # Should NOT call the API
    with patch("src.connectors.zoom.ZoomConnector") as MockZoom:
        zoom_instance = AsyncMock()
        MockZoom.return_value = zoom_instance

        rec_id = await service.fetch_meeting_by_uuid("known-uuid")

    assert rec_id == existing_id
    zoom_instance.get_meeting_transcript.assert_not_awaited()


@pytest.mark.asyncio
async def test_refresh_transcript_url_recording_source(service: ZoomIngestionService, repo: ZoomRepository) -> None:
    """refresh_transcript_url re-fetches recording metadata for recording-source meetings."""
    rec_id = repo.insert_recording(
        zoom_meeting_uuid="uuid-refresh-1", zoom_meeting_id="800",
        topic="Needs Refresh", host_email="", start_time="2026-01-01T00:00:00Z",
        duration_minutes=30, transcript_url="", raw_metadata={},
        discovery_source="recording",
    )

    recording_data = {
        "recording_files": [
            {"recording_type": "audio_transcript", "file_type": "TRANSCRIPT",
             "download_url": "https://zoom.us/dl/refreshed"},
        ],
    }

    with patch("src.connectors.zoom.ZoomConnector") as MockZoom:
        zoom_instance = AsyncMock()
        MockZoom.return_value = zoom_instance
        zoom_instance.get_meeting_recordings = AsyncMock(return_value=recording_data)

        result = await service.refresh_transcript_url(rec_id)

    assert result == "https://zoom.us/dl/refreshed"
    rec = repo.get_by_id(rec_id)
    assert rec.transcript_url == "https://zoom.us/dl/refreshed"


@pytest.mark.asyncio
async def test_refresh_transcript_url_transcript_source(service: ZoomIngestionService, repo: ZoomRepository) -> None:
    """refresh_transcript_url uses meeting transcript endpoint for transcript-source meetings."""
    rec_id = repo.insert_recording(
        zoom_meeting_uuid="uuid-refresh-2", zoom_meeting_id="801",
        topic="Transcript Refresh", host_email="", start_time="2026-01-01T00:00:00Z",
        duration_minutes=30, transcript_url="", raw_metadata={},
        discovery_source="transcript",
    )

    with patch("src.connectors.zoom.ZoomConnector") as MockZoom:
        zoom_instance = AsyncMock()
        MockZoom.return_value = zoom_instance
        zoom_instance.get_meeting_transcript = AsyncMock(
            return_value={"download_url": "https://zoom.us/transcript/refreshed"},
        )

        result = await service.refresh_transcript_url(rec_id)

    assert result == "https://zoom.us/transcript/refreshed"
    rec = repo.get_by_id(rec_id)
    assert rec.transcript_url == "https://zoom.us/transcript/refreshed"


@pytest.mark.asyncio
async def test_refresh_transcript_url_still_unavailable(service: ZoomIngestionService, repo: ZoomRepository) -> None:
    """refresh_transcript_url returns None when transcript is still not available."""
    rec_id = repo.insert_recording(
        zoom_meeting_uuid="uuid-refresh-3", zoom_meeting_id="802",
        topic="Still No Transcript", host_email="", start_time="2026-01-01T00:00:00Z",
        duration_minutes=30, transcript_url="", raw_metadata={},
        discovery_source="recording",
    )

    with patch("src.connectors.zoom.ZoomConnector") as MockZoom:
        zoom_instance = AsyncMock()
        MockZoom.return_value = zoom_instance
        zoom_instance.get_meeting_recordings = AsyncMock(return_value={"recording_files": []})

        result = await service.refresh_transcript_url(rec_id)

    assert result is None
    rec = repo.get_by_id(rec_id)
    assert rec.transcript_url == ""


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
