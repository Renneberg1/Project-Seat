"""Repository for the ``transcript_cache`` and ``transcript_suggestions`` tables."""

from __future__ import annotations

import json
from typing import Any

import src.config
from src.database import get_db
from src.models.transcript import (
    SuggestionStatus,
    TranscriptRecord,
    TranscriptSuggestion,
)


class TranscriptRepository:
    """CRUD operations for transcripts and their suggestions."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or src.config.settings.db_path

    # ------------------------------------------------------------------
    # transcript_cache
    # ------------------------------------------------------------------

    def insert_transcript(
        self, project_id: int, filename: str, raw_text: str, processed_json: str,
    ) -> int:
        with get_db(self._db_path) as conn:
            cursor = conn.execute(
                """INSERT INTO transcript_cache
                   (project_id, filename, raw_text, processed_json)
                   VALUES (?, ?, ?, ?)""",
                (project_id, filename, raw_text, processed_json),
            )
            conn.commit()
            return cursor.lastrowid

    def list_transcripts(self, project_id: int) -> list[TranscriptRecord]:
        with get_db(self._db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM transcript_cache WHERE project_id = ? ORDER BY created_at DESC",
                (project_id,),
            ).fetchall()
        return [TranscriptRecord.from_row(r) for r in rows]

    def get_transcript(self, transcript_id: int) -> TranscriptRecord | None:
        with get_db(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM transcript_cache WHERE id = ?",
                (transcript_id,),
            ).fetchone()
        return TranscriptRecord.from_row(row) if row else None

    def delete_transcript(self, transcript_id: int) -> None:
        with get_db(self._db_path) as conn:
            conn.execute(
                "DELETE FROM transcript_suggestions WHERE transcript_id = ?",
                (transcript_id,),
            )
            conn.execute(
                "DELETE FROM transcript_cache WHERE id = ?",
                (transcript_id,),
            )
            conn.commit()

    def update_meeting_summary(self, transcript_id: int, summary: str) -> None:
        with get_db(self._db_path) as conn:
            conn.execute(
                "UPDATE transcript_cache SET meeting_summary = ? WHERE id = ?",
                (summary, transcript_id),
            )
            conn.commit()

    def get_meeting_summaries(
        self, project_id: int, limit: int = 5, since: str | None = None,
    ) -> list[dict]:
        if since:
            sql = (
                "SELECT filename, meeting_summary, created_at FROM transcript_cache "
                "WHERE project_id = ? AND meeting_summary IS NOT NULL "
                "AND created_at >= ? ORDER BY created_at DESC LIMIT ?"
            )
            params: tuple = (project_id, since, limit)
        else:
            sql = (
                "SELECT filename, meeting_summary, created_at FROM transcript_cache "
                "WHERE project_id = ? AND meeting_summary IS NOT NULL "
                "ORDER BY created_at DESC LIMIT ?"
            )
            params = (project_id, limit)
        with get_db(self._db_path) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            {"filename": r["filename"], "summary": r["meeting_summary"], "created_at": r["created_at"]}
            for r in rows
        ]

    # ------------------------------------------------------------------
    # transcript_suggestions
    # ------------------------------------------------------------------

    def get_suggestion(self, suggestion_id: int) -> TranscriptSuggestion | None:
        with get_db(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM transcript_suggestions WHERE id = ?",
                (suggestion_id,),
            ).fetchone()
        return TranscriptSuggestion.from_row(row) if row else None

    def list_suggestions(self, transcript_id: int) -> list[TranscriptSuggestion]:
        with get_db(self._db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM transcript_suggestions WHERE transcript_id = ? ORDER BY id",
                (transcript_id,),
            ).fetchall()
        return [TranscriptSuggestion.from_row(r) for r in rows]

    def delete_suggestions(self, transcript_id: int) -> None:
        with get_db(self._db_path) as conn:
            conn.execute(
                "DELETE FROM transcript_suggestions WHERE transcript_id = ?",
                (transcript_id,),
            )
            conn.commit()

    def insert_suggestion(
        self,
        transcript_id: int,
        project_id: int,
        suggestion_type: str,
        title: str,
        detail: str,
        evidence: str,
        proposed_payload: str,
        proposed_action: str,
        proposed_preview: str,
        confidence: float,
        status: str,
    ) -> int:
        with get_db(self._db_path) as conn:
            cursor = conn.execute(
                """INSERT INTO transcript_suggestions
                   (transcript_id, project_id, suggestion_type, title, detail,
                    evidence, proposed_payload, proposed_action, proposed_preview,
                    confidence, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    transcript_id, project_id,
                    suggestion_type, title, detail,
                    evidence, proposed_payload, proposed_action, proposed_preview,
                    confidence, status,
                ),
            )
            conn.commit()
            return cursor.lastrowid

    def update_suggestion_status(
        self, suggestion_id: int, status: str, approval_item_id: int | None = None,
    ) -> None:
        with get_db(self._db_path) as conn:
            if approval_item_id is not None:
                conn.execute(
                    "UPDATE transcript_suggestions SET status = ?, approval_item_id = ? WHERE id = ?",
                    (status, approval_item_id, suggestion_id),
                )
            else:
                conn.execute(
                    "UPDATE transcript_suggestions SET status = ? WHERE id = ?",
                    (status, suggestion_id),
                )
            conn.commit()

    def update_suggestion_content(
        self,
        suggestion_id: int,
        title: str,
        detail: str,
        evidence: str,
        proposed_payload: str,
        proposed_preview: str,
        confidence: float,
    ) -> None:
        with get_db(self._db_path) as conn:
            conn.execute(
                """UPDATE transcript_suggestions
                   SET title = ?, detail = ?, evidence = ?,
                       proposed_payload = ?, proposed_preview = ?,
                       confidence = ?
                   WHERE id = ?""",
                (title, detail, evidence, proposed_payload, proposed_preview, confidence, suggestion_id),
            )
            conn.commit()

    def get_transcript_summary(self, project_id: int) -> dict[str, int]:
        with get_db(self._db_path) as conn:
            transcript_count = conn.execute(
                "SELECT COUNT(*) FROM transcript_cache WHERE project_id = ?",
                (project_id,),
            ).fetchone()[0]
            suggestion_count = conn.execute(
                "SELECT COUNT(*) FROM transcript_suggestions WHERE project_id = ?",
                (project_id,),
            ).fetchone()[0]
            pending_count = conn.execute(
                "SELECT COUNT(*) FROM transcript_suggestions WHERE project_id = ? AND status = ?",
                (project_id, SuggestionStatus.PENDING.value),
            ).fetchone()[0]
        return {
            "transcript_count": transcript_count,
            "suggestion_count": suggestion_count,
            "pending_count": pending_count,
        }
