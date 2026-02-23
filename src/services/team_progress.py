"""Team version progress service — per-team issue counts from Jira fix versions."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.cache import cache
from src.connectors.base import ConnectorError
from src.connectors.jira import JiraConnector
from src.models.project import Project

logger = logging.getLogger(__name__)

# Jira fields needed for progress tracking
_SEARCH_FIELDS = [
    "status",
    "issuetype",
    "project",
    "priority",
    "customfield_10016",  # Story point estimate (next-gen)
    "customfield_10026",  # Story Points (classic)
]


@dataclass
class TeamVersionReport:
    """Progress report for a single team's fix version."""

    team_key: str
    version_name: str
    total_issues: int
    done_count: int
    in_progress_count: int
    todo_count: int
    blocker_count: int
    sp_total: float
    sp_done: float
    sp_missing_count: int
    error: str | None = None

    @property
    def pct_done_issues(self) -> int:
        if self.total_issues == 0:
            return 0
        return round(100 * self.done_count / self.total_issues)

    @property
    def pct_done_sp(self) -> int:
        if self.sp_total == 0:
            return 0
        return round(100 * self.sp_done / self.sp_total)


def _get_story_points(fields: dict) -> float | None:
    """Extract story points, preferring next-gen field over classic."""
    sp = fields.get("customfield_10016")
    if sp is not None:
        try:
            return float(sp)
        except (TypeError, ValueError):
            pass
    sp = fields.get("customfield_10026")
    if sp is not None:
        try:
            return float(sp)
        except (TypeError, ValueError):
            pass
    return None


def _aggregate(team_key: str, version_name: str, raw_issues: list[dict]) -> TeamVersionReport:
    """Build a TeamVersionReport from a list of raw Jira issue dicts."""
    done = 0
    in_progress = 0
    todo = 0
    blockers = 0
    sp_total = 0.0
    sp_done = 0.0
    sp_missing = 0

    for issue in raw_issues:
        fields = issue.get("fields", {})

        # Status category classification
        status_cat = (
            fields.get("status", {}).get("statusCategory", {}).get("name", "")
        )
        if status_cat == "Done":
            done += 1
        elif status_cat == "In Progress":
            in_progress += 1
        else:
            todo += 1

        # Blocker priority
        priority_name = fields.get("priority", {}).get("name", "") if fields.get("priority") else ""
        if priority_name == "Blocker":
            blockers += 1

        # Story points
        sp = _get_story_points(fields)
        if sp is not None:
            sp_total += sp
            if status_cat == "Done":
                sp_done += sp
        else:
            sp_missing += 1

    return TeamVersionReport(
        team_key=team_key,
        version_name=version_name,
        total_issues=len(raw_issues),
        done_count=done,
        in_progress_count=in_progress,
        todo_count=todo,
        blocker_count=blockers,
        sp_total=sp_total,
        sp_done=sp_done,
        sp_missing_count=sp_missing,
    )


class TeamProgressService:
    """Fetches per-team fix version progress from Jira."""

    async def get_team_reports(self, project: Project) -> list[TeamVersionReport]:
        """Return a TeamVersionReport per team project, or [] if none configured."""
        if not project.team_projects:
            return []

        cache_key = f"team_progress:{project.jira_goal_key}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            reports = await self._fetch_reports(project)
        except ConnectorError as exc:
            logger.warning("Failed to fetch team progress for %s: %s", project.name, exc)
            reports = [
                TeamVersionReport(
                    team_key=tk,
                    version_name=ver,
                    total_issues=0, done_count=0, in_progress_count=0,
                    todo_count=0, blocker_count=0,
                    sp_total=0, sp_done=0, sp_missing_count=0,
                    error=str(exc),
                )
                for tk, ver in project.team_projects.items()
            ]

        cache.set(cache_key, reports, ttl=60)
        return reports

    async def _fetch_reports(self, project: Project) -> list[TeamVersionReport]:
        """Execute JQL queries grouped by version name and aggregate per team."""
        # Group teams by version name so we issue one query per unique version
        version_to_teams: dict[str, list[str]] = {}
        for tk, ver in project.team_projects.items():
            version_to_teams.setdefault(ver, []).append(tk)

        all_issues: list[dict] = []
        jira = JiraConnector()
        try:
            for version_name, team_keys in version_to_teams.items():
                keys_csv = ", ".join(team_keys)
                jql = f'project in ({keys_csv}) AND fixVersion = "{version_name}"'
                issues = await jira.search(jql, fields=_SEARCH_FIELDS)
                all_issues.extend(issues)
        finally:
            await jira.close()

        # Group by project key
        by_team: dict[str, list[dict]] = {tk: [] for tk in project.team_projects}
        for issue in all_issues:
            pk = issue.get("fields", {}).get("project", {}).get("key", "")
            if pk in by_team:
                by_team[pk].append(issue)

        return [
            _aggregate(tk, ver, by_team[tk])
            for tk, ver in project.team_projects.items()
        ]
