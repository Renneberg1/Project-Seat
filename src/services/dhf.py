"""DHF document tracking service — async port of eQMS client logic."""

from __future__ import annotations

import asyncio
import logging
import re

from src.cache import cache
from src.config import Settings, settings as default_settings
from src.connectors.base import ConnectorError
from src.connectors.confluence import ConfluenceConnector
from src.models.dhf import DHFDocument, DHFSummary, DocumentStatus
from src.models.project import Project

logger = logging.getLogger(__name__)

_VERSION_RE = re.compile(r"\[V(\d+)\]")

# Limit concurrent Confluence API calls to avoid rate-limiting.
# Atlassian Cloud allows ~100 req/s; 20 concurrent keeps us well within limits.
_CONFLUENCE_SEM = asyncio.Semaphore(20)


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

        Results are cached for 120 seconds.
        Raises ``ConnectorError`` on API failure (caller should handle).
        """
        if not project.dhf_draft_root_id or not project.dhf_released_root_id:
            return ([], [])

        cache_key = f"dhf:{project.dhf_draft_root_id}:{project.dhf_released_root_id}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        connector = ConfluenceConnector(settings=self._settings)
        try:
            user_cache: dict[str, str] = {}
            draft_docs, released_docs = await asyncio.gather(
                self._collect_documents(connector, project.dhf_draft_root_id, user_cache),
                self._collect_documents(connector, project.dhf_released_root_id, user_cache),
            )
            rows = self._match_documents(draft_docs, released_docs)
            rows.sort(key=lambda d: (d.area, d.title))
            areas = sorted({d.area for d in rows})
            result = (rows, areas)
            cache.set(cache_key, result, ttl=120)
            return result
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
        """Walk 2-level hierarchy (areas -> documents) under a DHF root page.

        Uses a phased approach to minimise API calls:
        1. Fetch area children (parallel)
        2. Fetch doc metadata + page data for all docs (parallel, semaphore-limited)
        3. Batch-resolve unique author display names (parallel, deduplicated)
        4. For SoftComply-authored docs only, fetch version history (parallel)
        5. Assemble results
        """
        areas = await connector.get_child_pages_v2(root_page_id)

        # Phase 1: Fetch all area children in parallel
        area_children_lists = await asyncio.gather(
            *(connector.get_child_pages_v2(area.get("id", "")) for area in areas)
        )

        # Build flat list of (area_title, child_id, child_title)
        all_items: list[tuple[str, str, str]] = []
        for area, children in zip(areas, area_children_lists):
            area_title = area.get("title", "")
            for child in children:
                all_items.append((area_title, child.get("id", ""), child.get("title", "")))

        if not all_items:
            return []

        # Phase 2: Fetch doc_id + page_v2 for every doc (semaphore-limited)
        async def _fetch_page_data(child_id: str) -> tuple[str | None, dict]:
            async with _CONFLUENCE_SEM:
                return await asyncio.gather(
                    self._get_document_id(connector, child_id),
                    connector.get_page_v2(child_id),
                )

        page_results = await asyncio.gather(
            *(_fetch_page_data(cid) for _, cid, _ in all_items)
        )

        # Phase 3: Collect unique author IDs and batch-resolve display names
        author_ids: set[str] = set()
        page_data_list: list[tuple[str | None, dict]] = []
        for doc_id_page in page_results:
            doc_id, full_page = doc_id_page
            page_data_list.append((doc_id, full_page))
            aid = full_page.get("version", {}).get("authorId", "")
            if aid:
                author_ids.add(aid)

        # Resolve only IDs not already in cache
        new_ids = [aid for aid in author_ids if aid not in user_cache]

        async def _resolve_name(aid: str) -> tuple[str, str]:
            async with _CONFLUENCE_SEM:
                name = await connector.get_user_display_name(aid)
            return aid, name

        if new_ids:
            resolved = await asyncio.gather(*(_resolve_name(aid) for aid in new_ids))
            for aid, name in resolved:
                user_cache[aid] = name

        # Phase 4: For SoftComply-authored docs, batch-fetch version histories
        softcomply_indices: list[int] = []
        for i, (_, (_, full_page)) in enumerate(zip(all_items, page_data_list)):
            aid = full_page.get("version", {}).get("authorId", "")
            if aid and "softcomply" in user_cache.get(aid, "").lower():
                softcomply_indices.append(i)

        if softcomply_indices:
            async def _fetch_versions(child_id: str) -> list[dict]:
                async with _CONFLUENCE_SEM:
                    return await connector.get_page_versions(child_id)

            version_results = await asyncio.gather(
                *(_fetch_versions(all_items[i][1]) for i in softcomply_indices)
            )

            # Collect any new author IDs from version histories
            extra_ids: set[str] = set()
            for versions in version_results:
                for v in versions:
                    vid = v.get("authorId", "")
                    if vid and vid not in user_cache:
                        extra_ids.add(vid)

            if extra_ids:
                extra_resolved = await asyncio.gather(
                    *(_resolve_name(aid) for aid in extra_ids)
                )
                for aid, name in extra_resolved:
                    user_cache[aid] = name

            # Pick the first human author from each version history
            sc_author_map: dict[int, str] = {}
            for idx, versions in zip(softcomply_indices, version_results):
                for v in versions:
                    vid = v.get("authorId", "")
                    if vid and "softcomply" not in user_cache.get(vid, "").lower():
                        sc_author_map[idx] = user_cache[vid]
                        break

        # Phase 5: Assemble results
        base_url = f"https://{connector._domain}.atlassian.net/wiki"
        docs: list[dict] = []
        for i, (area_title, child_id, child_title) in enumerate(all_items):
            doc_id, full_page = page_data_list[i]
            ver = full_page.get("version", {})
            aid = ver.get("authorId", "")

            # Determine author name
            if i in softcomply_indices:
                author_name = sc_author_map.get(i, user_cache.get(aid, aid))
            else:
                author_name = user_cache.get(aid, aid)

            webui = full_page.get("_links", {}).get("webui", "")
            docs.append({
                "page_id": child_id,
                "title": _strip_version(child_title),
                "area": area_title,
                "version": _parse_version(child_title),
                "document_id": doc_id,
                "last_modified": ver.get("createdAt", ""),
                "author": author_name,
                "page_url": f"{base_url}{webui}" if webui else "",
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
