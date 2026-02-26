"""Repository for the ``charter_suggestions`` table."""

from __future__ import annotations

import json

import src.config
from src.database import get_db
from src.models.charter import CharterSuggestion, CharterSuggestionStatus


class CharterRepository:
    """CRUD operations for charter suggestions."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or src.config.settings.db_path

    def insert_suggestion(
        self,
        project_id: int,
        section_name: str,
        current_text: str,
        proposed_text: str,
        rationale: str,
        confidence: float,
        proposed_payload: str,
        proposed_preview: str,
        analysis_summary: str,
        status: str,
    ) -> int:
        with get_db(self._db_path) as conn:
            cursor = conn.execute(
                """INSERT INTO charter_suggestions
                   (project_id, section_name, current_text, proposed_text,
                    rationale, confidence, proposed_payload, proposed_preview,
                    analysis_summary, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    project_id, section_name, current_text, proposed_text,
                    rationale, confidence, proposed_payload, proposed_preview,
                    analysis_summary, status,
                ),
            )
            conn.commit()
            return cursor.lastrowid

    def get_suggestion(self, suggestion_id: int) -> CharterSuggestion | None:
        with get_db(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM charter_suggestions WHERE id = ?",
                (suggestion_id,),
            ).fetchone()
        return CharterSuggestion.from_row(row) if row else None

    def list_suggestions(self, project_id: int) -> list[CharterSuggestion]:
        with get_db(self._db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM charter_suggestions WHERE project_id = ? ORDER BY id DESC",
                (project_id,),
            ).fetchall()
        return [CharterSuggestion.from_row(r) for r in rows]

    def update_status(
        self, suggestion_id: int, status: str, approval_item_id: int | None = None,
    ) -> None:
        with get_db(self._db_path) as conn:
            if approval_item_id is not None:
                conn.execute(
                    "UPDATE charter_suggestions SET status = ?, approval_item_id = ? WHERE id = ?",
                    (status, approval_item_id, suggestion_id),
                )
            else:
                conn.execute(
                    "UPDATE charter_suggestions SET status = ? WHERE id = ?",
                    (status, suggestion_id),
                )
            conn.commit()
