"""Team progress snapshot service — stores daily SP totals for burnup charts."""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta

from src.config import settings as app_settings
from src.models.project import Project
from src.services.team_progress import TeamVersionReport

logger = logging.getLogger(__name__)


class TeamSnapshotService:
    """Persist and retrieve daily team-progress snapshots."""

    def __init__(
        self,
        db_path: str | None = None,
        snapshot_repo: "SnapshotRepository | None" = None,
    ) -> None:
        self._db_path = db_path or app_settings.db_path

        from src.repositories.snapshot_repo import SnapshotRepository
        self._repo = snapshot_repo or SnapshotRepository(self._db_path)

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
        self._repo.save(project.id, today, json.dumps(data))

    def get_snapshots(
        self,
        project_id: int,
        days: int = 90,
    ) -> list[dict]:
        """Return [{date, sp_total, sp_done}] ordered by date, last N days."""
        return self._repo.get_snapshots(project_id, days)


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
