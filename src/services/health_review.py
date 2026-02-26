"""Health review service — gather project data, LLM health check, persist reviews."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict
from typing import Any

from src.cache import cache
from src.config import Settings, settings as default_settings
from src.database import get_db
from src.models.project import Project

_CONTEXT_CACHE_TTL = 600  # 10 minutes

logger = logging.getLogger(__name__)


class HealthReviewService:
    """Orchestrate the LLM-powered project health review workflow."""

    def __init__(
        self,
        db_path: str | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or default_settings
        self._db_path = db_path or self._settings.db_path

    # ------------------------------------------------------------------
    # Gather all project context
    # ------------------------------------------------------------------

    async def gather_all_context(self, project: Project) -> dict[str, Any]:
        """Fetch all available project data in parallel.

        Returns a dict suitable for passing to the prompt builders.
        Uses a 10-minute cache so Step 2 reuses context from Step 1.
        """
        cache_key = f"ctx:health_review:{project.id}"
        cached = cache.get(cache_key)
        if cached is not None:
            logger.debug("Health review: using cached context for project %d", project.id)
            return cached

        from src.services.dashboard import DashboardService
        from src.services.dhf import DHFService
        from src.services.release import ReleaseService
        from src.services.team_progress import TeamProgressService
        from src.services.team_snapshot import TeamSnapshotService
        from src.services.transcript import TranscriptService

        dashboard = DashboardService(db_path=self._db_path, settings=self._settings)
        dhf_service = DHFService(settings=self._settings)
        team_progress = TeamProgressService()
        team_snapshot = TeamSnapshotService(db_path=self._db_path)
        transcript_service = TranscriptService(db_path=self._db_path, settings=self._settings)

        # Parallel fetch — each wrapped to catch errors gracefully
        async def _get_summary():
            try:
                return await dashboard.get_project_summary(project)
            except Exception as exc:
                logger.warning("Health review: failed to get project summary: %s", exc)
                return None

        async def _get_initiatives():
            try:
                return await dashboard.get_initiatives(project)
            except Exception as exc:
                logger.warning("Health review: failed to get initiatives: %s", exc)
                return []

        async def _get_pi():
            try:
                ideas = await dashboard.get_product_ideas(project)
                return dashboard.summarise_product_ideas(ideas)
            except Exception as exc:
                logger.warning("Health review: failed to get product ideas: %s", exc)
                return None

        async def _get_team_reports():
            try:
                return await team_progress.get_team_reports(project)
            except Exception as exc:
                logger.warning("Health review: failed to get team reports: %s", exc)
                return []

        async def _get_snapshots():
            try:
                return team_snapshot.get_snapshots(project.id, 90)
            except Exception as exc:
                logger.warning("Health review: failed to get snapshots: %s", exc)
                return []

        async def _get_dhf():
            try:
                summary = await dhf_service.get_dhf_summary(project)
                return asdict(summary)
            except Exception as exc:
                logger.warning("Health review: failed to get DHF summary: %s", exc)
                return None

        async def _get_transcript_context():
            try:
                return await transcript_service.gather_project_context(project)
            except Exception as exc:
                logger.warning("Health review: failed to get transcript context: %s", exc)
                return None

        async def _get_releases():
            try:
                release_service = ReleaseService(db_path=self._db_path)
                releases = release_service.list_releases(project.id)
                return [{"name": r.name, "locked": r.locked} for r in releases]
            except Exception as exc:
                logger.warning("Health review: failed to get releases: %s", exc)
                return []

        async def _get_meeting_summaries():
            try:
                with get_db(self._db_path) as conn:
                    rows = conn.execute(
                        "SELECT filename, meeting_summary, created_at FROM transcript_cache "
                        "WHERE project_id = ? AND meeting_summary IS NOT NULL "
                        "ORDER BY created_at DESC LIMIT 5",
                        (project.id,),
                    ).fetchall()
                return [
                    {"filename": r["filename"], "summary": r["meeting_summary"], "created_at": r["created_at"]}
                    for r in rows
                ]
            except Exception as exc:
                logger.warning("Health review: failed to get meeting summaries: %s", exc)
                return []

        (
            summary, initiatives, pi_summary, team_reports,
            snapshots, dhf_summary, transcript_ctx, releases,
            meeting_summaries,
        ) = await asyncio.gather(
            _get_summary(),
            _get_initiatives(),
            _get_pi(),
            _get_team_reports(),
            _get_snapshots(),
            _get_dhf(),
            _get_transcript_context(),
            _get_releases(),
            _get_meeting_summaries(),
        )

        # Assemble context dict
        ctx: dict[str, Any] = {
            "project_name": project.name,
        }

        # From project summary
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

        # From initiatives
        if initiatives:
            ctx["initiatives"] = [
                {
                    "key": i.issue.key,
                    "summary": i.issue.summary,
                    "epic_count": i.epic_count,
                    "done_epic_count": i.done_epic_count,
                    "task_count": i.task_count,
                    "done_task_count": i.done_task_count,
                }
                for i in initiatives
            ]

        # Team progress
        if team_reports:
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
                for r in team_reports
            ]

        # Burnup snapshots
        if snapshots:
            ctx["burnup_snapshots"] = snapshots

        # DHF
        if dhf_summary:
            ctx["dhf_summary"] = dhf_summary

        # Product Ideas
        if pi_summary:
            ctx["pi_summary"] = asdict(pi_summary)

        # Releases
        if releases:
            ctx["releases"] = releases

        # Charter / XFT content from transcript context
        if transcript_ctx:
            ctx["charter_content"] = transcript_ctx.charter_content
            ctx["xft_content"] = transcript_ctx.xft_content

        # Meeting summaries
        if meeting_summaries:
            ctx["meeting_summaries"] = meeting_summaries

        cache.set(cache_key, ctx, _CONTEXT_CACHE_TTL)
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
        with get_db(self._db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO health_reviews (project_id, health_rating, review_json) "
                "VALUES (?, ?, ?)",
                (project_id, health_rating, json.dumps(review)),
            )
            conn.commit()
            return cursor.lastrowid

    def list_reviews(self, project_id: int) -> list[dict[str, Any]]:
        """Return recent reviews (last 10), newest first."""
        with get_db(self._db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM health_reviews WHERE project_id = ? "
                "ORDER BY id DESC LIMIT 10",
                (project_id,),
            ).fetchall()
        results = []
        for r in rows:
            review_data = json.loads(r["review_json"])
            review_data["id"] = r["id"]
            review_data["created_at"] = r["created_at"]
            review_data["health_rating"] = r["health_rating"]
            results.append(review_data)
        return results

    def get_review(self, review_id: int) -> dict[str, Any] | None:
        """Fetch a single review by ID."""
        with get_db(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM health_reviews WHERE id = ?",
                (review_id,),
            ).fetchone()
        if not row:
            return None
        review_data = json.loads(row["review_json"])
        review_data["id"] = row["id"]
        review_data["created_at"] = row["created_at"]
        review_data["health_rating"] = row["health_rating"]
        return review_data
