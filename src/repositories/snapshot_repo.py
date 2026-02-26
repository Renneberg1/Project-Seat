"""Repository for the ``team_progress_snapshots`` table."""

from __future__ import annotations

import json
from datetime import date, timedelta

import src.config
from src.database import get_db


class SnapshotRepository:
    """CRUD operations for team progress snapshots."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or src.config.settings.db_path

    def save(self, project_id: int, snapshot_date: str, data_json: str) -> None:
        with get_db(self._db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO team_progress_snapshots "
                "(project_id, snapshot_date, data_json) VALUES (?, ?, ?)",
                (project_id, snapshot_date, data_json),
            )
            conn.commit()

    def get_snapshots(self, project_id: int, days: int = 90) -> list[dict]:
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        with get_db(self._db_path) as conn:
            rows = conn.execute(
                "SELECT snapshot_date, data_json FROM team_progress_snapshots "
                "WHERE project_id = ? AND snapshot_date >= ? "
                "ORDER BY snapshot_date",
                (project_id, cutoff),
            ).fetchall()
        result = []
        for row in rows:
            data = json.loads(row["data_json"])
            result.append({
                "date": row["snapshot_date"],
                "sp_total": data["sp_total"],
                "sp_done": data["sp_done"],
                "per_team": data.get("per_team", []),
            })
        return result
