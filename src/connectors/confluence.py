"""Confluence REST API connector."""

from __future__ import annotations

from typing import Any

from src.config import Settings, settings as default_settings
from src.connectors.base import BaseConnector


class ConfluenceConnector(BaseConnector):
    """Thin wrapper around the Confluence REST API (v1, /wiki/rest/api)."""

    def __init__(self, *, settings: Settings | None = None) -> None:
        cfg = settings or default_settings
        super().__init__(cfg.atlassian.confluence_base_url, settings=cfg)

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
