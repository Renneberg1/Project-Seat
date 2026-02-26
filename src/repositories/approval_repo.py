"""Repository for the ``approval_queue`` and ``approval_log`` tables."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import src.config
from src.database import get_db
from src.models.approval import ApprovalAction, ApprovalItem, ApprovalStatus


class ApprovalRepository:
    """CRUD operations for approval queue and audit log."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or src.config.settings.db_path

    # ------------------------------------------------------------------
    # Queue — create
    # ------------------------------------------------------------------

    def propose(
        self,
        action_type: ApprovalAction,
        payload: dict,
        preview: str,
        context: str = "",
        project_id: int | None = None,
    ) -> int:
        """Add a proposed action to the approval queue. Returns the item ID."""
        with get_db(self._db_path) as conn:
            cursor = conn.execute(
                """INSERT INTO approval_queue
                   (project_id, action_type, payload, preview, context, status)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    project_id,
                    action_type.value,
                    json.dumps(payload),
                    preview,
                    context,
                    ApprovalStatus.PENDING.value,
                ),
            )
            conn.commit()
            return cursor.lastrowid

    # ------------------------------------------------------------------
    # Queue — read
    # ------------------------------------------------------------------

    def get(self, item_id: int) -> ApprovalItem | None:
        with get_db(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM approval_queue WHERE id = ?", (item_id,)
            ).fetchone()
        return ApprovalItem.from_row(row) if row else None

    def list_all(self, project_id: int | None = None) -> list[ApprovalItem]:
        with get_db(self._db_path) as conn:
            if project_id is not None:
                rows = conn.execute(
                    "SELECT * FROM approval_queue WHERE project_id = ? ORDER BY id",
                    (project_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM approval_queue ORDER BY id"
                ).fetchall()
        return [ApprovalItem.from_row(r) for r in rows]

    def list_by_status(
        self, status: ApprovalStatus, project_id: int | None = None,
    ) -> list[ApprovalItem]:
        with get_db(self._db_path) as conn:
            if project_id is not None:
                rows = conn.execute(
                    "SELECT * FROM approval_queue WHERE status = ? AND project_id = ? ORDER BY id",
                    (status.value, project_id),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM approval_queue WHERE status = ? ORDER BY id",
                    (status.value,),
                ).fetchall()
        return [ApprovalItem.from_row(r) for r in rows]

    # ------------------------------------------------------------------
    # Queue — update
    # ------------------------------------------------------------------

    def update_status(self, item_id: int, status: ApprovalStatus) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with get_db(self._db_path) as conn:
            conn.execute(
                "UPDATE approval_queue SET status = ?, resolved_at = ? WHERE id = ?",
                (status.value, now, item_id),
            )
            conn.commit()

    def mark_approved(self, item_id: int) -> None:
        with get_db(self._db_path) as conn:
            conn.execute(
                "UPDATE approval_queue SET status = ? WHERE id = ?",
                (ApprovalStatus.APPROVED.value, item_id),
            )
            conn.commit()

    def set_result(
        self, item_id: int, status: ApprovalStatus, result_json: str,
    ) -> None:
        resolved_at = datetime.now(timezone.utc).isoformat()
        with get_db(self._db_path) as conn:
            conn.execute(
                "UPDATE approval_queue SET status = ?, result = ?, resolved_at = ? WHERE id = ?",
                (status.value, result_json, resolved_at, item_id),
            )
            conn.commit()

    def reset_to_pending(self, item_id: int) -> None:
        with get_db(self._db_path) as conn:
            conn.execute(
                "UPDATE approval_queue SET status = ?, result = NULL, resolved_at = NULL WHERE id = ?",
                (ApprovalStatus.PENDING.value, item_id),
            )
            conn.commit()

    def update_payload(self, item_id: int, payload_json: str) -> None:
        with get_db(self._db_path) as conn:
            conn.execute(
                "UPDATE approval_queue SET payload = ? WHERE id = ?",
                (payload_json, item_id),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Audit log
    # ------------------------------------------------------------------

    def log_audit(self, item: ApprovalItem, result_json: str | None = None) -> None:
        """Write an entry to the immutable approval_log table."""
        with get_db(self._db_path) as conn:
            conn.execute(
                """INSERT INTO approval_log
                   (project_id, action_type, payload, approved_by, approved_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    item.project_id,
                    item.action_type.value,
                    item.payload,
                    "local_user",
                    item.resolved_at,
                    item.created_at,
                ),
            )
            conn.commit()

    def log_audit_raw(
        self,
        project_id: int | None,
        action_type: str,
        details: dict,
    ) -> None:
        """Write a raw audit entry (used by release service)."""
        now = datetime.now(timezone.utc).isoformat()
        with get_db(self._db_path) as conn:
            conn.execute(
                """INSERT INTO approval_log
                   (project_id, action_type, payload, approved_by, approved_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (project_id, action_type, json.dumps(details), "local_user", now, now),
            )
            conn.commit()
