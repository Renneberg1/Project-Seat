"""Repository for action_items and knowledge_entries tables."""

from __future__ import annotations

import json
import logging
from typing import Any

import src.config
from src.database import get_db
from src.models.knowledge import ActionItem, KnowledgeEntry

logger = logging.getLogger(__name__)


class KnowledgeRepository:
    """CRUD operations for action items and knowledge entries."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or src.config.settings.db_path

    # ------------------------------------------------------------------
    # action_items
    # ------------------------------------------------------------------

    def insert_action_item(
        self,
        project_id: int,
        title: str,
        owner: str = "",
        due_date: str | None = None,
        source: str = "transcript",
        evidence: str = "",
        transcript_id: int | None = None,
    ) -> int:
        with get_db(self._db_path) as conn:
            cursor = conn.execute(
                """INSERT INTO action_items
                   (project_id, transcript_id, title, owner, due_date, source, evidence)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (project_id, transcript_id, title, owner, due_date, source, evidence),
            )
            conn.commit()
            return cursor.lastrowid

    def list_action_items(
        self, project_id: int, status: str | None = None,
    ) -> list[ActionItem]:
        with get_db(self._db_path) as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM action_items WHERE project_id = ? AND status = ? ORDER BY created_at DESC",
                    (project_id, status),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM action_items WHERE project_id = ? ORDER BY created_at DESC",
                    (project_id,),
                ).fetchall()
        return [ActionItem.from_row(r) for r in rows]

    def get_action_item(self, item_id: int) -> ActionItem | None:
        with get_db(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM action_items WHERE id = ?", (item_id,),
            ).fetchone()
        return ActionItem.from_row(row) if row else None

    def update_action_item_status(self, item_id: int, status: str) -> None:
        logger.info("Action item id=%s -> status=%s", item_id, status)
        with get_db(self._db_path) as conn:
            conn.execute(
                "UPDATE action_items SET status = ?, updated_at = datetime('now') WHERE id = ?",
                (status, item_id),
            )
            conn.commit()

    def count_action_items(self, project_id: int) -> dict[str, int]:
        with get_db(self._db_path) as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM action_items WHERE project_id = ?",
                (project_id,),
            ).fetchone()[0]
            open_count = conn.execute(
                "SELECT COUNT(*) FROM action_items WHERE project_id = ? AND status = 'open'",
                (project_id,),
            ).fetchone()[0]
        return {"total": total, "open": open_count}

    # ------------------------------------------------------------------
    # knowledge_entries
    # ------------------------------------------------------------------

    def insert_knowledge_entry(
        self,
        project_id: int,
        entry_type: str,
        title: str,
        content: str = "",
        tags: list[str] | None = None,
        source: str = "transcript",
        transcript_id: int | None = None,
    ) -> int:
        with get_db(self._db_path) as conn:
            cursor = conn.execute(
                """INSERT INTO knowledge_entries
                   (project_id, transcript_id, entry_type, title, content, tags, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (project_id, transcript_id, entry_type, title, content,
                 json.dumps(tags or []), source),
            )
            conn.commit()
            return cursor.lastrowid

    def list_knowledge_entries(
        self, project_id: int, entry_type: str | None = None,
    ) -> list[KnowledgeEntry]:
        with get_db(self._db_path) as conn:
            if entry_type:
                rows = conn.execute(
                    "SELECT * FROM knowledge_entries WHERE project_id = ? AND entry_type = ? ORDER BY created_at DESC",
                    (project_id, entry_type),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM knowledge_entries WHERE project_id = ? ORDER BY created_at DESC",
                    (project_id,),
                ).fetchall()
        return [KnowledgeEntry.from_row(r) for r in rows]

    def get_knowledge_entry(self, entry_id: int) -> KnowledgeEntry | None:
        with get_db(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM knowledge_entries WHERE id = ?", (entry_id,),
            ).fetchone()
        if not row:
            logger.debug("Knowledge entry id=%s not found", entry_id)
        return KnowledgeEntry.from_row(row) if row else None

    def update_published(self, entry_id: int, approval_item_id: int) -> None:
        with get_db(self._db_path) as conn:
            conn.execute(
                "UPDATE knowledge_entries SET published = 1, approval_item_id = ? WHERE id = ?",
                (approval_item_id, entry_id),
            )
            conn.commit()

    def search_knowledge(
        self, project_id: int, query: str,
    ) -> list[KnowledgeEntry]:
        """Search knowledge entries by title and content (LIKE-based)."""
        pattern = f"%{query}%"
        with get_db(self._db_path) as conn:
            rows = conn.execute(
                """SELECT * FROM knowledge_entries
                   WHERE project_id = ? AND (title LIKE ? OR content LIKE ?)
                   ORDER BY created_at DESC""",
                (project_id, pattern, pattern),
            ).fetchall()
        return [KnowledgeEntry.from_row(r) for r in rows]
