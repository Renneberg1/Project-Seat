"""Knowledge service — action items and knowledge entries from transcript analysis."""

from __future__ import annotations

import logging
from typing import Any

import src.config
from src.config import Settings
from src.models.knowledge import ActionItem, KnowledgeEntry

logger = logging.getLogger(__name__)


class KnowledgeService:
    """Manage project knowledge extracted from transcripts and manually added."""

    def __init__(
        self,
        db_path: str | None = None,
        settings: Settings | None = None,
        knowledge_repo: "KnowledgeRepository | None" = None,
    ) -> None:
        self._settings = settings or src.config.settings
        self._db_path = db_path or self._settings.db_path

        from src.repositories.knowledge_repo import KnowledgeRepository
        self._repo = knowledge_repo or KnowledgeRepository(self._db_path)

    # ------------------------------------------------------------------
    # Store from LLM analysis
    # ------------------------------------------------------------------

    def store_from_analysis(
        self,
        project_id: int,
        transcript_id: int,
        suggestions: list[dict[str, Any]],
    ) -> dict[str, int]:
        """Route action_item/note/insight suggestions to the knowledge DB.

        Returns counts of items stored by type.
        """
        counts = {"action_items": 0, "notes": 0, "insights": 0}

        for sug in suggestions:
            sug_type = sug.get("type", "")

            if sug_type == "action_item":
                self._repo.insert_action_item(
                    project_id=project_id,
                    transcript_id=transcript_id,
                    title=sug.get("title", "Untitled"),
                    owner=sug.get("owner_name", ""),
                    due_date=sug.get("due_date_hint", None) or None,
                    source="transcript",
                    evidence=sug.get("evidence", ""),
                )
                counts["action_items"] += 1

            elif sug_type in ("note", "insight"):
                self._repo.insert_knowledge_entry(
                    project_id=project_id,
                    transcript_id=transcript_id,
                    entry_type=sug_type,
                    title=sug.get("title", "Untitled"),
                    content=sug.get("background", "") or sug.get("confluence_content", ""),
                    tags=sug.get("tags", []),
                    source="transcript",
                )
                counts["notes" if sug_type == "note" else "insights"] += 1

        return counts

    # ------------------------------------------------------------------
    # Action items
    # ------------------------------------------------------------------

    def list_action_items(
        self, project_id: int, status: str | None = None,
    ) -> list[ActionItem]:
        return self._repo.list_action_items(project_id, status)

    def update_action_item_status(self, item_id: int, status: str) -> None:
        self._repo.update_action_item_status(item_id, status)

    def add_action_item(
        self,
        project_id: int,
        title: str,
        owner: str = "",
        due_date: str | None = None,
    ) -> int:
        return self._repo.insert_action_item(
            project_id=project_id,
            title=title,
            owner=owner,
            due_date=due_date,
            source="manual",
        )

    def get_action_item(self, item_id: int) -> ActionItem | None:
        return self._repo.get_action_item(item_id)

    def count_action_items(self, project_id: int) -> dict[str, int]:
        return self._repo.count_action_items(project_id)

    # ------------------------------------------------------------------
    # Knowledge entries
    # ------------------------------------------------------------------

    def list_knowledge_entries(
        self, project_id: int, entry_type: str | None = None,
    ) -> list[KnowledgeEntry]:
        return self._repo.list_knowledge_entries(project_id, entry_type)

    def get_knowledge_entry(self, entry_id: int) -> KnowledgeEntry | None:
        return self._repo.get_knowledge_entry(entry_id)

    def search_knowledge(
        self, project_id: int, query: str,
    ) -> list[KnowledgeEntry]:
        return self._repo.search_knowledge(project_id, query)

    def add_knowledge_entry(
        self,
        project_id: int,
        entry_type: str,
        title: str,
        content: str = "",
        tags: list[str] | None = None,
    ) -> int:
        return self._repo.insert_knowledge_entry(
            project_id=project_id,
            entry_type=entry_type,
            title=title,
            content=content,
            tags=tags,
            source="manual",
        )

    # ------------------------------------------------------------------
    # Confluence publish
    # ------------------------------------------------------------------

    async def publish_to_confluence(
        self, entry_id: int, project: Any,
    ) -> int | None:
        """Queue a knowledge entry for Confluence publish via approval engine."""
        from src.engine.approval import ApprovalEngine
        from src.models.approval import ApprovalAction

        entry = self._repo.get_knowledge_entry(entry_id)
        if entry is None:
            return None

        page_id = project.confluence_xft_id
        if not page_id:
            raise ValueError("Project has no XFT Confluence page configured")

        from datetime import date
        from html import escape as _html_escape
        today = date.today().isoformat()
        escaped_content = _html_escape(entry.content, quote=True)
        paragraphs = [line.strip() for line in escaped_content.split("\n") if line.strip()]
        body_html = "".join(f"<p>{p}</p>" for p in paragraphs) if paragraphs else f"<p>{escaped_content}</p>"
        append_html = f"<h2>{entry.title} — {today}</h2>{body_html}"

        payload = {
            "page_id": page_id,
            "title": None,
            "append_mode": True,
            "append_content": append_html,
        }

        engine = ApprovalEngine(db_path=self._db_path)
        item_id = engine.propose(
            action_type=ApprovalAction.UPDATE_CONFLUENCE_PAGE,
            payload=payload,
            preview=f"Publish knowledge entry: {entry.title}",
            context=f"Knowledge entry #{entry.id}: {entry.title}",
            project_id=entry.project_id,
        )

        self._repo.update_published(entry_id, item_id)
        return item_id
