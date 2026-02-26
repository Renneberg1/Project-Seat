"""Health review service — gather project data, LLM health check, persist reviews."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from typing import Any

from src.config import Settings, settings as default_settings
from src.models.project import Project

_CONTEXT_CACHE_TTL = 600  # 10 minutes

logger = logging.getLogger(__name__)


class HealthReviewService:
    """Orchestrate the LLM-powered project health review workflow."""

    def __init__(
        self,
        db_path: str | None = None,
        settings: Settings | None = None,
        review_repo: "HealthReviewRepository | None" = None,
    ) -> None:
        self._settings = settings or default_settings
        self._db_path = db_path or self._settings.db_path

        from src.repositories.review_repo import HealthReviewRepository
        self._repo = review_repo or HealthReviewRepository(self._db_path)

    # ------------------------------------------------------------------
    # Gather all project context
    # ------------------------------------------------------------------

    async def gather_all_context(self, project: Project) -> dict[str, Any]:
        """Fetch all available project data in parallel.

        Returns a dict suitable for passing to the prompt builders.
        Uses a 10-minute cache so Step 2 reuses context from Step 1.
        """
        from src.services.project_context import ProjectContextService

        ctx_service = ProjectContextService(
            db_path=self._db_path, settings=self._settings,
        )
        data = await ctx_service.gather(
            project,
            risks=True, decisions=True,
            charter=True, xft=True,
            summary=True, initiatives=True, pi=True,
            team_reports=True, snapshots=True, snapshot_days=90,
            dhf_summary=True, releases=True,
            meeting_summaries=True, meeting_summary_limit=5,
            cache_key=f"ctx:health_review:{project.id}",
            cache_ttl=_CONTEXT_CACHE_TTL,
        )

        return self._build_health_context(data)

    def _build_health_context(self, data: Any) -> dict[str, Any]:
        """Transform ProjectContextData into the dict format expected by prompts."""
        ctx: dict[str, Any] = {
            "project_name": data.project.name,
        }

        summary = data.summary
        if summary and summary.goal:
            ctx["goal"] = {
                "key": summary.goal.key,
                "summary": summary.goal.summary,
                "status": summary.goal.status,
                "due_date": summary.goal.due_date,
            }
            ctx["risk_count"] = summary.risk_count
            ctx["open_risk_count"] = summary.open_risk_count
            ctx["decision_count"] = summary.decision_count
            ctx["risk_points"] = summary.risk_points
            ctx["risk_threshold"] = summary.risk_threshold
            ctx["risk_level"] = summary.risk_level
            ctx["risks"] = [
                {"key": r.key, "summary": r.summary, "status": r.status}
                for r in (summary.risks or [])
            ]
            ctx["decisions"] = [
                {"key": d.key, "summary": d.summary, "status": d.status}
                for d in (summary.decisions or [])
            ]

        if data.initiatives:
            ctx["initiatives"] = [
                {
                    "key": i.issue.key,
                    "summary": i.issue.summary,
                    "epic_count": i.epic_count,
                    "done_epic_count": i.done_epic_count,
                    "task_count": i.task_count,
                    "done_task_count": i.done_task_count,
                }
                for i in data.initiatives
            ]

        if data.team_reports:
            ctx["team_reports"] = [
                {
                    "team_key": r.team_key,
                    "version_name": r.version_name,
                    "total_issues": r.total_issues,
                    "done_count": r.done_count,
                    "in_progress_count": r.in_progress_count,
                    "todo_count": r.todo_count,
                    "blocker_count": r.blocker_count,
                    "sp_total": r.sp_total,
                    "sp_done": r.sp_done,
                    "pct_done_issues": r.pct_done_issues,
                }
                for r in data.team_reports
            ]

        if data.snapshots:
            ctx["burnup_snapshots"] = data.snapshots

        if data.dhf_summary:
            ctx["dhf_summary"] = data.dhf_summary

        if data.pi_summary:
            ctx["pi_summary"] = asdict(data.pi_summary)

        if data.releases:
            ctx["releases"] = data.releases

        if data.charter_content:
            ctx["charter_content"] = data.charter_content
        if data.xft_content:
            ctx["xft_content"] = data.xft_content

        if data.meeting_summaries:
            ctx["meeting_summaries"] = data.meeting_summaries

        return ctx

    # ------------------------------------------------------------------
    # LLM Step 1: Generate questions
    # ------------------------------------------------------------------

    async def generate_questions(
        self, project: Project,
    ) -> list[dict[str, str]]:
        """Gather context and ask the LLM to identify gaps.

        Returns a list of question dicts.
        """
        from src.engine.agent import HealthReviewAgent, get_provider

        context = await self.gather_all_context(project)

        provider = get_provider(self._settings.llm)
        agent = HealthReviewAgent(provider)
        try:
            result = await agent.ask_questions(context)
        finally:
            await provider.close()

        return result.get("questions", [])

    # ------------------------------------------------------------------
    # LLM Step 2: Generate review
    # ------------------------------------------------------------------

    async def generate_review(
        self,
        project: Project,
        qa_pairs: list[dict[str, str]],
    ) -> dict[str, Any]:
        """Gather context and produce a structured health review.

        Returns the full review dict.
        """
        from src.engine.agent import HealthReviewAgent, get_provider

        context = await self.gather_all_context(project)

        provider = get_provider(self._settings.llm)
        agent = HealthReviewAgent(provider)
        try:
            result = await agent.generate_review(context, qa_pairs)
        finally:
            await provider.close()

        return result

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_review(self, project_id: int, review: dict[str, Any]) -> int:
        """Persist a review and return its ID."""
        health_rating = review.get("health_rating", "Amber")
        return self._repo.insert(project_id, health_rating, json.dumps(review))

    def list_reviews(self, project_id: int) -> list[dict[str, Any]]:
        """Return recent reviews (last 10), newest first."""
        return self._repo.list_reviews(project_id)

    def get_review(self, review_id: int) -> dict[str, Any] | None:
        """Fetch a single review by ID."""
        return self._repo.get_review(review_id)
