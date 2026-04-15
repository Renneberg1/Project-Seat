"""Charter service — fetch sections, LLM Q&A, edit proposals, suggestion management."""

from __future__ import annotations

import json
import logging
from typing import Any

from src.config import Settings, settings as default_settings
from src.connectors.jira import JiraConnector
from src.engine.mentions import resolve_confluence_mentions, resolve_confluence_page_links
from src.models.charter import CharterSuggestion, CharterSuggestionStatus

logger = logging.getLogger(__name__)


class CharterService:
    """Manage Charter section display, LLM-powered updates, and suggestions."""

    def __init__(
        self,
        db_path: str | None = None,
        settings: Settings | None = None,
        charter_repo: "CharterRepository | None" = None,
    ) -> None:
        self._settings = settings or default_settings
        self._db_path = db_path or self._settings.db_path

        from src.repositories.charter_repo import CharterRepository
        self._repo = charter_repo or CharterRepository(self._db_path)

    # ------------------------------------------------------------------
    # Fetch Charter sections
    # ------------------------------------------------------------------

    async def fetch_charter_sections(
        self, project: Any
    ) -> list[dict[str, str]]:
        """Fetch the Charter page from Confluence and extract sections.

        Returns a list of ``{name, content}`` dicts. Confluence user mentions
        are resolved to ``@DisplayName`` so the LLM can see who is assigned to
        fields like Project Manager / Executive Sponsor instead of an empty
        string.
        """
        import asyncio
        from src.connectors.confluence import ConfluenceConnector
        from src.engine.charter_storage_utils import (
            extract_sections,
            extract_user_placeholders,
            replace_user_placeholders,
        )

        if not project.confluence_charter_id:
            return []

        confluence = ConfluenceConnector(settings=self._settings)
        try:
            page = await confluence.get_page(
                project.confluence_charter_id, expand=["body.storage"]
            )
            body = page.get("body", {}).get("storage", {}).get("value", "")
            sections = extract_sections(body)

            # Resolve {{USER:<account-id>}} placeholders to @DisplayName
            account_ids = extract_user_placeholders(sections)
            if account_ids:
                names = await asyncio.gather(
                    *(confluence.get_user_display_name(aid) for aid in account_ids),
                    return_exceptions=True,
                )
                id_to_name = {
                    aid: name
                    for aid, name in zip(account_ids, names)
                    if isinstance(name, str) and name and name != aid
                }
                sections = replace_user_placeholders(sections, id_to_name)

            return sections
        finally:
            await confluence.close()

    # ------------------------------------------------------------------
    # LLM Step 1: Generate questions
    # ------------------------------------------------------------------

    async def _gather_charter_context(self, project: Any) -> dict[str, str]:
        """Gather rich project context for Charter LLM calls."""
        from src.services.project_context import ProjectContextService

        ctx_service = ProjectContextService(
            db_path=self._db_path, settings=self._settings,
        )
        data = await ctx_service.gather(
            project,
            risks=True, decisions=True,
            summary=True, initiatives=True, pi=True,
            goal_metadata=True, xft=True,
            team_reports=True,
            meeting_summaries=True, meeting_summary_limit=5,
            action_items=True, knowledge=True,
            cache_key=f"ctx:charter:{project.id}",
            cache_ttl=600,
        )

        ctx: dict[str, str] = {"project_name": project.name}

        # Build a concise project state summary for the LLM
        parts: list[str] = []

        # --- Project identifiers + release info ---
        parts.append(f"Project ID (local): {project.id}")
        parts.append(f"Jira Goal key: {project.jira_goal_key}")
        if project.pi_version:
            parts.append(
                f"Release / version: {project.pi_version} "
                f"(ideas board: {project.pi_project_key or 'PI'})"
            )
        if project.confluence_charter_id:
            parts.append(f"Confluence Charter page ID: {project.confluence_charter_id}")
        if project.confluence_xft_id:
            parts.append(f"Confluence XFT page ID: {project.confluence_xft_id}")

        # --- Goal (full info including description) ---
        if data.summary and data.summary.goal:
            g = data.summary.goal
            parts.append(f"Goal: {g.key} — {g.summary} (status: {g.status}, due: {g.due_date})")
            if g.fix_versions:
                parts.append(f"  Fix versions: {', '.join(g.fix_versions)}")
            if g.description_adf:
                desc = ProjectContextService._extract_adf_text(g.description_adf).strip()
                if desc:
                    parts.append(f"  Goal description: {desc[:1500]}")
            parts.append(f"Risks: {data.summary.open_risk_count} open / {data.summary.risk_count} total")
            parts.append(f"Decisions: {data.summary.decision_count} total")

        if data.goal_labels:
            parts.append(f"Goal labels: {', '.join(data.goal_labels)}")
        if data.goal_components:
            parts.append(f"Goal components: {', '.join(data.goal_components)}")

        # --- Product ideas / features list (the "feature backlog") ---
        if data.product_ideas:
            parts.append(
                f"Product ideas / features ({len(data.product_ideas)} items "
                f"on board {project.pi_project_key or 'PI'}, version {project.pi_version}):"
            )
            # Group by priority for readability
            by_priority: dict[str, list] = {}
            for idea in data.product_ideas:
                key = idea.release_priority or "Unprioritised"
                by_priority.setdefault(key, []).append(idea)
            # Order: Must Have / Now first, then others
            priority_order = ["Must Have", "Now", "Should Have", "Next",
                              "Could Have", "Later", "Nice to Have", "Unprioritised"]
            ordered_keys = sorted(
                by_priority.keys(),
                key=lambda k: priority_order.index(k) if k in priority_order else 99,
            )
            for prio in ordered_keys:
                ideas = by_priority[prio]
                parts.append(f"  [{prio}] ({len(ideas)} items):")
                for idea in ideas[:15]:  # cap per group
                    state = f" — {idea.pi_state}" if idea.pi_state else ""
                    parts.append(
                        f"    - [{idea.key}] {idea.summary} "
                        f"({idea.issue_type}, status: {idea.status}{state})"
                    )
                if len(ideas) > 15:
                    parts.append(f"    … and {len(ideas) - 15} more")

        if data.existing_risks:
            parts.append("Open risks:")
            for r in data.existing_risks[:10]:
                parts.append(f"  - [{r.get('key', '?')}] {r.get('summary', '')}")

        if data.existing_decisions:
            parts.append("Recent decisions:")
            for d in data.existing_decisions[:10]:
                parts.append(f"  - [{d.get('key', '?')}] {d.get('summary', '')}")

        if data.initiatives:
            parts.append("Initiatives:")
            for i in data.initiatives:
                parts.append(
                    f"  - {i.issue.key}: {i.issue.summary} "
                    f"({i.done_task_count}/{i.task_count} tasks done)"
                )

        if data.team_reports:
            parts.append("Team progress:")
            for r in data.team_reports:
                parts.append(f"  - {r.team_key}: {r.pct_done_issues}% done ({r.sp_done}/{r.sp_total} SP)")

        if data.action_items:
            parts.append("Open action items:")
            for a in data.action_items[:5]:
                parts.append(f"  - {a.title} (owner: {a.owner})")

        if data.meeting_summaries:
            parts.append("Recent meetings:")
            for ms in data.meeting_summaries[:3]:
                parts.append(f"  - {ms.get('filename', '?')}: {ms.get('summary', '')[:150]}")

        # --- XFT page excerpt (cross-functional team, roles, dates often live here) ---
        if data.xft_content:
            # Strip HTML tags crudely for the LLM context
            import re
            xft_text = re.sub(r"<[^>]+>", " ", data.xft_content)
            xft_text = re.sub(r"\s+", " ", xft_text).strip()
            if xft_text:
                parts.append(f"XFT page excerpt: {xft_text[:1500]}")

        if parts:
            ctx["project_state"] = "\n".join(parts)

        return ctx

    async def generate_questions(
        self, project: Any, user_input: str
    ) -> list[dict[str, str]]:
        """Call the LLM to identify gaps in the user's description.

        Returns a list of question dicts with ``question``, ``section_name``,
        ``why_needed`` keys.
        """
        from src.engine.agent import CharterAgent, get_provider

        sections = await self.fetch_charter_sections(project)
        project_context = await self._gather_charter_context(project)

        provider = get_provider(self._settings.llm)
        agent = CharterAgent(provider)
        try:
            result = await agent.ask_questions(
                current_sections=sections,
                user_input=user_input,
                project_context=project_context,
            )
            from src.services.context_resolver import resolve_if_needed
            result = await resolve_if_needed(
                result, agent, self._settings, label="Charter questions",
            )
        finally:
            await provider.close()

        return result.get("questions", [])

    # ------------------------------------------------------------------
    # LLM Step 2: Propose edits
    # ------------------------------------------------------------------

    async def analyze_charter_update(
        self,
        project: Any,
        user_input: str,
        qa_pairs: list[dict[str, str]],
    ) -> list[CharterSuggestion]:
        """Call the LLM to propose section edits and store them as suggestions.

        Returns the list of created CharterSuggestion objects.
        """
        from src.engine.agent import CharterAgent, get_provider

        sections = await self.fetch_charter_sections(project)
        sections_by_name = {s["name"]: s["content"] for s in sections}
        project_context = await self._gather_charter_context(project)

        provider = get_provider(self._settings.llm)
        agent = CharterAgent(provider)
        try:
            result = await agent.propose_edits(
                current_sections=sections,
                user_input=user_input,
                qa_pairs=qa_pairs,
                project_context=project_context,
            )
            from src.services.context_resolver import resolve_if_needed
            result = await resolve_if_needed(
                result, agent, self._settings, label="Charter edits",
            )
        finally:
            await provider.close()

        summary = result.get("summary", "")
        edits = result.get("section_edits", [])

        suggestions: list[CharterSuggestion] = []
        for edit in edits:
            section_name = edit.get("section_name", "")
            proposed_text = edit.get("proposed_text", "")
            rationale = edit.get("rationale", "")
            confidence = edit.get("confidence", 0.5)
            current_text = sections_by_name.get(section_name, "")

            # Build the payload that will be used at accept time
            payload = {
                "page_id": project.confluence_charter_id,
                "section_replace_mode": True,
                "section_name": section_name,
                "new_content": proposed_text,
            }
            preview = (
                f"Section: {section_name}\n"
                f"Rationale: {rationale}\n"
                f"Proposed text: {proposed_text[:300]}"
            )

            sug_id = self._repo.insert_suggestion(
                project_id=project.id,
                section_name=section_name,
                current_text=current_text,
                proposed_text=proposed_text,
                rationale=rationale,
                confidence=confidence,
                proposed_payload=json.dumps(payload),
                proposed_preview=preview,
                analysis_summary=summary,
                status=CharterSuggestionStatus.PENDING.value,
            )

            sug = self._get_suggestion(sug_id)
            if sug:
                suggestions.append(sug)

        return suggestions

    # ------------------------------------------------------------------
    # Suggestion CRUD
    # ------------------------------------------------------------------

    def list_suggestions(self, project_id: int) -> list[CharterSuggestion]:
        """List all charter suggestions for a project, newest first."""
        return self._repo.list_suggestions(project_id)

    def _get_suggestion(self, suggestion_id: int) -> CharterSuggestion | None:
        return self._repo.get_suggestion(suggestion_id)

    def get_suggestion(self, suggestion_id: int) -> CharterSuggestion | None:
        return self._get_suggestion(suggestion_id)

    async def accept_suggestion(
        self, suggestion_id: int, project: Any
    ) -> CharterSuggestion | None:
        """Accept a suggestion and queue it for approval.

        Refreshes the page_id from current project data to prevent stale references.
        Resolves @mentions in proposed text to Confluence XHTML markup.
        """
        from src.engine.approval import ApprovalEngine
        from src.models.approval import ApprovalAction

        sug = self._get_suggestion(suggestion_id)
        if sug is None or sug.status != CharterSuggestionStatus.PENDING:
            return sug

        payload = json.loads(sug.proposed_payload)

        # Patch with current project data
        if not project.confluence_charter_id:
            raise ValueError(
                "Cannot accept: project has no Charter page configured."
            )
        payload["page_id"] = project.confluence_charter_id

        # Resolve @mentions + [page: Title] placeholders in the proposed content.
        # Both transform plain text into embedded XHTML, so if either fires we
        # flag raw_xhtml=True and do the <p>-wrapping ourselves.
        new_content = payload.get("new_content", "")
        jira = JiraConnector(settings=self._settings)
        from src.connectors.confluence import ConfluenceConnector
        confluence = ConfluenceConnector(settings=self._settings)
        try:
            resolved = await resolve_confluence_mentions(new_content, jira)
            resolved = await resolve_confluence_page_links(resolved, confluence)
        finally:
            await jira.close()
            await confluence.close()

        if resolved != new_content:
            # Content now contains XHTML markup — wrap lines in <p> tags
            paragraphs = [line.strip() for line in resolved.split("\n") if line.strip()]
            body_html = "".join(f"<p>{p}</p>" for p in paragraphs) if paragraphs else f"<p>{resolved}</p>"
            payload["new_content"] = body_html
            payload["raw_xhtml"] = True

        engine = ApprovalEngine(db_path=self._db_path)
        item_id = engine.propose(
            action_type=ApprovalAction.UPDATE_CONFLUENCE_PAGE,
            payload=payload,
            preview=sug.proposed_preview,
            context=f"Charter update: {sug.section_name}",
            project_id=sug.project_id,
        )

        self._repo.update_status(suggestion_id, CharterSuggestionStatus.QUEUED.value, item_id)

        return self._get_suggestion(suggestion_id)

    def reject_suggestion(self, suggestion_id: int) -> CharterSuggestion | None:
        """Reject a suggestion."""
        self._repo.update_status(suggestion_id, CharterSuggestionStatus.REJECTED.value)
        return self._get_suggestion(suggestion_id)

    async def accept_all_suggestions(
        self, project: Any
    ) -> list[int]:
        """Accept all pending charter suggestions for a project. Returns approval item IDs."""
        suggestions = self.list_suggestions(project.id)
        item_ids: list[int] = []
        for sug in suggestions:
            if sug.status == CharterSuggestionStatus.PENDING:
                result = await self.accept_suggestion(sug.id, project)
                if result and result.approval_item_id:
                    item_ids.append(result.approval_item_id)
        return item_ids
