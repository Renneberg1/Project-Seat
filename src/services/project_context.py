"""Unified project context gathering — consolidates parallel data fetching."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from src.cache import cache
from src.config import Settings, settings as default_settings
from src.connectors.base import ConnectorError

from src.models.project import Project

logger = logging.getLogger(__name__)


@dataclass
class ProjectContextData:
    """Container for all available project context. Each field defaults to None/empty."""

    project: Project
    # Jira risks/decisions — key+summary pairs
    existing_risks: list[dict[str, str]] = field(default_factory=list)
    existing_decisions: list[dict[str, str]] = field(default_factory=list)
    # Raw Jira API responses (CEO review, with date filters)
    new_risks_raw: list[dict] = field(default_factory=list)
    new_decisions_raw: list[dict] = field(default_factory=list)
    # Goal metadata
    goal_labels: list[str] = field(default_factory=list)
    goal_components: list[str] = field(default_factory=list)
    # Confluence page content
    charter_content: str | None = None
    xft_content: str | None = None
    # Dashboard data
    summary: Any = None
    initiatives: list[Any] = field(default_factory=list)
    pi_summary: Any = None
    # Team data
    team_reports: list[Any] = field(default_factory=list)
    snapshots: list[dict] = field(default_factory=list)
    # DHF
    dhf_summary: Any = None
    dhf_docs: list[Any] = field(default_factory=list)
    # Releases
    releases: list[dict] = field(default_factory=list)
    # Meeting summaries
    meeting_summaries: list[dict] = field(default_factory=list)
    # Knowledge
    action_items: list[Any] = field(default_factory=list)
    knowledge_entries: list[Any] = field(default_factory=list)


class ProjectContextService:
    """Centralised parallel data fetcher for all project context needs."""

    def __init__(
        self,
        db_path: str | None = None,
        settings: Settings | None = None,
        transcript_repo: "TranscriptRepository | None" = None,
        knowledge_repo: "KnowledgeRepository | None" = None,
    ) -> None:
        self._settings = settings or default_settings
        self._db_path = db_path or self._settings.db_path
        self._transcript_repo = transcript_repo
        self._knowledge_repo = knowledge_repo

    async def gather(  # noqa: C901 — intentionally many flags
        self,
        project: Project,
        *,
        risks: bool = False,
        decisions: bool = False,
        risks_raw: bool = False,
        decisions_raw: bool = False,
        risks_created_since: str | None = None,
        decisions_created_since: str | None = None,
        charter: bool = False,
        xft: bool = False,
        goal_metadata: bool = False,
        summary: bool = False,
        initiatives: bool = False,
        pi: bool = False,
        team_reports: bool = False,
        snapshots: bool = False,
        snapshot_days: int = 90,
        dhf_summary: bool = False,
        dhf_docs: bool = False,
        releases: bool = False,
        meeting_summaries: bool = False,
        meeting_summary_limit: int = 5,
        meeting_summary_since: str | None = None,
        action_items: bool = False,
        knowledge: bool = False,
        cache_key: str | None = None,
        cache_ttl: float = 0,
    ) -> ProjectContextData:
        """Fetch requested sources in parallel. Each source fails independently."""
        if cache_key and cache_ttl > 0:
            cached = cache.get(cache_key)
            if cached is not None:
                logger.debug("ProjectContext: using cached data for %s", cache_key)
                return cached

        data = ProjectContextData(project=project)
        tasks: dict[str, Any] = {}

        # --- Jira risks/decisions (key+summary pairs) ---
        if risks:
            tasks["risks"] = self._fetch_risk_summaries(project)
        if decisions:
            tasks["decisions"] = self._fetch_decision_summaries(project)

        # --- Raw Jira risk/decision responses (with optional date filter) ---
        if risks_raw:
            tasks["risks_raw"] = self._fetch_risks_raw(project, risks_created_since)
        if decisions_raw:
            tasks["decisions_raw"] = self._fetch_decisions_raw(project, decisions_created_since)

        # --- Confluence page content ---
        if charter:
            tasks["charter"] = self._fetch_page_body(project.confluence_charter_id)
        if xft:
            tasks["xft"] = self._fetch_page_body(project.confluence_xft_id)

        # --- Goal metadata ---
        if goal_metadata:
            tasks["goal_metadata"] = self._fetch_goal_metadata(project)

        # --- Dashboard data ---
        if summary:
            tasks["summary"] = self._fetch_summary(project)
        if initiatives:
            tasks["initiatives"] = self._fetch_initiatives(project)
        if pi:
            tasks["pi"] = self._fetch_pi(project)

        # --- Team data ---
        if team_reports:
            tasks["team_reports"] = self._fetch_team_reports(project)
        if snapshots:
            tasks["snapshots"] = self._fetch_snapshots(project, snapshot_days)

        # --- DHF ---
        if dhf_summary:
            tasks["dhf_summary"] = self._fetch_dhf_summary(project)
        if dhf_docs:
            tasks["dhf_docs"] = self._fetch_dhf_docs(project)

        # --- Releases ---
        if releases:
            tasks["releases"] = self._fetch_releases(project)

        # --- Meeting summaries ---
        if meeting_summaries:
            tasks["meeting_summaries"] = self._fetch_meeting_summaries(
                project, meeting_summary_limit, meeting_summary_since,
            )

        # --- Knowledge ---
        if action_items:
            tasks["action_items"] = self._fetch_action_items(project)
        if knowledge:
            tasks["knowledge"] = self._fetch_knowledge_entries(project)

        # Run all tasks in parallel
        if tasks:
            keys = list(tasks.keys())
            results = await asyncio.gather(*tasks.values())
            for key, result in zip(keys, results):
                self._assign_result(data, key, result, project)

        if cache_key and cache_ttl > 0:
            cache.set(cache_key, data, cache_ttl)

        return data

    # ------------------------------------------------------------------
    # Result assignment
    # ------------------------------------------------------------------

    def _assign_result(
        self, data: ProjectContextData, key: str, result: Any, project: Project,
    ) -> None:
        if key == "risks":
            data.existing_risks = result
        elif key == "decisions":
            data.existing_decisions = result
        elif key == "risks_raw":
            data.new_risks_raw = result
        elif key == "decisions_raw":
            data.new_decisions_raw = result
        elif key == "charter":
            data.charter_content = result
        elif key == "xft":
            data.xft_content = result
        elif key == "goal_metadata":
            labels, components = result
            data.goal_labels = labels
            data.goal_components = components
            # Apply fallbacks from project defaults
            if not labels and getattr(project, "default_label", None):
                data.goal_labels = [project.default_label]
            if not components and getattr(project, "default_component", None):
                data.goal_components = [project.default_component]
        elif key == "summary":
            data.summary = result
        elif key == "initiatives":
            data.initiatives = result
        elif key == "pi":
            data.pi_summary = result
        elif key == "team_reports":
            data.team_reports = result
        elif key == "snapshots":
            data.snapshots = result
        elif key == "dhf_summary":
            data.dhf_summary = result
        elif key == "dhf_docs":
            data.dhf_docs = result
        elif key == "releases":
            data.releases = result
        elif key == "meeting_summaries":
            data.meeting_summaries = result
        elif key == "action_items":
            data.action_items = result
        elif key == "knowledge":
            data.knowledge_entries = result

    # ------------------------------------------------------------------
    # Individual fetch methods — each catches its own errors
    # ------------------------------------------------------------------

    async def _fetch_risk_summaries(self, project: Project) -> list[dict[str, str]]:
        from src.connectors.jira import JiraConnector
        jira = JiraConnector(settings=self._settings)
        try:
            raw = await jira.search(
                f'project = RISK AND issuetype = Risk AND parent = {project.jira_goal_key}',
                fields=["summary", "status"],
            )
            return [
                {
                    "key": r.get("key", ""),
                    "summary": r.get("fields", {}).get("summary", ""),
                    "status": r.get("fields", {}).get("status", {}).get("name", ""),
                }
                for r in raw
            ]
        except (ConnectorError, Exception) as exc:
            logger.warning("ProjectContext: failed to fetch risk summaries: %s", exc)
            return []
        finally:
            await jira.close()

    async def _fetch_decision_summaries(self, project: Project) -> list[dict[str, str]]:
        from src.connectors.jira import JiraConnector
        jira = JiraConnector(settings=self._settings)
        try:
            raw = await jira.search(
                f'project = RISK AND issuetype = "Project Issue" AND parent = {project.jira_goal_key}',
                fields=["summary", "status"],
            )
            return [
                {
                    "key": r.get("key", ""),
                    "summary": r.get("fields", {}).get("summary", ""),
                    "status": r.get("fields", {}).get("status", {}).get("name", ""),
                }
                for r in raw
            ]
        except (ConnectorError, Exception) as exc:
            logger.warning("ProjectContext: failed to fetch decision summaries: %s", exc)
            return []
        finally:
            await jira.close()

    async def _fetch_risks_raw(
        self, project: Project, created_since: str | None,
    ) -> list[dict]:
        from src.connectors.jira import JiraConnector
        jira = JiraConnector(settings=self._settings)
        try:
            jql = f'project = RISK AND issuetype = Risk AND parent = {project.jira_goal_key}'
            if created_since:
                jql += f' AND created >= {created_since}'
            return await jira.search(jql, fields=["summary", "status", "components"])
        except (ConnectorError, Exception) as exc:
            logger.warning("ProjectContext: failed to fetch raw risks: %s", exc)
            return []
        finally:
            await jira.close()

    async def _fetch_decisions_raw(
        self, project: Project, created_since: str | None,
    ) -> list[dict]:
        from src.connectors.jira import JiraConnector
        jira = JiraConnector(settings=self._settings)
        try:
            jql = (
                f'project = RISK AND issuetype = "Project Issue" '
                f'AND parent = {project.jira_goal_key}'
            )
            if created_since:
                jql += f' AND created >= {created_since}'
            return await jira.search(jql, fields=["summary", "status"])
        except (ConnectorError, Exception) as exc:
            logger.warning("ProjectContext: failed to fetch raw decisions: %s", exc)
            return []
        finally:
            await jira.close()

    async def _fetch_page_body(self, page_id: str | None) -> str | None:
        if not page_id:
            return None
        from src.connectors.confluence import ConfluenceConnector
        confluence = ConfluenceConnector(settings=self._settings)
        try:
            data = await confluence.get_page(page_id, expand=["body.storage"])
            return data.get("body", {}).get("storage", {}).get("value", "")
        except (ConnectorError, Exception) as exc:
            logger.warning("ProjectContext: failed to fetch page %s: %s", page_id, exc)
            return None
        finally:
            await confluence.close()

    async def _fetch_goal_metadata(self, project: Project) -> tuple[list[str], list[str]]:
        from src.connectors.jira import JiraConnector
        jira = JiraConnector(settings=self._settings)
        try:
            goal = await jira.get_issue(
                project.jira_goal_key, fields=["labels", "components"]
            )
            labels = goal.get("fields", {}).get("labels", [])
            components = [
                c.get("name", "") for c in goal.get("fields", {}).get("components", [])
            ]
            return labels, components
        except (ConnectorError, Exception) as exc:
            logger.warning(
                "ProjectContext: failed to fetch goal metadata for %s: %s",
                project.jira_goal_key, exc,
            )
            return [], []
        finally:
            await jira.close()

    async def _fetch_summary(self, project: Project) -> Any:
        from src.services.dashboard import DashboardService
        dashboard = DashboardService(db_path=self._db_path, settings=self._settings)
        try:
            return await dashboard.get_project_summary(project)
        except Exception as exc:
            logger.warning("ProjectContext: failed to get project summary: %s", exc)
            return None

    async def _fetch_initiatives(self, project: Project) -> list:
        from src.services.dashboard import DashboardService
        dashboard = DashboardService(db_path=self._db_path, settings=self._settings)
        try:
            return await dashboard.get_initiatives(project)
        except Exception as exc:
            logger.warning("ProjectContext: failed to get initiatives: %s", exc)
            return []

    async def _fetch_pi(self, project: Project) -> Any:
        from src.services.dashboard import DashboardService
        dashboard = DashboardService(db_path=self._db_path, settings=self._settings)
        try:
            ideas = await dashboard.get_product_ideas(project)
            return dashboard.summarise_product_ideas(ideas)
        except Exception as exc:
            logger.warning("ProjectContext: failed to get product ideas: %s", exc)
            return None

    async def _fetch_team_reports(self, project: Project) -> list:
        from src.services.team_progress import TeamProgressService
        svc = TeamProgressService()
        try:
            return await svc.get_team_reports(project)
        except Exception as exc:
            logger.warning("ProjectContext: failed to get team reports: %s", exc)
            return []

    async def _fetch_snapshots(self, project: Project, days: int) -> list[dict]:
        from src.services.team_snapshot import TeamSnapshotService
        svc = TeamSnapshotService(db_path=self._db_path)
        try:
            return svc.get_snapshots(project.id, days)
        except Exception as exc:
            logger.warning("ProjectContext: failed to get snapshots: %s", exc)
            return []

    async def _fetch_dhf_summary(self, project: Project) -> Any:
        from dataclasses import asdict
        from src.services.dhf import DHFService
        svc = DHFService(settings=self._settings)
        try:
            summary = await svc.get_dhf_summary(project)
            return asdict(summary)
        except Exception as exc:
            logger.warning("ProjectContext: failed to get DHF summary: %s", exc)
            return None

    async def _fetch_dhf_docs(self, project: Project) -> list:
        from src.services.dhf import DHFService
        svc = DHFService(settings=self._settings)
        try:
            docs, _ = await svc.get_dhf_table(project)
            return docs
        except Exception as exc:
            logger.warning("ProjectContext: failed to get DHF docs: %s", exc)
            return []

    async def _fetch_releases(self, project: Project) -> list[dict]:
        from src.services.release import ReleaseService
        svc = ReleaseService(db_path=self._db_path)
        try:
            release_list = svc.list_releases(project.id)
            return [{"name": r.name, "locked": r.locked} for r in release_list]
        except Exception as exc:
            logger.warning("ProjectContext: failed to get releases: %s", exc)
            return []

    async def _fetch_meeting_summaries(
        self, project: Project, limit: int, since: str | None,
    ) -> list[dict]:
        try:
            from src.repositories.transcript_repo import TranscriptRepository
            repo = self._transcript_repo or TranscriptRepository(self._db_path)
            return repo.get_meeting_summaries(project.id, limit=limit, since=since)
        except Exception as exc:
            logger.warning("ProjectContext: failed to get meeting summaries: %s", exc)
            return []

    async def _fetch_action_items(self, project: Project) -> list:
        try:
            from src.repositories.knowledge_repo import KnowledgeRepository
            repo = self._knowledge_repo or KnowledgeRepository(self._db_path)
            return repo.list_action_items(project.id, status="open")
        except Exception as exc:
            logger.warning("ProjectContext: failed to get action items: %s", exc)
            return []

    async def _fetch_knowledge_entries(self, project: Project) -> list:
        try:
            from src.repositories.knowledge_repo import KnowledgeRepository
            repo = self._knowledge_repo or KnowledgeRepository(self._db_path)
            return repo.list_knowledge_entries(project.id)
        except Exception as exc:
            logger.warning("ProjectContext: failed to get knowledge entries: %s", exc)
            return []
