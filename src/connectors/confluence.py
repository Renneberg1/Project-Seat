"""Confluence REST API connector."""

from __future__ import annotations

import logging
from typing import Any

from src.config import Settings, settings as default_settings
from src.connectors.base import BaseConnector, ConnectorError

logger = logging.getLogger(__name__)


class ConfluenceConnector(BaseConnector):
    """Thin wrapper around the Confluence REST API (v1 + v2)."""

    def __init__(self, *, settings: Settings | None = None) -> None:
        cfg = settings or default_settings
        super().__init__(cfg.atlassian.confluence_base_url, settings=cfg)
        self._domain = cfg.atlassian.domain

    # ------------------------------------------------------------------
    # Pages
    # ------------------------------------------------------------------

    async def get_page(
        self,
        page_id: str,
        *,
        expand: list[str] | None = None,
    ) -> dict[str, Any]:
        """Fetch a single page by ID.

        Common expand values: body.storage, version, children.page, ancestors
        """
        params: dict[str, Any] = {}
        if expand:
            params["expand"] = ",".join(expand)
        return await self.get(f"/content/{page_id}", params=params or None)

    async def get_page_children(self, page_id: str) -> list[dict[str, Any]]:
        """List direct child pages of the given page (auto-paginated)."""
        return await self.get_all_confluence(f"/content/{page_id}/child/page")

    async def create_page(
        self,
        space_key: str,
        title: str,
        body_storage: str,
        *,
        parent_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a new page with storage-format (XHTML) body.

        Returns the created page payload (id, title, _links, etc.).
        """
        payload: dict[str, Any] = {
            "type": "page",
            "title": title,
            "space": {"key": space_key},
            "body": {
                "storage": {
                    "value": body_storage,
                    "representation": "storage",
                },
            },
        }
        if parent_id:
            payload["ancestors"] = [{"id": parent_id}]
        return await self.post("/content", json_body=payload)

    async def search_pages(
        self,
        space_key: str,
        title: str,
    ) -> list[dict[str, Any]]:
        """Find pages by exact title within a space (auto-paginated)."""
        cql = f'space="{space_key}" AND title="{title}" AND type=page'
        return await self.get_all_confluence(
            "/content/search",
            params={"cql": cql},
        )

    # ------------------------------------------------------------------
    # v2 API helpers
    # ------------------------------------------------------------------

    def _v2_url(self, path: str) -> str:
        """Build an absolute v2 API URL (bypasses httpx base_url)."""
        return f"https://{self._domain}.atlassian.net/wiki/api/v2{path}"

    async def _v2_get_all(self, path: str) -> list[dict[str, Any]]:
        """Cursor-paginated fetch for v2 endpoints.

        v2 uses ``_links.next`` which contains the full path (starting
        with ``/wiki/api/v2/...``).  We build absolute URLs so httpx
        bypasses the v1 ``base_url``.
        """
        url = self._v2_url(path)
        all_results: list[dict[str, Any]] = []

        while url:
            data = await self.get(url)
            all_results.extend(data.get("results", []))
            next_link = data.get("_links", {}).get("next")
            if next_link:
                url = f"https://{self._domain}.atlassian.net{next_link}"
            else:
                url = ""

        return all_results

    async def get_child_pages_v2(self, page_id: str) -> list[dict[str, Any]]:
        """List direct child pages via the v2 API (cursor-paginated)."""
        return await self._v2_get_all(f"/pages/{page_id}/children")

    async def get_page_v2(self, page_id: str) -> dict[str, Any]:
        """Fetch a single page via the v2 API (includes ``_links.webui``)."""
        return await self.get(self._v2_url(f"/pages/{page_id}"))

    async def get_page_versions(
        self, page_id: str, *, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Fetch version history for a page (newest first)."""
        url = self._v2_url(f"/pages/{page_id}/versions")
        data = await self.get(url, params={"limit": limit, "sort": "-modified-date"})
        return data.get("results", [])

    async def get_content_property(
        self, page_id: str, key: str
    ) -> dict[str, Any] | None:
        """Fetch a content property by key (v1 endpoint). Returns ``None`` on 404."""
        try:
            return await self.get(f"/content/{page_id}/property/{key}")
        except ConnectorError as exc:
            if exc.status_code == 404:
                return None
            raise

    async def get_user_display_name(self, account_id: str) -> str:
        """Resolve an Atlassian account ID to a display name (v1 /user)."""
        try:
            data = await self.get("/user", params={"accountId": account_id})
            return data.get("displayName", account_id)
        except ConnectorError:
            return account_id
