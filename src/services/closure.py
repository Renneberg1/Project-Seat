"""Closure Report service — gather full lifecycle data, LLM report, publish to Confluence."""

from __future__ import annotations

import json
import logging
from html import escape
from typing import Any

from src.config import Settings, settings as default_settings
from src.models.closure import ClosureReport, ClosureReportStatus
from src.models.project import Project

_CONTEXT_CACHE_TTL = 600  # 10 minutes

logger = logging.getLogger(__name__)


class ClosureService:
    """Orchestrate the LLM-powered project closure report workflow."""

    def __init__(
        self,
        db_path: str | None = None,
        settings: Settings | None = None,
        closure_repo: "ClosureReportRepository | None" = None,
    ) -> None:
        self._settings = settings or default_settings
        self._db_path = db_path or self._settings.db_path

        from src.repositories.closure_repo import ClosureReportRepository
        self._repo = closure_repo or ClosureReportRepository(self._db_path)

    # ------------------------------------------------------------------
    # Gather context (reuses ProjectContextService)
    # ------------------------------------------------------------------

    async def gather_closure_context(self, project: Project) -> dict[str, Any]:
        """Fetch all data needed for a closure report — full project lifecycle.

        Uses a 10-minute cache so Step 2 reuses context from Step 1.
        """
        from src.services.project_context import ProjectContextService

        ctx_service = ProjectContextService(
            db_path=self._db_path, settings=self._settings,
        )
        data = await ctx_service.gather(
            project,
            summary=True, initiatives=True,
            team_reports=True,
            snapshots=True, snapshot_days=365,
            dhf_docs=True, releases=True,
            risks_raw=True,
            decisions_raw=True,
            charter=True, xft=True,
            meeting_summaries=True, meeting_summary_limit=20,
            action_items=True, knowledge=True,
            cache_key=f"ctx:closure:{project.id}",
            cache_ttl=_CONTEXT_CACHE_TTL,
        )

        return {
            "project": project,
            "summary": data.summary,
            "initiatives": data.initiatives,
            "team_reports": data.team_reports,
            "snapshots": data.snapshots,
            "dhf_docs": data.dhf_docs,
            "releases": data.releases,
            "risks_raw": data.new_risks_raw,
            "decisions_raw": data.new_decisions_raw,
            "charter_content": data.charter_content,
            "xft_content": data.xft_content,
            "meeting_summaries": data.meeting_summaries,
            "action_items": data.action_items,
            "knowledge_entries": data.knowledge_entries,
        }

    # ------------------------------------------------------------------
    # Compute deterministic metrics from context
    # ------------------------------------------------------------------

    def compute_closure_metrics(self, context: dict[str, Any]) -> dict[str, Any]:
        """Extract deterministic metrics dict from gathered context."""
        from src.models.dhf import DocumentStatus

        project: Project = context["project"]
        summary = context.get("summary")

        metrics: dict[str, Any] = {
            "project_name": project.name,
            "phase": project.phase,
            "pm": "N/A",
            "sponsor": "N/A",
        }

        # Timeline info from goal
        if summary and summary.goal:
            metrics["timeline"] = {
                "planned_start": summary.goal.created or "N/A",
                "planned_end": summary.goal.due_date or "N/A",
                "actual_end": "TBD",
                "deviation": "N/A",
            }
        else:
            metrics["timeline"] = {}

        # All risks (full lifecycle)
        all_risks = []
        for raw in context.get("risks_raw", []):
            fields = raw.get("fields", {})
            components_raw = fields.get("components", [])
            components = ", ".join(c.get("name", "") for c in components_raw) if components_raw else ""
            status = fields.get("status", {})
            all_risks.append({
                "key": raw.get("key", "?"),
                "summary": fields.get("summary", "?"),
                "priority": fields.get("priority", {}).get("name", "?"),
                "status": status.get("name", "?"),
                "status_category": status.get("statusCategory", {}).get("name", "?"),
                "components": components,
            })
        metrics["all_risks"] = all_risks

        # All decisions (full lifecycle)
        all_decisions = []
        for raw in context.get("decisions_raw", []):
            fields = raw.get("fields", {})
            status = fields.get("status", {})
            all_decisions.append({
                "key": raw.get("key", "?"),
                "summary": fields.get("summary", "?"),
                "status": status.get("name", "?"),
                "status_category": status.get("statusCategory", {}).get("name", "?"),
            })
        metrics["all_decisions"] = all_decisions

        # Team progress (final state)
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

        # Scope — derived from initiatives (done vs not done)
        scope_delivered = []
        scope_not_delivered = []
        initiatives = context.get("initiatives", [])
        for init in initiatives:
            item = {
                "key": getattr(init, "key", "?"),
                "summary": getattr(init, "summary", "?"),
                "status": getattr(init, "status", "?"),
            }
            status_name = getattr(init, "status", "")
            if status_name and status_name.lower() in ("done", "closed", "released", "resolved"):
                scope_delivered.append(item)
            else:
                scope_not_delivered.append(item)
        metrics["scope_delivered"] = scope_delivered
        metrics["scope_not_delivered"] = scope_not_delivered

        # DHF documents
        dhf_docs = context.get("dhf_docs", [])
        dhf_total = len(dhf_docs)
        dhf_released = sum(1 for d in dhf_docs if d.status == DocumentStatus.RELEASED)
        dhf_pct = round(100 * dhf_released / dhf_total) if dhf_total else 0
        metrics["dhf_total"] = dhf_total
        metrics["dhf_released"] = dhf_released
        metrics["dhf_completion_pct"] = dhf_pct

        # Releases
        metrics["releases"] = context.get("releases", [])

        # Action items and knowledge (for lessons learned context)
        action_items = context.get("action_items", [])
        if action_items:
            metrics["action_items"] = [
                {"title": a.title, "owner": a.owner_name, "status": a.status}
                for a in action_items
            ]
        knowledge_entries = context.get("knowledge_entries", [])
        if knowledge_entries:
            metrics["knowledge_entries"] = [
                {"title": e.title, "type": e.entry_type}
                for e in knowledge_entries[:15]
            ]

        # Meeting summaries (already available, pass through for narrative context)
        metrics["meeting_summaries"] = [
            {"filename": ms.get("filename", ""), "summary": ms.get("summary", "")[:300]}
            for ms in context.get("meeting_summaries", [])[:10]
        ]

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
        from src.engine.agent import ClosureAgent, get_provider

        context = await self.gather_closure_context(project)
        metrics = self.compute_closure_metrics(context)

        provider = get_provider(self._settings.llm)
        agent = ClosureAgent(provider)
        try:
            result = await agent.ask_questions(metrics, pm_notes)
            from src.services.context_resolver import resolve_if_needed
            result = await resolve_if_needed(
                result, agent, self._settings, label="Closure questions",
            )
        finally:
            await provider.close()

        return result.get("questions", []), metrics

    # ------------------------------------------------------------------
    # LLM Step 2: Generate report
    # ------------------------------------------------------------------

    async def generate_report(
        self,
        project: Project,
        pm_notes: str,
        qa_pairs: list[dict[str, str]],
    ) -> dict[str, Any]:
        """Gather context, compute metrics, produce the closure report.

        Returns the merged report dict (LLM narrative + pre-computed metrics).
        """
        from src.engine.agent import ClosureAgent, get_provider

        context = await self.gather_closure_context(project)
        metrics = self.compute_closure_metrics(context)

        provider = get_provider(self._settings.llm)
        agent = ClosureAgent(provider)
        try:
            result = await agent.generate_report(metrics, pm_notes, qa_pairs)
            from src.services.context_resolver import resolve_if_needed
            result = await resolve_if_needed(
                result, agent, self._settings, label="Closure report",
            )
        finally:
            await provider.close()

        # Merge pre-computed metrics into the report for template rendering
        result["metrics"] = metrics
        return result

    # ------------------------------------------------------------------
    # Confluence XHTML rendering
    # ------------------------------------------------------------------

    def render_confluence_xhtml(self, report_data: dict[str, Any]) -> str:
        """Build Confluence storage-format XHTML for the closure report page."""
        metrics = report_data.get("metrics", {})
        project_name = escape(metrics.get("project_name", "Unknown"))

        parts: list[str] = []

        # Header table
        pm = escape(metrics.get("pm", "N/A"))
        sponsor = escape(metrics.get("sponsor", "N/A"))
        parts.append("<h2>Project Details</h2>")
        parts.append("<table><tbody>")
        parts.append(f"<tr><th>Project Name</th><td>{project_name}</td></tr>")
        parts.append(f"<tr><th>Project Manager</th><td>{pm}</td></tr>")
        parts.append(f"<tr><th>Executive Sponsor</th><td>{sponsor}</td></tr>")
        parts.append(f"<tr><th>Phase</th><td>{escape(metrics.get('phase', 'N/A'))}</td></tr>")
        parts.append("</tbody></table>")

        # Final Delivery Outcome
        outcome = report_data.get("final_delivery_outcome", "")
        parts.append("<h2>Final Delivery Outcome</h2>")
        if outcome:
            parts.append(f"<p>{escape(outcome)}</p>")

        # Timeline table
        timeline = metrics.get("timeline", {})
        if timeline:
            parts.append("<h2>Project Timeline</h2>")
            parts.append("<table><thead><tr><th>Milestone</th><th>Planned</th><th>Actual</th><th>Deviation</th></tr></thead><tbody>")
            parts.append(
                f"<tr><td>Project Completion</td>"
                f"<td>{escape(str(timeline.get('planned_end', 'N/A')))}</td>"
                f"<td>{escape(str(timeline.get('actual_end', 'TBD')))}</td>"
                f"<td>{escape(str(timeline.get('deviation', 'N/A')))}</td></tr>"
            )
            parts.append("</tbody></table>")

        # Scope Delivered
        scope_delivered = metrics.get("scope_delivered", [])
        scope_not_delivered = metrics.get("scope_not_delivered", [])
        parts.append("<h2>Scope Delivered</h2>")
        parts.append("<h3>In Scope — Delivered</h3>")
        if scope_delivered:
            parts.append("<ul>")
            for item in scope_delivered:
                parts.append(f"<li>{escape(item.get('key', '?'))}: {escape(item.get('summary', '?'))}</li>")
            parts.append("</ul>")
        else:
            parts.append("<p>No scope items marked as delivered.</p>")

        parts.append("<h3>In Scope — Not Delivered</h3>")
        if scope_not_delivered:
            parts.append("<ul>")
            for item in scope_not_delivered:
                parts.append(f"<li>{escape(item.get('key', '?'))}: {escape(item.get('summary', '?'))} [{escape(item.get('status', '?'))}]</li>")
            parts.append("</ul>")
        else:
            parts.append("<p>All scope items were delivered.</p>")

        # Success Criteria
        criteria = report_data.get("success_criteria_assessments", [])
        if criteria:
            parts.append("<h2>Performance Against Success Criteria</h2>")
            parts.append(
                "<table><thead><tr>"
                "<th>Criterion</th><th>Expected</th><th>Actual</th><th>Status</th><th>Comments</th>"
                "</tr></thead><tbody>"
            )
            for c in criteria:
                status = escape(c.get("status", "?"))
                parts.append(
                    f"<tr>"
                    f"<td>{escape(c.get('criterion', '?'))}</td>"
                    f"<td>{escape(c.get('expected_outcome', '?'))}</td>"
                    f"<td>{escape(c.get('actual_performance', '?'))}</td>"
                    f"<td>{status}</td>"
                    f"<td>{escape(c.get('comments', ''))}</td>"
                    f"</tr>"
                )
            parts.append("</tbody></table>")

        # Risks table
        all_risks = metrics.get("all_risks", [])
        if all_risks:
            parts.append("<h2>Risks &amp; Issues Closure</h2>")
            parts.append(
                "<table><thead><tr>"
                "<th>ID</th><th>Description</th><th>Priority</th><th>Status</th><th>Components</th>"
                "</tr></thead><tbody>"
            )
            for r in all_risks:
                parts.append(
                    f"<tr>"
                    f"<td>{escape(r.get('key', '?'))}</td>"
                    f"<td>{escape(r.get('summary', '?'))}</td>"
                    f"<td>{escape(r.get('priority', '?'))}</td>"
                    f"<td>{escape(r.get('status', '?'))}</td>"
                    f"<td>{escape(r.get('components', ''))}</td>"
                    f"</tr>"
                )
            parts.append("</tbody></table>")

        # Decisions table
        all_decisions = metrics.get("all_decisions", [])
        if all_decisions:
            parts.append("<h3>Decisions</h3>")
            parts.append(
                "<table><thead><tr>"
                "<th>ID</th><th>Description</th><th>Status</th>"
                "</tr></thead><tbody>"
            )
            for d in all_decisions:
                parts.append(
                    f"<tr>"
                    f"<td>{escape(d.get('key', '?'))}</td>"
                    f"<td>{escape(d.get('summary', '?'))}</td>"
                    f"<td>{escape(d.get('status', '?'))}</td>"
                    f"</tr>"
                )
            parts.append("</tbody></table>")

        # Lessons Learned
        lessons = report_data.get("lessons_learned", [])
        if lessons:
            parts.append("<h2>Lessons Learned</h2>")
            parts.append(
                "<table><thead><tr>"
                "<th>Category</th><th>Description</th><th>Effect / Triggers</th>"
                "<th>Recommendations</th><th>Owner</th>"
                "</tr></thead><tbody>"
            )
            for ll in lessons:
                parts.append(
                    f"<tr>"
                    f"<td>{escape(ll.get('category', '?'))}</td>"
                    f"<td>{escape(ll.get('description', '?'))}</td>"
                    f"<td>{escape(ll.get('effect_triggers', ''))}</td>"
                    f"<td>{escape(ll.get('recommendations', ''))}</td>"
                    f"<td>{escape(ll.get('owner', ''))}</td>"
                    f"</tr>"
                )
            parts.append("</tbody></table>")

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_report(self, project_id: int, report: dict[str, Any], xhtml: str) -> int:
        """Persist a closure report and return its ID."""
        return self._repo.insert(project_id, json.dumps(report), xhtml, ClosureReportStatus.DRAFT.value)

    def accept_report(self, report_id: int, project: Project) -> ClosureReport | None:
        """Accept a report and queue it for approval (create Confluence page)."""
        from src.engine.approval import ApprovalEngine
        from src.models.approval import ApprovalAction

        report = self.get_report(report_id)
        if report is None or report.status != ClosureReportStatus.DRAFT:
            return report

        parent_id = project.confluence_charter_id
        if not parent_id:
            raise ValueError(
                "Cannot publish: no Charter page configured. "
                "Set the Charter page ID in Project Settings."
            )

        payload = {
            "space_key": self._settings.atlassian.confluence_space_key,
            "title": f"{project.name} Closure Report",
            "body_storage": report.confluence_body,
            "parent_id": parent_id,
        }

        engine = ApprovalEngine(db_path=self._db_path)
        item_id = engine.propose(
            action_type=ApprovalAction.CREATE_CONFLUENCE_PAGE,
            payload=payload,
            preview=f"Create Closure Report page under Charter for {project.name}",
            context=f"Closure Report for {project.name}",
            project_id=project.id,
        )

        self._repo.update_status(report_id, ClosureReportStatus.QUEUED.value, item_id)

        return self.get_report(report_id)

    def reject_report(self, report_id: int) -> ClosureReport | None:
        """Reject a closure report."""
        self._repo.update_status(report_id, ClosureReportStatus.REJECTED.value)
        return self.get_report(report_id)

    def list_reports(self, project_id: int) -> list[ClosureReport]:
        """Return recent closure reports (last 10), newest first."""
        return self._repo.list_reports(project_id)

    def get_report(self, report_id: int) -> ClosureReport | None:
        """Fetch a single closure report by ID."""
        return self._repo.get_report(report_id)
