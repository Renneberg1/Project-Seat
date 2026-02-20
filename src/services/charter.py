"""Charter service — fetch sections, LLM Q&A, edit proposals, suggestion management."""

from __future__ import annotations

import json
import logging
from typing import Any

from src.config import Settings, settings as default_settings
from src.database import get_db
from src.models.charter import CharterSuggestion, CharterSuggestionStatus

logger = logging.getLogger(__name__)


class CharterService:
    """Manage Charter section display, LLM-powered updates, and suggestions."""

    def __init__(
        self,
        db_path: str | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._settings = settings or default_settings
        self._db_path = db_path or self._settings.db_path

    # ------------------------------------------------------------------
    # Fetch Charter sections
    # ------------------------------------------------------------------

    async def fetch_charter_sections(
        self, project: Any
    ) -> list[dict[str, str]]:
        """Fetch the Charter page from Confluence and extract sections.

        Returns a list of ``{name, content}`` dicts.
        """
        from src.connectors.confluence import ConfluenceConnector
        from src.engine.charter_storage_utils import extract_sections

        if not project.confluence_charter_id:
            return []

        confluence = ConfluenceConnector(settings=self._settings)
        try:
            page = await confluence.get_page(
                project.confluence_charter_id, expand=["body.storage"]
            )
        finally:
            await confluence.close()

        body = page.get("body", {}).get("storage", {}).get("value", "")
        return extract_sections(body)

    # ------------------------------------------------------------------
    # LLM Step 1: Generate questions
    # ------------------------------------------------------------------

    async def generate_questions(
        self, project: Any, user_input: str
    ) -> list[dict[str, str]]:
        """Call the LLM to identify gaps in the user's description.

        Returns a list of question dicts with ``question``, ``section_name``,
        ``why_needed`` keys.
        """
        from src.engine.agent import CharterAgent, get_provider

        sections = await self.fetch_charter_sections(project)
        project_context = {"project_name": project.name}

        provider = get_provider(self._settings.llm)
        agent = CharterAgent(provider)
        try:
            result = await agent.ask_questions(
                current_sections=sections,
                user_input=user_input,
                project_context=project_context,
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
        project_context = {"project_name": project.name}

        provider = get_provider(self._settings.llm)
        agent = CharterAgent(provider)
        try:
            result = await agent.propose_edits(
                current_sections=sections,
                user_input=user_input,
                qa_pairs=qa_pairs,
                project_context=project_context,
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

            with get_db(self._db_path) as conn:
                cursor = conn.execute(
                    """INSERT INTO charter_suggestions
                       (project_id, section_name, current_text, proposed_text,
                        rationale, confidence, proposed_payload, proposed_preview,
                        analysis_summary, status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        project.id,
                        section_name,
                        current_text,
                        proposed_text,
                        rationale,
                        confidence,
                        json.dumps(payload),
                        preview,
                        summary,
                        CharterSuggestionStatus.PENDING.value,
                    ),
                )
                conn.commit()
                sug_id = cursor.lastrowid

            sug = self._get_suggestion(sug_id)
            if sug:
                suggestions.append(sug)

        return suggestions

    # ------------------------------------------------------------------
    # Suggestion CRUD
    # ------------------------------------------------------------------

    def list_suggestions(self, project_id: int) -> list[CharterSuggestion]:
        """List all charter suggestions for a project, newest first."""
        with get_db(self._db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM charter_suggestions WHERE project_id = ? ORDER BY id DESC",
                (project_id,),
            ).fetchall()
        return [CharterSuggestion.from_row(r) for r in rows]

    def _get_suggestion(self, suggestion_id: int) -> CharterSuggestion | None:
        with get_db(self._db_path) as conn:
            row = conn.execute(
                "SELECT * FROM charter_suggestions WHERE id = ?",
                (suggestion_id,),
            ).fetchone()
        return CharterSuggestion.from_row(row) if row else None

    def get_suggestion(self, suggestion_id: int) -> CharterSuggestion | None:
        return self._get_suggestion(suggestion_id)

    def accept_suggestion(
        self, suggestion_id: int, project: Any
    ) -> CharterSuggestion | None:
        """Accept a suggestion and queue it for approval.

        Refreshes the page_id from current project data to prevent stale references.
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

        engine = ApprovalEngine(db_path=self._db_path)
        item_id = engine.propose(
            action_type=ApprovalAction.UPDATE_CONFLUENCE_PAGE,
            payload=payload,
            preview=sug.proposed_preview,
            context=f"Charter update: {sug.section_name}",
            project_id=sug.project_id,
        )

        with get_db(self._db_path) as conn:
            conn.execute(
                "UPDATE charter_suggestions SET status = ?, approval_item_id = ? WHERE id = ?",
                (CharterSuggestionStatus.QUEUED.value, item_id, suggestion_id),
            )
            conn.commit()

        return self._get_suggestion(suggestion_id)

    def reject_suggestion(self, suggestion_id: int) -> CharterSuggestion | None:
        """Reject a suggestion."""
        with get_db(self._db_path) as conn:
            conn.execute(
                "UPDATE charter_suggestions SET status = ? WHERE id = ?",
                (CharterSuggestionStatus.REJECTED.value, suggestion_id),
            )
            conn.commit()
        return self._get_suggestion(suggestion_id)

    def accept_all_suggestions(
        self, project: Any
    ) -> list[int]:
        """Accept all pending charter suggestions for a project. Returns approval item IDs."""
        suggestions = self.list_suggestions(project.id)
        item_ids: list[int] = []
        for sug in suggestions:
            if sug.status == CharterSuggestionStatus.PENDING:
                result = self.accept_suggestion(sug.id, project)
                if result and result.approval_item_id:
                    item_ids.append(result.approval_item_id)
        return item_ids
