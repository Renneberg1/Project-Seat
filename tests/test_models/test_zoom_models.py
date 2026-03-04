"""Tests for Zoom recording and project-meeting mapping models."""

from __future__ import annotations

import json

from src.models.zoom import ProjectMeetingMap, ZoomRecording


# ---------------------------------------------------------------------------
# ZoomRecording: direct construction
# ---------------------------------------------------------------------------


def test_zoom_recording_construction():
    rec = ZoomRecording(
        id=1,
        zoom_meeting_uuid="abc-123",
        zoom_meeting_id="9876543210",
        topic="Sprint Planning",
        host_email="host@example.com",
        start_time="2026-03-01T09:00:00Z",
        duration_minutes=60,
        transcript_url="https://zoom.us/rec/download/abc",
        processing_status="matched",
        match_method="title",
        error_message=None,
        raw_metadata={"recording_id": "r1"},
        created_at="2026-03-01T10:00:00",
    )

    assert rec.id == 1
    assert rec.zoom_meeting_uuid == "abc-123"
    assert rec.zoom_meeting_id == "9876543210"
    assert rec.topic == "Sprint Planning"
    assert rec.host_email == "host@example.com"
    assert rec.duration_minutes == 60
    assert rec.processing_status == "matched"
    assert rec.match_method == "title"
    assert rec.error_message is None
    assert rec.raw_metadata == {"recording_id": "r1"}


def test_zoom_recording_with_error():
    rec = ZoomRecording(
        id=2,
        zoom_meeting_uuid="def-456",
        zoom_meeting_id="1234567890",
        topic="Retro",
        host_email="host@example.com",
        start_time="2026-03-02T14:00:00Z",
        duration_minutes=30,
        transcript_url="",
        processing_status="error",
        match_method=None,
        error_message="Transcript download failed",
        raw_metadata={},
        created_at="2026-03-02T15:00:00",
    )

    assert rec.processing_status == "error"
    assert rec.match_method is None
    assert rec.error_message == "Transcript download failed"


# ---------------------------------------------------------------------------
# ZoomRecording.from_row
# ---------------------------------------------------------------------------


def _make_zoom_row(
    *,
    id: int = 1,
    zoom_meeting_uuid: str = "uuid-abc",
    zoom_meeting_id: str = "111222333",
    topic: str = "Daily Standup",
    host_email: str = "host@example.com",
    start_time: str = "2026-03-01T08:00:00Z",
    duration_minutes: int = 15,
    transcript_url: str = "https://zoom.us/rec/download/xyz",
    processing_status: str = "pending",
    match_method: str | None = None,
    error_message: str | None = None,
    raw_metadata: str | dict = '{"key": "val"}',
    created_at: str = "2026-03-01T09:00:00",
) -> dict:
    return {
        "id": id,
        "zoom_meeting_uuid": zoom_meeting_uuid,
        "zoom_meeting_id": zoom_meeting_id,
        "topic": topic,
        "host_email": host_email,
        "start_time": start_time,
        "duration_minutes": duration_minutes,
        "transcript_url": transcript_url,
        "processing_status": processing_status,
        "match_method": match_method,
        "error_message": error_message,
        "raw_metadata": raw_metadata,
        "created_at": created_at,
    }


def test_zoom_recording_from_row_string_metadata():
    row = _make_zoom_row(raw_metadata='{"participants": 5}')
    rec = ZoomRecording.from_row(row)

    assert rec.raw_metadata == {"participants": 5}
    assert rec.topic == "Daily Standup"


def test_zoom_recording_from_row_dict_metadata():
    """When raw_metadata is already a dict (not a JSON string), it is used directly."""
    row = _make_zoom_row(raw_metadata={"already": "parsed"})
    rec = ZoomRecording.from_row(row)

    assert rec.raw_metadata == {"already": "parsed"}


def test_zoom_recording_from_row_nullable_fields():
    row = _make_zoom_row(match_method=None, error_message=None)
    rec = ZoomRecording.from_row(row)

    assert rec.match_method is None
    assert rec.error_message is None


# ---------------------------------------------------------------------------
# ProjectMeetingMap: direct construction
# ---------------------------------------------------------------------------


def test_project_meeting_map_construction():
    mapping = ProjectMeetingMap(
        id=1,
        zoom_recording_id=10,
        project_id=42,
        transcript_id=100,
        analysis_status="completed",
        created_at="2026-03-01T12:00:00",
    )

    assert mapping.id == 1
    assert mapping.zoom_recording_id == 10
    assert mapping.project_id == 42
    assert mapping.transcript_id == 100
    assert mapping.analysis_status == "completed"


def test_project_meeting_map_nullable_transcript():
    mapping = ProjectMeetingMap(
        id=2,
        zoom_recording_id=11,
        project_id=43,
        transcript_id=None,
        analysis_status="pending",
        created_at="2026-03-02T08:00:00",
    )

    assert mapping.transcript_id is None


# ---------------------------------------------------------------------------
# ProjectMeetingMap.from_row
# ---------------------------------------------------------------------------


def test_project_meeting_map_from_row():
    row = {
        "id": 5,
        "zoom_recording_id": 20,
        "project_id": 99,
        "transcript_id": 200,
        "analysis_status": "analysed",
        "created_at": "2026-03-03T10:00:00",
    }
    mapping = ProjectMeetingMap.from_row(row)

    assert mapping.id == 5
    assert mapping.zoom_recording_id == 20
    assert mapping.project_id == 99
    assert mapping.transcript_id == 200
    assert mapping.analysis_status == "analysed"
    assert mapping.created_at == "2026-03-03T10:00:00"
