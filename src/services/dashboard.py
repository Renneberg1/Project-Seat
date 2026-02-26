"""Dashboard service — aggregates live Jira data for tracked projects."""

from __future__ import annotations

import asyncio
import logging

from src.cache import cache
import src.config
from src.config import Settings
from src.connectors.base import ConnectorError
from src.connectors.jira import JiraConnector
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
        project_repo: "ProjectRepository | None" = None,
    ) -> None:
        self._settings = settings or src.config.settings
        self._db_path = db_path or self._settings.db_path

        from src.repositories.project_repo import ProjectRepository
        self._repo = project_repo or ProjectRepository(self._db_path)

    # ------------------------------------------------------------------
    # Local DB queries
    # ------------------------------------------------------------------

    def list_projects(self) -> list[Project]:
        """Return all projects from the local database."""
        return self._repo.list_all()

    def get_project_by_id(self, project_id: int) -> Project | None:
        """Return a single project by ID, or None if not found."""
        return self._repo.get_by_id(project_id)

    def update_phase(self, project_id: int, phase: str) -> None:
        """Update the pipeline phase for a project."""
        if phase not in VALID_PHASES:
            raise ValueError(f"Invalid phase '{phase}'. Must be one of: {VALID_PHASES}")
        self._repo.update(project_id, phase=phase)

    def update_project(self, project_id: int, **fields) -> None:
        """Update one or more fields on a project row."""
        self._repo.update(project_id, **fields)

    # ------------------------------------------------------------------
    # Live Jira enrichment
    # ------------------------------------------------------------------

    async def get_project_summary(self, project: Project) -> ProjectSummary:
        """Fetch live Jira data for a single project.

        Results are cached for 60 seconds.
        Catches ConnectorError so a single project failure doesn't crash the dashboard.
        """
        cache_key = f"summary:{project.jira_goal_key}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        jira = JiraConnector(settings=self._settings)
        try:
            goal_data, risks_raw, decisions_raw, initiatives = await asyncio.gather(
                jira.get_issue(project.jira_goal_key, fields=[
                    "summary", "status", "issuetype", "project", "labels",
                    "fixVersions", "duedate", "parent", "description",
                    "customfield_13265", "customfield_13264", "customfield_13266",
                ]),
                jira.search(
                    f'project = RISK AND issuetype = Risk AND parent = {project.jira_goal_key}',
                    fields=["summary", "status", "issuetype", "project", "labels",
                            "fixVersions", "duedate", "parent", "description", "components",
                            "customfield_13264"],
                ),
                jira.search(
                    f'project = RISK AND issuetype = "Project Issue" AND parent = {project.jira_goal_key}',
                    fields=["summary", "status", "issuetype", "project", "labels",
                            "fixVersions", "duedate", "parent", "description",
                            "customfield_13267", "components"],
                ),
                jira.search(
                    f'parent = {project.jira_goal_key} AND project != RISK',
                    fields=["status"],
                ),
            )

            goal = JiraIssue.from_api(goal_data)
            risk_issues = [JiraIssue.from_api(r) for r in risks_raw]
            decision_issues = [JiraIssue.from_api(d) for d in decisions_raw]
            done_statuses = {"Done", "Closed"}
            open_risk_count = sum(
                1 for r in risk_issues if r.status not in done_statuses
            )

            result = ProjectSummary(
                project=project,
                goal=goal,
                risk_count=len(risk_issues),
                open_risk_count=open_risk_count,
                decision_count=len(decision_issues),
                initiative_count=len(initiatives),
                risk_threshold=goal.risk_threshold,
                risk_points=goal.risk_points,
                risk_level=goal.risk_level,
                risks=risk_issues,
                decisions=decision_issues,
                error=None,
            )
            cache.set(cache_key, result, ttl=60)
            return result
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

        Results are cached for 60 seconds.
        Excludes "Market Access" issue type.
        """
        if not project.pi_version:
            return []

        cache_key = f"pi:{project.pi_version}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

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
            ideas = [JiraIssue.from_api(r) for r in results]
            cache.set(cache_key, ideas, ttl=60)
            return ideas
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
        """Fetch Initiative tickets for a project with child Epic/Task counts.

        Results are cached for 60 seconds.
        Uses batched JQL: 3 queries total instead of 1 + N_initiatives + N_epics.
        """
        cache_key = f"initiatives:{project.jira_goal_key}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        jira = JiraConnector(settings=self._settings)
        try:
            # 1. Fetch all initiatives
            initiatives = await jira.search(
                f'parent = {project.jira_goal_key} AND project != RISK',
                fields=["summary", "status", "issuetype", "project", "labels",
                        "fixVersions", "duedate", "parent", "description"],
            )
            if not initiatives:
                return []

            init_keys = [raw.get("key", "") for raw in initiatives if raw.get("key")]
            if not init_keys:
                return []

            # 2. Batch-fetch ALL epics for all initiatives
            init_keys_str = ", ".join(init_keys)
            all_epics = await jira.search(
                f'issuetype = Epic AND parent in ({init_keys_str})',
                fields=["status", "parent"],
            )

            # Group epics by parent initiative key
            epics_by_parent: dict[str, list[dict]] = {k: [] for k in init_keys}
            epic_keys: list[str] = []
            for epic_raw in all_epics:
                parent_key = epic_raw.get("fields", {}).get("parent", {})
                if isinstance(parent_key, dict):
                    parent_key = parent_key.get("key", "")
                if parent_key in epics_by_parent:
                    epics_by_parent[parent_key].append(epic_raw)
                epic_key = epic_raw.get("key", "")
                if epic_key:
                    epic_keys.append(epic_key)

            # 3. Batch-fetch ALL tasks for all epics
            tasks_by_parent: dict[str, list[dict]] = {k: [] for k in epic_keys}
            if epic_keys:
                epic_keys_str = ", ".join(epic_keys)
                all_tasks = await jira.search(
                    f'parent in ({epic_keys_str})',
                    fields=["status", "parent"],
                )
                for task_raw in all_tasks:
                    parent_key = task_raw.get("fields", {}).get("parent", {})
                    if isinstance(parent_key, dict):
                        parent_key = parent_key.get("key", "")
                    if parent_key in tasks_by_parent:
                        tasks_by_parent[parent_key].append(task_raw)

            # Assemble results
            done_statuses = {"Done", "Closed"}
            results: list[InitiativeSummary] = []
            for raw in initiatives:
                issue = JiraIssue.from_api(raw)
                epics = epics_by_parent.get(issue.key, [])
                done_epic_count = sum(
                    1 for e in epics
                    if e.get("fields", {}).get("status", {}).get("name") in done_statuses
                )
                task_count = 0
                done_task_count = 0
                for epic_raw in epics:
                    epic_key = epic_raw.get("key", "")
                    tasks = tasks_by_parent.get(epic_key, [])
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
            cache.set(cache_key, results, ttl=60)
            return results
        except ConnectorError as exc:
            logger.warning("Failed to fetch initiatives for %s: %s", project.name, exc)
            return []
        finally:
            await jira.close()

    async def get_initiative_detail(self, initiative_key: str) -> InitiativeDetail | None:
        """Fetch an Initiative with its child Epics and each Epic's Tasks.

        Uses batched JQL: 1 issue fetch + 1 epics search + 1 batched tasks search.
        """
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

            epic_keys = [e.get("key", "") for e in epic_results if e.get("key")]

            # Batch-fetch all tasks for all epics in one query
            tasks_by_parent: dict[str, list[JiraIssue]] = {k: [] for k in epic_keys}
            if epic_keys:
                epic_keys_str = ", ".join(epic_keys)
                all_tasks = await jira.search(
                    f'parent in ({epic_keys_str})',
                    fields=fields,
                )
                for task_raw in all_tasks:
                    task_issue = JiraIssue.from_api(task_raw)
                    parent_key = task_raw.get("fields", {}).get("parent", {})
                    if isinstance(parent_key, dict):
                        parent_key = parent_key.get("key", "")
                    if parent_key in tasks_by_parent:
                        tasks_by_parent[parent_key].append(task_issue)

            epics: list[EpicWithTasks] = []
            for epic_raw in epic_results:
                epic_issue = JiraIssue.from_api(epic_raw)
                tasks = tasks_by_parent.get(epic_issue.key, [])
                epics.append(EpicWithTasks(issue=epic_issue, tasks=tasks))

            return InitiativeDetail(issue=initiative, epics=epics)
        except ConnectorError as exc:
            logger.warning("Failed to fetch initiative %s: %s", initiative_key, exc)
            return None
        finally:
            await jira.close()
