"""Zoom meeting-to-project matching — hybrid title match + LLM fallback."""

from __future__ import annotations

import difflib
import json
import logging
import re
from typing import Any

import src.config
from src.config import Settings
from src.models.zoom import ZoomRecording

logger = logging.getLogger(__name__)


class ZoomMatchingService:
    """Match Zoom recordings to projects via title matching and LLM fallback."""

    def __init__(
        self,
        db_path: str | None = None,
        settings: Settings | None = None,
        zoom_repo: "ZoomRepository | None" = None,
    ) -> None:
        self._settings = settings or src.config.settings
        self._db_path = db_path or self._settings.db_path

        from src.repositories.zoom_repo import ZoomRepository
        self._repo = zoom_repo or ZoomRepository(self._db_path)

        self.last_match_method: str | None = None

    async def match_recording(
        self,
        recording: ZoomRecording,
        transcript_excerpt: str = "",
    ) -> list[int]:
        """Match a recording to project(s). Returns list of project IDs.

        Step 1: Title match (free, fast)
        Step 2: LLM classification (only if title match fails)
        """
        # Load active projects
        projects = self._load_active_projects()
        if not projects:
            return []

        # Step 1: Title-based matching
        title_matches = self._title_match(recording.topic, projects)
        if title_matches:
            self.last_match_method = "title"
            return title_matches

        # Step 2: LLM classification
        if transcript_excerpt:
            llm_matches = await self._llm_match(
                recording.topic,
                recording.host_email,
                transcript_excerpt,
                projects,
            )
            if llm_matches:
                self.last_match_method = "llm"
                return llm_matches

        self.last_match_method = None
        return []

    # ------------------------------------------------------------------
    # Title matching
    # ------------------------------------------------------------------

    def _title_match(
        self, topic: str, projects: list[dict[str, Any]],
    ) -> list[int]:
        """Match meeting topic against project names, aliases, and team keys."""
        topic_norm = self._normalize(topic)
        matched: list[int] = []

        for p in projects:
            candidates = [self._normalize(p["name"])]
            candidates.extend(self._normalize(a) for a in p.get("aliases", []))
            candidates.extend(self._normalize(k) for k in p.get("team_keys", []))

            for candidate in candidates:
                if not candidate:
                    continue
                # Exact substring match
                if candidate in topic_norm:
                    if p["id"] not in matched:
                        matched.append(p["id"])
                    break
                # Fuzzy match (for project names)
                if len(candidate) >= 4:
                    ratio = difflib.SequenceMatcher(None, candidate, topic_norm).ratio()
                    if ratio >= 0.7:
                        if p["id"] not in matched:
                            matched.append(p["id"])
                        break

        return matched

    @staticmethod
    def _normalize(text: str) -> str:
        """Normalize for comparison: lowercase, strip punctuation."""
        return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()

    # ------------------------------------------------------------------
    # LLM classification
    # ------------------------------------------------------------------

    async def _llm_match(
        self,
        topic: str,
        host_email: str,
        transcript_excerpt: str,
        projects: list[dict[str, Any]],
    ) -> list[int]:
        """Use LLM to classify the meeting when title match fails."""
        from src.engine.agent import ZoomMatchAgent, get_provider

        provider = get_provider(self._settings.llm)
        agent = ZoomMatchAgent(provider)
        try:
            result = await agent.classify_meeting(
                topic=topic,
                host_email=host_email,
                transcript_excerpt=transcript_excerpt,
                active_projects=projects,
            )
        finally:
            await provider.close()

        matched: list[int] = []
        for m in result.get("matches", []):
            if m.get("confidence", 0) >= 0.7:
                pid = int(m["project_id"])
                # Validate that the project ID is in our list
                if any(p["id"] == pid for p in projects):
                    matched.append(pid)

        return matched

    # ------------------------------------------------------------------
    # Project loading
    # ------------------------------------------------------------------

    def _load_active_projects(self) -> list[dict[str, Any]]:
        """Load all active projects with names, aliases, and team keys."""
        from src.services.dashboard import DashboardService
        dash = DashboardService(db_path=self._db_path, settings=self._settings)
        all_projects = dash.list_projects()

        all_aliases = self._repo.get_all_aliases()

        result: list[dict[str, Any]] = []
        for p in all_projects:
            if p.status != "active":
                continue
            team_keys = [pair[0] for pair in (p.team_projects or [])]
            result.append({
                "id": p.id,
                "name": p.name,
                "team_keys": team_keys,
                "aliases": all_aliases.get(p.id, []),
            })
        return result
