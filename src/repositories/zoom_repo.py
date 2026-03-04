"""Repository for zoom_recordings, project_meeting_map, and project_aliases tables."""

from __future__ import annotations

import json
import logging
from typing import Any

import src.config
from src.database import get_db
from src.models.zoom import ProjectMeetingMap, ZoomRecording

logger = logging.getLogger(__name__)


class ZoomRepository:
    """CRUD operations for Zoom recordings, project mappings, and aliases."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or src.config.settings.db_path

    # ------------------------------------------------------------------
    # zoom_recordings
    # ------------------------------------------------------------------

    def insert_recording(
        self,
        zoom_meeting_uuid: str,
        zoom_meeting_id: str,
        topic: str,
        host_email: str,
        start_time: str,
        duration_minutes: int,
        transcript_url: str,
        raw_metadata: dict[str, Any],
    ) -> int:
        with get_db(self._db_path) as conn:
            cursor = conn.execute(
                """INSERT INTO zoom_recordings
                   (zoom_meeting_uuid, zoom_meeting_id, topic, host_email,
                    start_time, duration_minutes, transcript_url, raw_metadata)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    zoom_meeting_uuid, zoom_meeting_id, topic, host_email,
                    start_time, duration_minutes, transcript_url,
                    json.dumps(raw_metadata),
                ),
            )
            conn.commit()
            return cursor.lastrowid

    def get_by_uuid(self, zoom_meeting_uuid: str) -> ZoomRecording | None:
        with get_db(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM zoom_recordings WHERE zoom_meeting_uuid = ?",
                (zoom_meeting_uuid,),
            ).fetchone()
        return ZoomRecording.from_row(row) if row else None

    def get_by_id(self, recording_id: int) -> ZoomRecording | None:
        with get_db(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM zoom_recordings WHERE id = ?",
                (recording_id,),
            ).fetchone()
        if not row:
            logger.debug("Zoom recording id=%s not found", recording_id)
        return ZoomRecording.from_row(row) if row else None

    def list_all(self) -> list[ZoomRecording]:
        with get_db(self._db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM zoom_recordings ORDER BY start_time DESC",
            ).fetchall()
        return [ZoomRecording.from_row(r) for r in rows]

    def list_by_status(self, status: str) -> list[ZoomRecording]:
        with get_db(self._db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM zoom_recordings WHERE processing_status = ? ORDER BY start_time DESC",
                (status,),
            ).fetchall()
        return [ZoomRecording.from_row(r) for r in rows]

    _SENTINEL = object()

    def update_status(
        self,
        recording_id: int,
        status: str,
        *,
        match_method: str | None | object = _SENTINEL,
        error_message: str | None | object = _SENTINEL,
    ) -> None:
        parts = ["processing_status = ?"]
        params: list = [status]
        if match_method is not self._SENTINEL:
            parts.append("match_method = ?")
            params.append(match_method)
        if error_message is not self._SENTINEL:
            parts.append("error_message = ?")
            params.append(error_message)
        params.append(recording_id)
        with get_db(self._db_path) as conn:
            conn.execute(
                f"UPDATE zoom_recordings SET {', '.join(parts)} WHERE id = ?",
                params,
            )
            conn.commit()

    def dismiss_recording(self, recording_id: int) -> None:
        logger.info("Dismissing Zoom recording id=%s", recording_id)
        self.update_status(recording_id, "dismissed")

    # ------------------------------------------------------------------
    # project_meeting_map
    # ------------------------------------------------------------------

    def add_project_mapping(
        self,
        zoom_recording_id: int,
        project_id: int,
        transcript_id: int | None = None,
    ) -> int:
        with get_db(self._db_path) as conn:
            cursor = conn.execute(
                """INSERT OR IGNORE INTO project_meeting_map
                   (zoom_recording_id, project_id, transcript_id)
                   VALUES (?, ?, ?)""",
                (zoom_recording_id, project_id, transcript_id),
            )
            conn.commit()
            return cursor.lastrowid

    def update_mapping_transcript(
        self, zoom_recording_id: int, project_id: int, transcript_id: int,
    ) -> None:
        with get_db(self._db_path) as conn:
            conn.execute(
                """UPDATE project_meeting_map
                   SET transcript_id = ?, analysis_status = 'complete'
                   WHERE zoom_recording_id = ? AND project_id = ?""",
                (transcript_id, zoom_recording_id, project_id),
            )
            conn.commit()

    def update_mapping_status(
        self, zoom_recording_id: int, project_id: int, status: str,
    ) -> None:
        with get_db(self._db_path) as conn:
            conn.execute(
                """UPDATE project_meeting_map
                   SET analysis_status = ?
                   WHERE zoom_recording_id = ? AND project_id = ?""",
                (status, zoom_recording_id, project_id),
            )
            conn.commit()

    def get_mappings_for_recording(self, zoom_recording_id: int) -> list[ProjectMeetingMap]:
        with get_db(self._db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM project_meeting_map WHERE zoom_recording_id = ?",
                (zoom_recording_id,),
            ).fetchall()
        return [ProjectMeetingMap.from_row(r) for r in rows]

    def get_project_ids_for_recording(self, zoom_recording_id: int) -> list[int]:
        with get_db(self._db_path) as conn:
            rows = conn.execute(
                "SELECT project_id FROM project_meeting_map WHERE zoom_recording_id = ?",
                (zoom_recording_id,),
            ).fetchall()
        return [r["project_id"] for r in rows]

    # ------------------------------------------------------------------
    # project_aliases
    # ------------------------------------------------------------------

    def get_aliases(self, project_id: int) -> list[str]:
        with get_db(self._db_path) as conn:
            rows = conn.execute(
                "SELECT alias FROM project_aliases WHERE project_id = ?",
                (project_id,),
            ).fetchall()
        return [r["alias"] for r in rows]

    def set_aliases(self, project_id: int, aliases: list[str]) -> None:
        with get_db(self._db_path) as conn:
            conn.execute("DELETE FROM project_aliases WHERE project_id = ?", (project_id,))
            for alias in aliases:
                alias = alias.strip()
                if alias:
                    conn.execute(
                        "INSERT INTO project_aliases (project_id, alias) VALUES (?, ?)",
                        (project_id, alias),
                    )
            conn.commit()

    def get_all_aliases(self) -> dict[int, list[str]]:
        """Return {project_id: [alias, ...]} for all projects."""
        with get_db(self._db_path) as conn:
            rows = conn.execute("SELECT project_id, alias FROM project_aliases").fetchall()
        result: dict[int, list[str]] = {}
        for r in rows:
            result.setdefault(r["project_id"], []).append(r["alias"])
        return result

    # ------------------------------------------------------------------
    # Config table helpers
    # ------------------------------------------------------------------

    def get_config(self, key: str) -> str | None:
        with get_db(self._db_path) as conn:
            row = conn.execute(
                "SELECT value FROM config WHERE key = ?", (key,),
            ).fetchone()
        return row["value"] if row else None

    def set_config(self, key: str, value: str) -> None:
        with get_db(self._db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
                (key, value),
            )
            conn.commit()

    def delete_config(self, key: str) -> None:
        with get_db(self._db_path) as conn:
            conn.execute("DELETE FROM config WHERE key = ?", (key,))
            conn.commit()

    def get_last_sync_time(self) -> str | None:
        return self.get_config("zoom_last_sync")

    def set_last_sync_time(self, value: str) -> None:
        self.set_config("zoom_last_sync", value)
