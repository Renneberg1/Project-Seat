"""Jira REST API connector."""

from __future__ import annotations

from typing import Any

from src.config import Settings, settings as default_settings
from src.connectors.base import BaseConnector


class JiraConnector(BaseConnector):
    """Thin wrapper around the Jira REST API v3."""

    def __init__(self, *, settings: Settings | None = None) -> None:
        cfg = settings or default_settings
        super().__init__(cfg.atlassian.jira_base_url, settings=cfg)
        self._settings = cfg

    # ------------------------------------------------------------------
    # Issues
    # ------------------------------------------------------------------

    async def get_issue(self, key: str, *, fields: list[str] | None = None) -> dict[str, Any]:
        """Fetch a single issue by key (e.g. 'PROG-256')."""
        params: dict[str, Any] = {}
        if fields:
            params["fields"] = ",".join(fields)
        return await self.get(f"/issue/{key}", params=params or None)

    async def create_issue(
        self,
        project_key: str,
        issue_type_id: str,
        summary: str,
        *,
        fields: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new issue. Returns the created issue payload (id, key, self)."""
        body: dict[str, Any] = {
            "fields": {
                "project": {"key": project_key},
                "issuetype": {"id": issue_type_id},
                "summary": summary,
                **(fields or {}),
            }
        }
        return await self.post("/issue", json_body=body)

    async def search(
        self,
        jql: str,
        *,
        fields: list[str] | None = None,
        max_results: int = 50,
    ) -> list[dict[str, Any]]:
        """Execute a JQL search and return all matching issues (auto-paginated)."""
        params: dict[str, Any] = {"jql": jql}
        if fields:
            params["fields"] = ",".join(fields)
        return await self.get_all_jira("/search", params=params, page_size=max_results)

    # ------------------------------------------------------------------
    # Issue types
    # ------------------------------------------------------------------

    async def get_issue_types(self, project_key: str) -> list[dict[str, Any]]:
        """List issue types available in a project."""
        data = await self.get(f"/issue/createmeta/{project_key}/issuetypes")
        return data.get("issueTypes", data.get("values", []))

    # ------------------------------------------------------------------
    # Versions (fix versions)
    # ------------------------------------------------------------------

    async def create_version(
        self,
        project_key: str,
        name: str,
        *,
        release_date: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Create a fix version in a project."""
        body: dict[str, Any] = {"name": name, "project": project_key}
        if release_date:
            body["releaseDate"] = release_date
        if description:
            body["description"] = description
        return await self.post("/version", json_body=body)

    async def get_versions(self, project_key: str) -> list[dict[str, Any]]:
        """List all versions for a project."""
        data = await self.get(f"/project/{project_key}/versions")
        # The endpoint returns a plain list, not a paginated wrapper
        return data if isinstance(data, list) else data.get("values", [])

    # ------------------------------------------------------------------
    # Issue links
    # ------------------------------------------------------------------

    async def add_issue_link(
        self,
        outward_key: str,
        inward_key: str,
        link_type: str = "Relates",
    ) -> None:
        """Create a link between two issues."""
        body = {
            "type": {"name": link_type},
            "outwardIssue": {"key": outward_key},
            "inwardIssue": {"key": inward_key},
        }
        await self.post("/issueLink", json_body=body)

    # ------------------------------------------------------------------
    # Field helpers
    # ------------------------------------------------------------------

    def field_id(self, name: str) -> str:
        """Convenience proxy to settings.field_id()."""
        return self._settings.field_id(name)
