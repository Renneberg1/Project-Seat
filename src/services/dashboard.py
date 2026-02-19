"""Dashboard service — aggregates live Jira data for tracked projects."""

from __future__ import annotations

import asyncio
import logging

from src.config import Settings, settings as default_settings
from src.connectors.base import ConnectorError
from src.connectors.jira import JiraConnector
from src.database import get_db
from src.models.dashboard import (
    VALID_PHASES,
    EpicWithTasks,
    InitiativeDetail,
    InitiativeSummary,
    ProductIdeaSummary,
    ProjectSummary,
)
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

    def get_project_by_id(self, project_id: int) -> Project | None:
        """Return a single project by ID, or None if not found."""
        with get_db(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
        return Project.from_row(row) if row else None

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

    # ------------------------------------------------------------------
    # Product Ideas (PI board)
    # ------------------------------------------------------------------

    async def get_product_ideas(self, project: Project) -> list[JiraIssue]:
        """Fetch Product Ideas linked to this project via the PI version field.

        Excludes "Market Access" issue type.
        """
        if not project.pi_version:
            return []
        jira = JiraConnector(settings=self._settings)
        try:
            results = await jira.search(
                f'project = PI AND "versions[checkboxes]" = "{project.pi_version}"'
                f' AND issuetype != "Market Access"'
                f' AND statusCategory != Done'
                f' AND resolution = Unresolved',
                fields=["summary", "status", "issuetype", "project", "labels",
                        "fixVersions", "duedate", "parent", "description",
                        "customfield_12812", "customfield_11054", "customfield_13530"],
            )
            return [JiraIssue.from_api(r) for r in results]
        except ConnectorError:
            return []
        finally:
            await jira.close()

    def summarise_product_ideas(self, ideas: list[JiraIssue]) -> ProductIdeaSummary:
        """Compute summary counts from a list of Product Ideas."""
        done_statuses = {"Done", "Closed"}
        type_counts = {"Feature": 0, "Minor Feature": 0, "Idea": 0, "Defect": 0}
        done_count = 0
        must_have_count = 0
        for idea in ideas:
            type_counts[idea.issue_type] = type_counts.get(idea.issue_type, 0) + 1
            if idea.status in done_statuses:
                done_count += 1
            if idea.release_priority == "Must Have":
                must_have_count += 1
        return ProductIdeaSummary(
            total_count=len(ideas),
            open_count=len(ideas) - done_count,
            done_count=done_count,
            feature_count=type_counts.get("Feature", 0),
            minor_feature_count=type_counts.get("Minor Feature", 0),
            idea_count=type_counts.get("Idea", 0),
            defect_count=type_counts.get("Defect", 0),
            must_have_count=must_have_count,
        )

    # ------------------------------------------------------------------
    # Initiative / Feature drill-down
    # ------------------------------------------------------------------

    async def get_initiatives(self, project: Project) -> list[InitiativeSummary]:
        """Fetch Initiative tickets for a project with child Epic/Task counts."""
        jira = JiraConnector(settings=self._settings)
        try:
            initiatives = await jira.search(
                f'issuetype = Initiative AND fixVersion = "{project.name}"',
                fields=["summary", "status", "issuetype", "project", "labels",
                        "fixVersions", "duedate", "parent", "description"],
            )
            done_statuses = {"Done", "Closed"}
            results: list[InitiativeSummary] = []
            for raw in initiatives:
                issue = JiraIssue.from_api(raw)
                epics = await jira.search(
                    f'issuetype = Epic AND parent = {issue.key}',
                    fields=["status"],
                )
                task_count = 0
                done_task_count = 0
                done_epic_count = sum(
                    1 for e in epics
                    if e.get("fields", {}).get("status", {}).get("name") in done_statuses
                )
                for epic_raw in epics:
                    epic_key = epic_raw.get("key", "")
                    if not epic_key:
                        continue
                    tasks = await jira.search(
                        f'parent = {epic_key}',
                        fields=["status"],
                    )
                    task_count += len(tasks)
                    done_task_count += sum(
                        1 for t in tasks
                        if t.get("fields", {}).get("status", {}).get("name") in done_statuses
                    )
                results.append(InitiativeSummary(
                    issue=issue,
                    epic_count=len(epics),
                    task_count=task_count,
                    done_epic_count=done_epic_count,
                    done_task_count=done_task_count,
                ))
            return results
        except ConnectorError as exc:
            logger.warning("Failed to fetch initiatives for %s: %s", project.name, exc)
            return []
        finally:
            await jira.close()

    async def get_initiative_detail(self, initiative_key: str) -> InitiativeDetail | None:
        """Fetch an Initiative with its child Epics and each Epic's Tasks."""
        jira = JiraConnector(settings=self._settings)
        fields = ["summary", "status", "issuetype", "project", "labels",
                  "fixVersions", "duedate", "parent", "description"]
        try:
            raw = await jira.get_issue(initiative_key, fields=fields)
            initiative = JiraIssue.from_api(raw)

            epic_results = await jira.search(
                f'issuetype = Epic AND parent = {initiative_key}',
                fields=fields,
            )

            epics: list[EpicWithTasks] = []
            for epic_raw in epic_results:
                epic_issue = JiraIssue.from_api(epic_raw)
                task_results = await jira.search(
                    f'parent = {epic_issue.key}',
                    fields=fields,
                )
                tasks = [JiraIssue.from_api(t) for t in task_results]
                epics.append(EpicWithTasks(issue=epic_issue, tasks=tasks))

            return InitiativeDetail(issue=initiative, epics=epics)
        except ConnectorError as exc:
            logger.warning("Failed to fetch initiative %s: %s", initiative_key, exc)
            return None
        finally:
            await jira.close()
