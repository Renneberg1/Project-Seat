"""Team progress snapshot service — stores daily SP totals for burnup charts."""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta

from src.config import settings as app_settings
from src.database import get_db
from src.models.project import Project
from src.services.team_progress import TeamVersionReport

logger = logging.getLogger(__name__)


class TeamSnapshotService:
    """Persist and retrieve daily team-progress snapshots."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or app_settings.db_path

    def save_snapshot(
        self,
        project: Project,
        reports: list[TeamVersionReport],
    ) -> None:
        """Save today's snapshot for a project. Idempotent (INSERT OR REPLACE)."""
        sp_total = sum(r.sp_total for r in reports)
        sp_done = sum(r.sp_done for r in reports)
        per_team = [
            {
                "team_key": r.team_key,
                "version_name": r.version_name,
                "sp_total": r.sp_total,
                "sp_done": r.sp_done,
            }
            for r in reports
        ]
        data = {"sp_total": sp_total, "sp_done": sp_done, "per_team": per_team}

        today = date.today().isoformat()
        with get_db(self._db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO team_progress_snapshots "
                "(project_id, snapshot_date, data_json) VALUES (?, ?, ?)",
                (project.id, today, json.dumps(data)),
            )
            conn.commit()

    def get_snapshots(
        self,
        project_id: int,
        days: int = 90,
    ) -> list[dict]:
        """Return [{date, sp_total, sp_done}] ordered by date, last N days."""
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


async def snapshot_all_projects() -> None:
    """Orchestrator task: snapshot team progress for all active projects with teams."""
    from src.services.dashboard import DashboardService
    from src.services.team_progress import TeamProgressService

    dashboard = DashboardService()
    team_svc = TeamProgressService()
    snap_svc = TeamSnapshotService()

    projects = dashboard.list_projects()
    for project in projects:
        if project.status != "active" or not project.team_projects:
            continue
        try:
            reports = await team_svc.get_team_reports(project)
            snap_svc.save_snapshot(project, reports)
            logger.info("Snapshot saved for project %s", project.name)
        except Exception:
            logger.exception("Failed to snapshot project %s", project.name)
