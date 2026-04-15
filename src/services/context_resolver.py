"""Resolve LLM context requests by fetching data from Jira and Confluence.

Also provides ``resolve_if_needed()`` — a one-liner that any service can call
after an LLM call to handle the two-pass context enrichment pattern.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.config import Settings, settings as default_settings
from src.connectors.base import ConnectorError

logger = logging.getLogger(__name__)


async def resolve_if_needed(
    result: dict[str, Any],
    agent: Any,
    settings: Settings,
    *,
    label: str = "LLM",
) -> dict[str, Any]:
    """Check an LLM result for context_requests and resolve them if present.

    This is the standard two-pass helper. Call it after any agent method:

        result = await agent.some_method(...)
        result = await resolve_if_needed(result, agent, settings, label="Charter")

    If context_requests is empty, returns the original result unchanged (no extra API calls).
    """
    requests = result.get("context_requests", [])
    if not requests:
        return result

    resolver = ContextRequestResolver(settings=settings)
    fetched = await resolver.resolve(requests)
    if not fetched:
        return result

    logger.info(
        "%s: resolving %d context requests, refining analysis",
        label, len(fetched),
    )
    return await agent.resolve_context_requests(result, fetched)

# Maximum number of context requests to resolve per analysis
_MAX_REQUESTS = 5

# Truncate individual results to keep prompt size reasonable
_MAX_RESULT_CHARS = 3000


class ContextRequestResolver:
    """Resolve context_requests from the LLM's first-pass analysis.

    Supports four request types:
    - jira_issue: Fetch a specific Jira issue by key
    - jira_search: Text search across Jira (returns top results)
    - confluence_search: Search Confluence pages by TITLE
    - confluence_text_search: Full-text search Confluence pages (title + body)
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or default_settings

    async def resolve(
        self, requests: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        """Resolve a list of context requests in parallel.

        Args:
            requests: List of {type, query, reason} dicts from the LLM.

        Returns:
            List of {type, query, result} dicts with fetched data.
        """
        if not requests:
            return []

        # Cap the number of requests to prevent runaway fetches
        capped = requests[:_MAX_REQUESTS]
        if len(requests) > _MAX_REQUESTS:
            logger.warning(
                "Context requests capped: %d requested, %d allowed",
                len(requests), _MAX_REQUESTS,
            )

        tasks = [self._resolve_one(req) for req in capped]
        results = await asyncio.gather(*tasks)
        return [r for r in results if r is not None]

    async def _resolve_one(self, req: dict[str, str]) -> dict[str, str] | None:
        """Resolve a single context request."""
        req_type = req.get("type", "")
        query = req.get("query", "").strip()

        if not query:
            return None

        try:
            if req_type == "jira_issue":
                result = await self._fetch_jira_issue(query)
            elif req_type == "jira_search":
                result = await self._search_jira(query)
            elif req_type == "confluence_search":
                result = await self._search_confluence(query)
            elif req_type == "confluence_text_search":
                result = await self._search_confluence_text(query)
            else:
                logger.warning("Unknown context request type: %s", req_type)
                return None

            return {
                "type": req_type,
                "query": query,
                "result": result[:_MAX_RESULT_CHARS] if result else "No results found.",
            }

        except Exception as exc:
            logger.warning(
                "Failed to resolve context request %s(%s): %s",
                req_type, query, exc,
            )
            return {
                "type": req_type,
                "query": query,
                "result": f"Failed to fetch: {str(exc)[:200]}",
            }

    async def _fetch_jira_issue(self, key: str) -> str:
        """Fetch a specific Jira issue and return a text summary."""
        from src.connectors.jira import JiraConnector

        jira = JiraConnector(settings=self._settings)
        try:
            issue = await jira.get_issue(
                key,
                fields=["summary", "status", "description", "issuetype",
                         "priority", "components", "labels"],
            )
            fields = issue.get("fields", {})
            parts = [
                f"Key: {issue.get('key', key)}",
                f"Type: {fields.get('issuetype', {}).get('name', 'N/A')}",
                f"Summary: {fields.get('summary', 'N/A')}",
                f"Status: {fields.get('status', {}).get('name', 'N/A')}",
                f"Priority: {fields.get('priority', {}).get('name', 'N/A')}",
            ]

            components = fields.get("components", [])
            if components:
                parts.append(f"Components: {', '.join(c.get('name', '') for c in components)}")

            labels = fields.get("labels", [])
            if labels:
                parts.append(f"Labels: {', '.join(labels)}")

            # Extract plain text from ADF description
            desc = fields.get("description")
            if desc and isinstance(desc, dict):
                desc_text = self._extract_adf_text(desc)
                if desc_text:
                    parts.append(f"Description: {desc_text[:1500]}")
            elif desc and isinstance(desc, str):
                parts.append(f"Description: {desc[:1500]}")

            return "\n".join(parts)

        except ConnectorError as exc:
            return f"Issue {key} not found or inaccessible: {exc}"
        finally:
            await jira.close()

    async def _search_jira(self, query: str) -> str:
        """Search Jira with a text query and return top results."""
        from src.connectors.jira import JiraConnector

        jira = JiraConnector(settings=self._settings)
        try:
            # Use JQL text search
            jql = f'text ~ "{query}" ORDER BY updated DESC'
            results = await jira.search(
                jql, fields=["summary", "status", "issuetype"], max_results=8,
            )

            if not results:
                return "No matching Jira issues found."

            lines = [f"Found {len(results)} results for '{query}':"]
            for r in results:
                fields = r.get("fields", {})
                lines.append(
                    f"- [{r.get('key', '?')}] ({fields.get('issuetype', {}).get('name', '?')}) "
                    f"{fields.get('summary', '?')} [{fields.get('status', {}).get('name', '?')}]"
                )
            return "\n".join(lines)

        except ConnectorError as exc:
            return f"Jira search failed: {exc}"
        finally:
            await jira.close()

    async def _search_confluence(self, query: str) -> str:
        """Search Confluence pages by title and return top results."""
        from src.connectors.confluence import ConfluenceConnector

        confluence = ConfluenceConnector(settings=self._settings)
        try:
            results = await confluence.search_pages_by_title(
                query, max_results=5,
            )

            if not results:
                return "No matching Confluence pages found."

            lines = [f"Found {len(results)} title results for '{query}':"]
            for r in results:
                title = r.get("title", "?")
                page_id = r.get("id", "?")
                excerpt = r.get("excerpt", "")[:200] if r.get("excerpt") else ""
                lines.append(f"- [{page_id}] {title}")
                if excerpt:
                    lines.append(f"  {excerpt}")
            return "\n".join(lines)

        except ConnectorError as exc:
            return f"Confluence search failed: {exc}"
        finally:
            await confluence.close()

    async def _search_confluence_text(self, query: str) -> str:
        """Full-text Confluence search (title + body) returning results with excerpts."""
        from src.connectors.confluence import ConfluenceConnector

        confluence = ConfluenceConnector(settings=self._settings)
        try:
            results = await confluence.search_pages_by_text(
                query, max_results=5,
            )

            if not results:
                return "No matching Confluence pages found (full-text search)."

            lines = [f"Found {len(results)} full-text results for '{query}':"]
            for r in results:
                title = r.get("title", "?")
                page_id = r.get("id", "?")
                # Confluence returns excerpts with <b>...</b> highlight tags — strip for LLM
                raw_excerpt = r.get("excerpt", "") or ""
                excerpt = (
                    raw_excerpt.replace("<b>", "").replace("</b>", "").strip()
                )[:400]
                lines.append(f"- [{page_id}] {title}")
                if excerpt:
                    lines.append(f"  ...{excerpt}...")
            return "\n".join(lines)

        except ConnectorError as exc:
            return f"Confluence text search failed: {exc}"
        finally:
            await confluence.close()

    @staticmethod
    def _extract_adf_text(adf: dict[str, Any]) -> str:
        """Recursively extract plain text from an ADF document."""
        texts: list[str] = []

        def _walk(node: dict | list) -> None:
            if isinstance(node, list):
                for item in node:
                    _walk(item)
                return
            if isinstance(node, dict):
                if node.get("type") == "text":
                    texts.append(node.get("text", ""))
                for child in node.get("content", []):
                    _walk(child)

        _walk(adf)
        return " ".join(texts)
