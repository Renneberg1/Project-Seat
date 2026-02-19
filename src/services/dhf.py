"""DHF document tracking service — async port of eQMS client logic."""

from __future__ import annotations

import logging
import re

from src.config import Settings, settings as default_settings
from src.connectors.base import ConnectorError
from src.connectors.confluence import ConfluenceConnector
from src.models.dhf import DHFDocument, DHFSummary, DocumentStatus
from src.models.project import Project

logger = logging.getLogger(__name__)

_VERSION_RE = re.compile(r"\[V(\d+)\]")


def _parse_version(title: str) -> str | None:
    """Extract version string from a page title like 'Doc Name [V2]'."""
    match = _VERSION_RE.search(title)
    return match.group(1) if match else None


def _strip_version(title: str) -> str:
    """Remove the version suffix from a title for display."""
    return re.sub(r"\s*\[V\d+\]$", "", title).strip()


class DHFService:
    """Compares Draft and Released Confluence spaces to produce DHF status."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or default_settings

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_dhf_summary(self, project: Project) -> DHFSummary:
        """Lightweight document counts for the dashboard card."""
        if not project.dhf_draft_root_id or not project.dhf_released_root_id:
            return DHFSummary(
                total_count=0, released_count=0,
                draft_update_count=0, in_draft_count=0,
                error=None,
            )

        try:
            docs, _ = await self.get_dhf_table(project)
            released = sum(1 for d in docs if d.status == DocumentStatus.RELEASED)
            draft_update = sum(1 for d in docs if d.status == DocumentStatus.DRAFT_UPDATE)
            in_draft = sum(1 for d in docs if d.status == DocumentStatus.IN_DRAFT)
            return DHFSummary(
                total_count=len(docs),
                released_count=released,
                draft_update_count=draft_update,
                in_draft_count=in_draft,
            )
        except ConnectorError as exc:
            logger.warning("Failed to fetch DHF data for %s: %s", project.name, exc)
            return DHFSummary(
                total_count=0, released_count=0,
                draft_update_count=0, in_draft_count=0,
                error=str(exc),
            )

    async def get_dhf_table(
        self, project: Project
    ) -> tuple[list[DHFDocument], list[str]]:
        """Full DHF status table and list of unique areas.

        Raises ``ConnectorError`` on API failure (caller should handle).
        """
        connector = ConfluenceConnector(settings=self._settings)
        try:
            user_cache: dict[str, str] = {}
            draft_docs = await self._collect_documents(
                connector, project.dhf_draft_root_id, user_cache
            )
            released_docs = await self._collect_documents(
                connector, project.dhf_released_root_id, user_cache
            )
            rows = self._match_documents(draft_docs, released_docs)
            rows.sort(key=lambda d: (d.area, d.title))
            areas = sorted({d.area for d in rows})
            return rows, areas
        finally:
            await connector.close()

    # ------------------------------------------------------------------
    # Internal helpers (ported from eqms_client.py)
    # ------------------------------------------------------------------

    async def _collect_documents(
        self,
        connector: ConfluenceConnector,
        root_page_id: str,
        user_cache: dict[str, str],
    ) -> list[dict]:
        """Walk 2-level hierarchy (areas -> documents) under a DHF root page."""
        docs: list[dict] = []
        areas = await connector.get_child_pages_v2(root_page_id)

        for area in areas:
            area_title = area.get("title", "")
            area_id = area.get("id", "")
            children = await connector.get_child_pages_v2(area_id)

            for child in children:
                child_id = child.get("id", "")
                child_title = child.get("title", "")

                # SoftComply document ID for matching draft<->released
                doc_id = await self._get_document_id(connector, child_id)

                version = _parse_version(child_title)

                # Fetch v2 page for link and version metadata
                full_page = await connector.get_page_v2(child_id)
                ver = full_page.get("version", {})
                last_modified = ver.get("createdAt", "")

                author_name = await self._resolve_human_author(
                    connector, child_id, ver, user_cache
                )

                base_url = f"https://{connector._domain}.atlassian.net/wiki"
                webui = full_page.get("_links", {}).get("webui", "")
                page_url = f"{base_url}{webui}" if webui else ""

                docs.append({
                    "page_id": child_id,
                    "title": _strip_version(child_title),
                    "area": area_title,
                    "version": version,
                    "document_id": doc_id,
                    "last_modified": last_modified,
                    "author": author_name,
                    "page_url": page_url,
                })

        return docs

    @staticmethod
    async def _get_document_id(
        connector: ConfluenceConnector, page_id: str
    ) -> str | None:
        """Get the SoftComply documentId content property for a page."""
        prop = await connector.get_content_property(
            page_id, "sc-dm-document-metadata"
        )
        if prop:
            value = prop.get("value", {})
            if isinstance(value, dict):
                return value.get("documentId")
        return None

    @staticmethod
    async def _resolve_human_author(
        connector: ConfluenceConnector,
        page_id: str,
        current_version: dict,
        user_cache: dict[str, str],
    ) -> str:
        """Walk version history to find the most recent non-SoftComply author."""
        author_id = current_version.get("authorId", "")
        if author_id and author_id not in user_cache:
            user_cache[author_id] = await connector.get_user_display_name(author_id)

        # If current author is not SoftComply, return it
        if author_id and "softcomply" not in user_cache.get(author_id, "").lower():
            return user_cache.get(author_id, author_id)

        # Walk version history to find a human author
        versions = await connector.get_page_versions(page_id)
        for v in versions:
            vid = v.get("authorId", "")
            if vid and vid not in user_cache:
                user_cache[vid] = await connector.get_user_display_name(vid)
            if vid and "softcomply" not in user_cache.get(vid, "").lower():
                return user_cache.get(vid, vid)

        # All versions are SoftComply — return the latest display name
        return user_cache.get(author_id, author_id)

    @staticmethod
    def _match_documents(
        draft_docs: list[dict], released_docs: list[dict]
    ) -> list[DHFDocument]:
        """Match draft and released documents by documentId, classify status."""
        released_by_doc_id: dict[str, dict] = {}
        for doc in released_docs:
            if doc["document_id"]:
                released_by_doc_id[doc["document_id"]] = doc

        draft_by_doc_id: dict[str, dict] = {}
        draft_no_id: list[dict] = []
        for doc in draft_docs:
            if doc["document_id"]:
                draft_by_doc_id[doc["document_id"]] = doc
            else:
                draft_no_id.append(doc)

        all_doc_ids = set(released_by_doc_id.keys()) | set(draft_by_doc_id.keys())
        rows: list[DHFDocument] = []

        for doc_id in all_doc_ids:
            released = released_by_doc_id.get(doc_id)
            draft = draft_by_doc_id.get(doc_id)

            if released and draft:
                status = DocumentStatus.DRAFT_UPDATE
                source = draft
            elif released:
                status = DocumentStatus.RELEASED
                source = released
            else:
                status = DocumentStatus.IN_DRAFT
                source = draft

            rows.append(DHFDocument(
                title=source["title"],
                area=source["area"],
                released_version=released["version"] if released else None,
                draft_version=draft["version"] if draft else None,
                status=status,
                last_modified=source["last_modified"],
                author=source["author"],
                page_url=(draft or released)["page_url"],
            ))

        # Include draft docs that have no SoftComply document_id
        for doc in draft_no_id:
            rows.append(DHFDocument(
                title=doc["title"],
                area=doc["area"],
                released_version=None,
                draft_version=doc["version"],
                status=DocumentStatus.IN_DRAFT,
                last_modified=doc["last_modified"],
                author=doc["author"],
                page_url=doc["page_url"],
            ))

        return rows
