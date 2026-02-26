"""CEO Review service — gather project data, LLM status update, publish to Confluence."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict
from datetime import date, datetime, timedelta
from html import escape
from typing import Any

from src.cache import cache
from src.config import Settings, settings as default_settings
from src.database import get_db
from src.models.ceo_review import CeoReview, CeoReviewStatus
from src.models.project import Project

_CONTEXT_CACHE_TTL = 600  # 10 minutes

logger = logging.getLogger(__name__)

_TWO_WEEKS_AGO = lambda: (date.today() - timedelta(days=14)).isoformat()


class CeoReviewService:
    """Orchestrate the LLM-powered CEO status update workflow."""

    def __init__(
        self,
        db_path: str | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or default_settings
        self._db_path = db_path or self._settings.db_path

    # ------------------------------------------------------------------
    # Gather context (reuses existing services + new recent queries)
    # ------------------------------------------------------------------

    async def gather_ceo_context(self, project: Project) -> dict[str, Any]:
        """Fetch all data needed for a CEO review, including 2-week-focused queries.

        Uses a 10-minute cache so Step 2 reuses context from Step 1.
        """
        cache_key = f"ctx:ceo_review:{project.id}"
        cached = cache.get(cache_key)
        if cached is not None:
            logger.debug("CEO review: using cached context for project %d", project.id)
            return cached

        from src.connectors.jira import JiraConnector
        from src.services.dashboard import DashboardService
        from src.services.dhf import DHFService
        from src.services.release import ReleaseService
        from src.services.team_progress import TeamProgressService
        from src.services.team_snapshot import TeamSnapshotService

        dashboard = DashboardService(db_path=self._db_path, settings=self._settings)
        dhf_service = DHFService(settings=self._settings)
        team_progress = TeamProgressService()
        team_snapshot = TeamSnapshotService(db_path=self._db_path)

        async def _get_summary():
            try:
                return await dashboard.get_project_summary(project)
            except Exception as exc:
                logger.warning("CEO review: failed to get project summary: %s", exc)
                return None

        async def _get_initiatives():
            try:
                return await dashboard.get_initiatives(project)
            except Exception as exc:
                logger.warning("CEO review: failed to get initiatives: %s", exc)
                return []

        async def _get_team_reports():
            try:
                return await team_progress.get_team_reports(project)
            except Exception as exc:
                logger.warning("CEO review: failed to get team reports: %s", exc)
                return []

        async def _get_snapshots():
            try:
                return team_snapshot.get_snapshots(project.id, 14)
            except Exception as exc:
                logger.warning("CEO review: failed to get snapshots: %s", exc)
                return []

        async def _get_dhf():
            try:
                docs, _ = await dhf_service.get_dhf_table(project)
                return docs
            except Exception as exc:
                logger.warning("CEO review: failed to get DHF data: %s", exc)
                return []

        async def _get_releases():
            try:
                release_service = ReleaseService(db_path=self._db_path)
                releases = release_service.list_releases(project.id)
                return [{"name": r.name, "locked": r.locked} for r in releases]
            except Exception as exc:
                logger.warning("CEO review: failed to get releases: %s", exc)
                return []

        async def _get_new_risks():
            """Fetch risks created in the last 2 weeks."""
            try:
                jira = JiraConnector(settings=self._settings)
                try:
                    # Build version filter from team_projects
                    jql = (
                        f'project = RISK AND issuetype = Risk '
                        f'AND parent = {project.jira_goal_key} AND created >= -2w'
                    )
                    issues = await jira.search(
                        jql,
                        fields=["summary", "status", "components"],
                    )
                    return issues
                finally:
                    await jira.close()
            except Exception as exc:
                logger.warning("CEO review: failed to get new risks: %s", exc)
                return []

        async def _get_new_decisions():
            """Fetch decisions created in the last 2 weeks."""
            try:
                jira = JiraConnector(settings=self._settings)
                try:
                    jql = (
                        f'project = RISK AND issuetype = "Project Issue" '
                        f'AND parent = {project.jira_goal_key} AND created >= -2w'
                    )
                    issues = await jira.search(
                        jql,
                        fields=["summary", "status"],
                    )
                    return issues
                finally:
                    await jira.close()
            except Exception as exc:
                logger.warning("CEO review: failed to get new decisions: %s", exc)
                return []

        async def _get_meeting_summaries():
            try:
                with get_db(self._db_path) as conn:
                    rows = conn.execute(
                        "SELECT filename, meeting_summary, created_at FROM transcript_cache "
                        "WHERE project_id = ? AND meeting_summary IS NOT NULL "
                        "AND created_at >= ? ORDER BY created_at DESC LIMIT 5",
                        (project.id, _TWO_WEEKS_AGO()),
                    ).fetchall()
                return [
                    {"filename": r["filename"], "summary": r["meeting_summary"], "created_at": r["created_at"]}
                    for r in rows
                ]
            except Exception as exc:
                logger.warning("CEO review: failed to get meeting summaries: %s", exc)
                return []

        (
            summary, initiatives, team_reports, snapshots,
            dhf_docs, releases, new_risks_raw, new_decisions_raw,
            meeting_summaries,
        ) = await asyncio.gather(
            _get_summary(),
            _get_initiatives(),
            _get_team_reports(),
            _get_snapshots(),
            _get_dhf(),
            _get_releases(),
            _get_new_risks(),
            _get_new_decisions(),
            _get_meeting_summaries(),
        )

        ctx = {
            "project": project,
            "summary": summary,
            "initiatives": initiatives,
            "team_reports": team_reports,
            "snapshots": snapshots,
            "dhf_docs": dhf_docs,
            "releases": releases,
            "new_risks_raw": new_risks_raw,
            "new_decisions_raw": new_decisions_raw,
            "meeting_summaries": meeting_summaries,
        }
        cache.set(cache_key, ctx, _CONTEXT_CACHE_TTL)
        return ctx

    # ------------------------------------------------------------------
    # Compute deterministic metrics from context
    # ------------------------------------------------------------------

    def compute_metrics(self, context: dict[str, Any]) -> dict[str, Any]:
        """Extract deterministic metrics dict from gathered context."""
        from src.models.dhf import DocumentStatus
        from src.models.jira import JiraIssue

        project: Project = context["project"]
        summary = context.get("summary")

        metrics: dict[str, Any] = {
            "project_name": project.name,
            "phase": project.phase,
            "due_date": None,
            "total_risk_count": 0,
            "open_risk_count": 0,
        }

        if summary and summary.goal:
            metrics["due_date"] = summary.goal.due_date
            metrics["total_risk_count"] = summary.risk_count
            metrics["open_risk_count"] = summary.open_risk_count

        # New risks (last 2 weeks)
        new_risks = []
        for raw in context.get("new_risks_raw", []):
            fields = raw.get("fields", {})
            components_raw = fields.get("components", [])
            components = ", ".join(c.get("name", "") for c in components_raw) if components_raw else ""
            new_risks.append({
                "key": raw.get("key", "?"),
                "summary": fields.get("summary", "?"),
                "status": fields.get("status", {}).get("name", "?"),
                "components": components,
            })
        metrics["new_risks"] = new_risks

        # New decisions (last 2 weeks)
        new_decisions = []
        for raw in context.get("new_decisions_raw", []):
            fields = raw.get("fields", {})
            new_decisions.append({
                "key": raw.get("key", "?"),
                "summary": fields.get("summary", "?"),
                "status": fields.get("status", {}).get("name", "?"),
            })
        metrics["new_decisions"] = new_decisions

        # Team progress
        team_reports = context.get("team_reports", [])
        team_progress_list = []
        for r in team_reports:
            total = r.sp_total or 1
            pct = round(100 * r.sp_done / total) if total else 0
            team_progress_list.append({
                "team": r.team_key,
                "pct_done": pct,
                "sp_done": r.sp_done,
                "sp_total": r.sp_total,
                "blockers": r.blocker_count,
            })
        metrics["team_progress"] = team_progress_list

        # Burnup delta from snapshots (2 weeks)
        snapshots = context.get("snapshots", [])
        sp_burned_2w = 0
        scope_change_2w = 0
        if len(snapshots) >= 2:
            first = snapshots[0]
            last = snapshots[-1]
            sp_burned_2w = last.get("sp_done", 0) - first.get("sp_done", 0)
            scope_change_2w = last.get("sp_total", 0) - first.get("sp_total", 0)
        metrics["sp_burned_2w"] = sp_burned_2w
        metrics["scope_change_2w"] = scope_change_2w

        # DHF documents
        dhf_docs = context.get("dhf_docs", [])
        dhf_total = len(dhf_docs)
        dhf_released = sum(1 for d in dhf_docs if d.status == DocumentStatus.RELEASED)
        dhf_pct = round(100 * dhf_released / dhf_total) if dhf_total else 0
        metrics["dhf_total"] = dhf_total
        metrics["dhf_released"] = dhf_released
        metrics["dhf_completion_pct"] = dhf_pct

        # Recently updated docs (last 2 weeks)
        cutoff = _TWO_WEEKS_AGO()
        dhf_recently_updated = []
        for d in dhf_docs:
            if d.last_modified and d.last_modified >= cutoff:
                dhf_recently_updated.append({
                    "title": d.title,
                    "status": d.status.value,
                    "last_modified": d.last_modified,
                })
        metrics["dhf_recently_updated"] = dhf_recently_updated

        # Releases
        metrics["releases"] = context.get("releases", [])

        return metrics

    # ------------------------------------------------------------------
    # LLM Step 1: Generate questions
    # ------------------------------------------------------------------

    async def generate_questions(
        self, project: Project, pm_notes: str = "",
    ) -> tuple[list[dict[str, str]], dict[str, Any]]:
        """Gather context, compute metrics, ask the LLM for questions.

        Returns (questions, metrics) so the route can carry metrics forward.
        """
        from src.engine.agent import CeoReviewAgent, get_provider

        context = await self.gather_ceo_context(project)
        metrics = self.compute_metrics(context)

        provider = get_provider(self._settings.llm)
        agent = CeoReviewAgent(provider)
        try:
            result = await agent.ask_questions(metrics, pm_notes)
        finally:
            await provider.close()

        return result.get("questions", []), metrics

    # ------------------------------------------------------------------
    # LLM Step 2: Generate review
    # ------------------------------------------------------------------

    async def generate_review(
        self,
        project: Project,
        pm_notes: str,
        qa_pairs: list[dict[str, str]],
    ) -> dict[str, Any]:
        """Gather context, compute metrics, produce the CEO review.

        Returns the merged review dict (LLM narrative + pre-computed metrics).
        """
        from src.engine.agent import CeoReviewAgent, get_provider

        context = await self.gather_ceo_context(project)
        metrics = self.compute_metrics(context)

        provider = get_provider(self._settings.llm)
        agent = CeoReviewAgent(provider)
        try:
            result = await agent.generate_review(metrics, pm_notes, qa_pairs)
        finally:
            await provider.close()

        # Merge pre-computed metrics into the review for template rendering
        result["metrics"] = metrics
        return result

    # ------------------------------------------------------------------
    # Confluence XHTML rendering
    # ------------------------------------------------------------------

    def render_confluence_xhtml(self, review_data: dict[str, Any]) -> str:
        """Build Confluence storage-format XHTML for the Summary Status cell.

        Produces a concise ``<ul><li>`` bullet list suitable for replacing
        the ``<td>`` adjacent to the "Summary Status:" ``<th>`` in the
        CEO Review template table.
        """
        metrics = review_data.get("metrics", {})
        project_name = escape(metrics.get("project_name", "Unknown"))
        today = date.today().strftime("%d %b %Y")
        indicator = review_data.get("health_indicator", "At Risk")

        colour_map = {"On Track": "Green", "At Risk": "Yellow", "Off Track": "Red"}
        colour = colour_map.get(indicator, "Yellow")

        items: list[str] = []

        # Status header with Confluence status macro
        items.append(
            f'<ac:structured-macro ac:name="status">'
            f'<ac:parameter ac:name="title">{escape(indicator)}</ac:parameter>'
            f'<ac:parameter ac:name="colour">{colour}</ac:parameter>'
            f'</ac:structured-macro> {project_name} \u2014 {today}'
        )

        # Summary line
        summary = review_data.get("summary", "")
        if summary:
            items.append(f"<strong>{escape(summary)}</strong>")

        # Bullets
        for bullet in review_data.get("bullets", []):
            items.append(escape(bullet))

        # Escalations (only if present)
        escalations = review_data.get("escalations", [])
        for e in escalations:
            items.append(
                f"Escalation: {escape(e.get('issue', ''))} "
                f"\u2014 {escape(e.get('impact', ''))}. "
                f"Ask: {escape(e.get('ask', ''))}"
            )

        # Next milestones
        milestones = review_data.get("next_milestones", [])
        if milestones:
            items.append("Next: " + "; ".join(escape(m) for m in milestones))

        parts = ["<ul>"]
        for item in items:
            parts.append(f"<li>{item}</li>")
        parts.append("</ul>")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_review(self, project_id: int, review: dict[str, Any], xhtml: str) -> int:
        """Persist a CEO review and return its ID."""
        with get_db(self._db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO ceo_reviews (project_id, review_json, confluence_body, status) "
                "VALUES (?, ?, ?, ?)",
                (project_id, json.dumps(review), xhtml, CeoReviewStatus.DRAFT.value),
            )
            conn.commit()
            return cursor.lastrowid

    def accept_review(self, review_id: int, project: Project) -> CeoReview | None:
        """Accept a review and queue it for approval (Confluence append)."""
        from src.engine.approval import ApprovalEngine
        from src.models.approval import ApprovalAction

        review = self.get_review(review_id)
        if review is None or review.status != CeoReviewStatus.DRAFT:
            return review

        page_id = project.confluence_ceo_review_id
        if not page_id:
            raise ValueError(
                "Cannot publish: no CEO Review page configured. "
                "Set the page ID in Project Settings."
            )

        payload = {
            "page_id": page_id,
            "section_replace_mode": True,
            "section_name": "Summary Status",
            "new_content": review.confluence_body,
            "raw_xhtml": True,
        }

        engine = ApprovalEngine(db_path=self._db_path)
        item_id = engine.propose(
            action_type=ApprovalAction.UPDATE_CONFLUENCE_PAGE,
            payload=payload,
            preview=f"Update Summary Status on CEO Review page {page_id}",
            context=f"CEO Review for {project.name}",
            project_id=project.id,
        )

        with get_db(self._db_path) as conn:
            conn.execute(
                "UPDATE ceo_reviews SET status = ?, approval_item_id = ? WHERE id = ?",
                (CeoReviewStatus.QUEUED.value, item_id, review_id),
            )
            conn.commit()

        return self.get_review(review_id)

    def reject_review(self, review_id: int) -> CeoReview | None:
        """Reject a CEO review."""
        with get_db(self._db_path) as conn:
            conn.execute(
                "UPDATE ceo_reviews SET status = ? WHERE id = ?",
                (CeoReviewStatus.REJECTED.value, review_id),
            )
            conn.commit()
        return self.get_review(review_id)

    def list_reviews(self, project_id: int) -> list[CeoReview]:
        """Return recent CEO reviews (last 10), newest first."""
        with get_db(self._db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM ceo_reviews WHERE project_id = ? ORDER BY id DESC LIMIT 10",
                (project_id,),
            ).fetchall()
        return [CeoReview.from_row(r) for r in rows]

    def get_review(self, review_id: int) -> CeoReview | None:
        """Fetch a single CEO review by ID."""
        with get_db(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM ceo_reviews WHERE id = ?",
                (review_id,),
            ).fetchone()
        return CeoReview.from_row(row) if row else None

    # ------------------------------------------------------------------
    # CEO Review page discovery
    # ------------------------------------------------------------------

    async def discover_ceo_review_page(self, project: Project) -> str | None:
        """Walk up Charter ancestors to find the 'CEO Review' sibling page.

        Returns the page ID if found, else None.
        """
        from src.connectors.confluence import ConfluenceConnector

        if not project.confluence_charter_id:
            return None

        confluence = ConfluenceConnector(settings=self._settings)
        try:
            # Get Charter page with ancestors
            page = await confluence.get_page(
                project.confluence_charter_id, expand=["ancestors"]
            )
            ancestors = page.get("ancestors", [])
            if not ancestors:
                return None

            # The program page is the grandparent of the Charter
            # Charter → Projects/Releases → Program
            # CEO Review is a direct child of Program
            program_id = None
            if len(ancestors) >= 2:
                program_id = str(ancestors[-2]["id"])
            elif len(ancestors) >= 1:
                program_id = str(ancestors[-1]["id"])

            if not program_id:
                return None

            # Scan program children for "CEO Review"
            children = await confluence.get_child_pages_v2(program_id)
            for child in children:
                title = child.get("title", "")
                if "CEO Review" in title:
                    return str(child["id"])

            return None
        except Exception as exc:
            logger.warning("CEO review: failed to discover page: %s", exc)
            return None
        finally:
            await confluence.close()
