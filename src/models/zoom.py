"""Zoom recording and project-meeting mapping models."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass
class ZoomRecording:
    id: int
    zoom_meeting_uuid: str
    zoom_meeting_id: str
    topic: str
    host_email: str
    start_time: str
    duration_minutes: int
    transcript_url: str
    processing_status: str
    match_method: str | None
    error_message: str | None
    raw_metadata: dict[str, Any]
    discovery_source: str
    created_at: str

    @classmethod
    def from_row(cls, row: Any) -> ZoomRecording:
        raw = row["raw_metadata"]
        metadata = json.loads(raw) if isinstance(raw, str) else raw
        return cls(
            id=row["id"],
            zoom_meeting_uuid=row["zoom_meeting_uuid"],
            zoom_meeting_id=row["zoom_meeting_id"],
            topic=row["topic"],
            host_email=row["host_email"],
            start_time=row["start_time"],
            duration_minutes=row["duration_minutes"],
            transcript_url=row["transcript_url"],
            processing_status=row["processing_status"],
            match_method=row["match_method"],
            error_message=row["error_message"],
            raw_metadata=metadata,
            discovery_source=row["discovery_source"] if "discovery_source" in row.keys() else "recording",
            created_at=row["created_at"],
        )


@dataclass
class ProjectMeetingMap:
    id: int
    zoom_recording_id: int
    project_id: int
    transcript_id: int | None
    analysis_status: str
    created_at: str

    @classmethod
    def from_row(cls, row: Any) -> ProjectMeetingMap:
        return cls(
            id=row["id"],
            zoom_recording_id=row["zoom_recording_id"],
            project_id=row["project_id"],
            transcript_id=row["transcript_id"],
            analysis_status=row["analysis_status"],
            created_at=row["created_at"],
        )
