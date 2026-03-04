"""Repository for the ``releases`` and ``release_documents`` tables."""

from __future__ import annotations

import json
import logging

import src.config
from src.database import get_db
from src.models.release import Release

logger = logging.getLogger(__name__)


class ReleaseRepository:
    """CRUD operations for releases and their documents."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or src.config.settings.db_path

    # ------------------------------------------------------------------
    # Releases
    # ------------------------------------------------------------------

    def create_release(self, project_id: int, name: str) -> Release:
        with get_db(self._db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO releases (project_id, name) VALUES (?, ?)",
                (project_id, name),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM releases WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return Release.from_row(row)

    def delete_release(self, release_id: int) -> None:
        logger.info("Deleting release id=%s and its documents", release_id)
        with get_db(self._db_path) as conn:
            conn.execute("DELETE FROM release_documents WHERE release_id = ?", (release_id,))
            conn.execute("DELETE FROM releases WHERE id = ?", (release_id,))
            conn.commit()

    def list_releases(self, project_id: int) -> list[Release]:
        with get_db(self._db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM releases WHERE project_id = ? ORDER BY created_at DESC",
                (project_id,),
            ).fetchall()
        return [Release.from_row(r) for r in rows]

    def get_release(self, release_id: int) -> Release | None:
        with get_db(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM releases WHERE id = ?", (release_id,)
            ).fetchone()
        return Release.from_row(row) if row else None

    def get_project_id(self, release_id: int) -> int | None:
        with get_db(self._db_path) as conn:
            row = conn.execute(
                "SELECT project_id FROM releases WHERE id = ?", (release_id,)
            ).fetchone()
        return row["project_id"] if row else None

    def lock_release(self, release_id: int, version_snapshot_json: str) -> None:
        logger.info("Locking release id=%s (scope-freeze)", release_id)
        with get_db(self._db_path) as conn:
            conn.execute(
                "UPDATE releases SET locked = 1, version_snapshot = ? WHERE id = ?",
                (version_snapshot_json, release_id),
            )
            conn.commit()

    def unlock_release(self, release_id: int) -> None:
        with get_db(self._db_path) as conn:
            conn.execute(
                "UPDATE releases SET locked = 0 WHERE id = ?",
                (release_id,),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Release documents
    # ------------------------------------------------------------------

    def save_documents(self, release_id: int, titles: set[str]) -> None:
        with get_db(self._db_path) as conn:
            conn.execute(
                "DELETE FROM release_documents WHERE release_id = ?", (release_id,)
            )
            for title in sorted(titles):
                conn.execute(
                    "INSERT INTO release_documents (release_id, doc_title) VALUES (?, ?)",
                    (release_id, title),
                )
            conn.commit()

    def get_selected_documents(self, release_id: int) -> set[str]:
        with get_db(self._db_path) as conn:
            rows = conn.execute(
                "SELECT doc_title FROM release_documents WHERE release_id = ?",
                (release_id,),
            ).fetchall()
        return {r["doc_title"] for r in rows}
