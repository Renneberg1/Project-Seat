"""Dashboard service — aggregates live Jira data for tracked projects."""

from __future__ import annotations

import asyncio
import logging

from src.config import Settings, settings as default_settings
from src.connectors.base import ConnectorError
from src.connectors.jira import JiraConnector
from src.database import get_db
from src.models.dashboard import VALID_PHASES, ProjectSummary
from src.models.jira import JiraIssue
from src.models.project import Project

logger = logging.getLogger(__name__)


class DashboardService:
    """Fetch project data from local DB and enrich with live Jira metrics."""

    def __init__(
        self,
        db_path: str | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or default_settings
        self._db_path = db_path or self._settings.db_path

    # ------------------------------------------------------------------
    # Local DB queries
    # ------------------------------------------------------------------

    def list_projects(self) -> list[Project]:
        """Return all projects from the local database."""
        with get_db(self._db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM projects ORDER BY created_at DESC"
            ).fetchall()
        return [Project.from_row(r) for r in rows]

    def update_phase(self, project_id: int, phase: str) -> None:
        """Update the pipeline phase for a project."""
        if phase not in VALID_PHASES:
            raise ValueError(f"Invalid phase '{phase}'. Must be one of: {VALID_PHASES}")
        with get_db(self._db_path) as conn:
            conn.execute(
                "UPDATE projects SET phase = ? WHERE id = ?",
                (phase, project_id),
            )
            conn.commit()

    # ------------------------------------------------------------------
    # Live Jira enrichment
    # ------------------------------------------------------------------

    async def get_project_summary(self, project: Project) -> ProjectSummary:
        """Fetch live Jira data for a single project.

        Catches ConnectorError so a single project failure doesn't crash the dashboard.
        """
        jira = JiraConnector(settings=self._settings)
        try:
            goal_data, risks, decisions, initiatives = await asyncio.gather(
                jira.get_issue(project.jira_goal_key, fields=[
                    "summary", "status", "issuetype", "project", "labels",
                    "fixVersions", "duedate", "parent", "description",
                ]),
                jira.search(
                    f'project = RISK AND issuetype = Risk AND fixVersion = "{project.name}"',
                    fields=["status"],
                ),
                jira.search(
                    f'project = RISK AND issuetype = "Project Issue" AND fixVersion = "{project.name}"',
                    fields=["status"],
                ),
                jira.search(
                    f'issuetype = Initiative AND fixVersion = "{project.name}"',
                    fields=["status"],
                ),
            )

            goal = JiraIssue.from_api(goal_data)
            done_statuses = {"Done", "Closed"}
            open_risk_count = sum(
                1 for r in risks
                if r.get("fields", {}).get("status", {}).get("name") not in done_statuses
            )

            return ProjectSummary(
                project=project,
                goal=goal,
                risk_count=len(risks),
                open_risk_count=open_risk_count,
                decision_count=len(decisions),
                initiative_count=len(initiatives),
                error=None,
            )
        except ConnectorError as exc:
            logger.warning("Failed to fetch Jira data for %s: %s", project.name, exc)
            return ProjectSummary(
                project=project,
                goal=None,
                risk_count=0,
                open_risk_count=0,
                decision_count=0,
                initiative_count=0,
                error=str(exc),
            )
        finally:
            await jira.close()

    async def get_all_summaries(self) -> list[ProjectSummary]:
        """Fetch summaries for all projects in parallel."""
        projects = self.list_projects()
        if not projects:
            return []
        summaries = await asyncio.gather(
            *(self.get_project_summary(p) for p in projects)
        )
        return list(summaries)
