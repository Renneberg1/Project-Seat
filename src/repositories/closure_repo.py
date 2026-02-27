"""Repository for the ``closure_reports`` table."""

from __future__ import annotations

import json
from typing import Any

import src.config
from src.database import get_db
from src.models.closure import ClosureReport, ClosureReportStatus


class ClosureReportRepository:
    """CRUD operations for closure reports."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or src.config.settings.db_path

    def insert(
        self, project_id: int, report_json: str, confluence_body: str, status: str,
    ) -> int:
        with get_db(self._db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO closure_reports (project_id, report_json, confluence_body, status) "
                "VALUES (?, ?, ?, ?)",
                (project_id, report_json, confluence_body, status),
            )
            conn.commit()
            return cursor.lastrowid

    def get_report(self, report_id: int) -> ClosureReport | None:
        with get_db(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM closure_reports WHERE id = ?",
                (report_id,),
            ).fetchone()
        return ClosureReport.from_row(row) if row else None

    def list_reports(self, project_id: int, limit: int = 10) -> list[ClosureReport]:
        with get_db(self._db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM closure_reports WHERE project_id = ? ORDER BY id DESC LIMIT ?",
                (project_id, limit),
            ).fetchall()
        return [ClosureReport.from_row(r) for r in rows]

    def update_status(
        self, report_id: int, status: str, approval_item_id: int | None = None,
    ) -> None:
        with get_db(self._db_path) as conn:
            if approval_item_id is not None:
                conn.execute(
                    "UPDATE closure_reports SET status = ?, approval_item_id = ? WHERE id = ?",
                    (status, approval_item_id, report_id),
                )
            else:
                conn.execute(
                    "UPDATE closure_reports SET status = ? WHERE id = ?",
                    (status, report_id),
                )
            conn.commit()
