"""Repository for the ``projects`` table."""

from __future__ import annotations

import json
from typing import Any

import src.config
from src.database import get_db
from src.models.project import Project


class ProjectRepository:
    """CRUD operations for the ``projects`` table."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or src.config.settings.db_path

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def list_all(self) -> list[Project]:
        with get_db(self._db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM projects ORDER BY created_at DESC"
            ).fetchall()
        return [Project.from_row(r) for r in rows]

    def get_by_id(self, project_id: int) -> Project | None:
        with get_db(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
        return Project.from_row(row) if row else None

    def get_by_goal_key(self, goal_key: str) -> Project | None:
        with get_db(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM projects WHERE jira_goal_key = ?", (goal_key,)
            ).fetchone()
        return Project.from_row(row) if row else None

    def exists_by_goal_key(self, goal_key: str) -> int | None:
        """Return the project ID if a row with this goal key exists, else None."""
        with get_db(self._db_path) as conn:
            row = conn.execute(
                "SELECT id FROM projects WHERE jira_goal_key = ?", (goal_key,)
            ).fetchone()
        return row["id"] if row else None

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------

    def create(self, **fields: Any) -> int:
        """Insert a new project row. Returns the new project ID.

        Accepts keyword arguments matching column names.
        ``team_projects`` is auto-serialised to JSON if passed as a list.
        """
        if "team_projects" in fields and isinstance(fields["team_projects"], list):
            fields["team_projects"] = json.dumps(fields["team_projects"])
        columns = ", ".join(fields.keys())
        placeholders = ", ".join("?" for _ in fields)
        values = tuple(fields.values())
        with get_db(self._db_path) as conn:
            cursor = conn.execute(
                f"INSERT INTO projects ({columns}) VALUES ({placeholders})", values,
            )
            conn.commit()
            return cursor.lastrowid

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update(self, project_id: int, **fields: Any) -> None:
        """Update one or more columns on a project row.

        ``team_projects`` is auto-serialised to JSON if passed as a list.
        """
        if not fields:
            return
        if "team_projects" in fields and isinstance(fields["team_projects"], list):
            fields["team_projects"] = json.dumps(fields["team_projects"])
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = tuple(fields.values()) + (project_id,)
        with get_db(self._db_path) as conn:
            conn.execute(
                f"UPDATE projects SET {set_clause} WHERE id = ?", values,
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete(self, project_id: int) -> None:
        with get_db(self._db_path) as conn:
            conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            conn.commit()
