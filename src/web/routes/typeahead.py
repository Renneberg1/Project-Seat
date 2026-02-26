"""Typeahead search endpoints for Atlassian resource linking."""

from __future__ import annotations

import logging
import re

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from src.cache import cache
from src.connectors.base import ConnectorError
from src.connectors.confluence import ConfluenceConnector
from src.connectors.jira import JiraConnector
from src.web.deps import templates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/typeahead", tags=["typeahead"])

_CACHE_SHORT = 60  # pages/issues: 60s
_CACHE_LONG = 300  # projects/versions: 5min


def _render_results(request: Request, results: list[dict]) -> HTMLResponse:
    return templates.TemplateResponse(
        request, "partials/typeahead_results.html", {"results": results}
    )


def _extract_space_key(page: dict) -> str:
    """Extract the space key from a Confluence search result.

    With ``expand=space``, the space object is nested directly.
    Without expand, fall back to ``_expandable.space`` URL parsing.
    """
    # Expanded space object (preferred)
    space = page.get("space")
    if isinstance(space, dict):
        return space.get("key", "")
    # Fallback: _expandable URL
    expandable = page.get("_expandable", {}).get("space", "")
    if expandable:
        return expandable.rstrip("/").split("/")[-1]
    return ""


# ------------------------------------------------------------------
# Confluence pages
# ------------------------------------------------------------------


@router.get("/confluence-pages", response_class=HTMLResponse)
async def search_confluence_pages(
    request: Request,
    q: str = Query("", min_length=0),
    space: str = Query(""),
) -> HTMLResponse:
    """Search Confluence pages by title (fuzzy CQL match)."""
    if len(q) < 2:
        return _render_results(request, [])

    cache_key = f"ta:confluence-pages:{space}:{q}"
    cached = cache.get(cache_key)
    if cached is not None:
        return _render_results(request, cached)

    confluence = ConfluenceConnector()
    try:
        pages = await confluence.search_pages_by_title(q, space_key=space)
    except ConnectorError as exc:
        logger.warning("Confluence typeahead search failed for q=%r: %s", q, exc)
        return _render_results(request, [])
    finally:
        await confluence.close()

    results = [
        {
            "id": p.get("id", ""),
            "label": p.get("title", ""),
            "sublabel": _extract_space_key(p),
        }
        for p in pages[:10]
    ]
    cache.set(cache_key, results, _CACHE_SHORT)
    return _render_results(request, results)


# ------------------------------------------------------------------
# Jira issues
# ------------------------------------------------------------------


@router.get("/jira-issues", response_class=HTMLResponse)
async def search_jira_issues(
    request: Request,
    q: str = Query("", min_length=0),
    project: str = Query(""),
) -> HTMLResponse:
    """Search Jira issues by key or summary."""
    if len(q) < 2:
        return _render_results(request, [])

    cache_key = f"ta:jira-issues:{project}:{q}"
    cached = cache.get(cache_key)
    if cached is not None:
        return _render_results(request, cached)

    # Build JQL: if it looks like a key prefix, search by key; otherwise by summary
    if re.match(r"^[A-Z]+-\d+$", q, re.IGNORECASE):
        # Full key like PROG-256
        jql = f'key = "{q.upper()}"'
        if project:
            jql = f'project = "{project}" AND {jql}'
    elif re.match(r"^[A-Z]+-$", q, re.IGNORECASE):
        # Partial key like PROG- (prefix only)
        proj_key = q.upper().rstrip("-")
        jql = f'project = "{proj_key}" ORDER BY key DESC'
    else:
        escaped = q.replace('"', '\\"')
        jql = f'summary ~ "{escaped}"'
        if project:
            jql = f'project = "{project}" AND {jql}'

    logger.debug("Jira typeahead JQL: %s", jql)
    jira = JiraConnector()
    try:
        issues = await jira.search(jql, fields=["summary"], max_results=10)
    except ConnectorError as exc:
        logger.warning("Jira typeahead search failed for q=%r jql=%r: %s", q, jql, exc)
        return _render_results(request, [])
    except Exception as exc:
        logger.warning("Jira typeahead unexpected error for q=%r: %s", q, exc)
        return _render_results(request, [])
    finally:
        await jira.close()

    results = [
        {
            "id": i.get("key", ""),
            "label": i.get("key", ""),
            "sublabel": i.get("fields", {}).get("summary", ""),
        }
        for i in issues[:10]
    ]
    cache.set(cache_key, results, _CACHE_SHORT)
    return _render_results(request, results)


# ------------------------------------------------------------------
# Jira projects
# ------------------------------------------------------------------


@router.get("/jira-projects", response_class=HTMLResponse)
async def search_jira_projects(
    request: Request,
    q: str = Query(""),
) -> HTMLResponse:
    """Search Jira projects by name/key."""
    cache_key = f"ta:jira-projects:{q}"
    cached = cache.get(cache_key)
    if cached is not None:
        return _render_results(request, cached)

    jira = JiraConnector()
    try:
        projects = await jira.list_projects(query=q)
    except ConnectorError as exc:
        logger.warning("Jira project typeahead failed for q=%r: %s", q, exc)
        return _render_results(request, [])
    finally:
        await jira.close()

    results = [
        {
            "id": p.get("key", ""),
            "label": p.get("key", ""),
            "sublabel": p.get("name", ""),
        }
        for p in projects[:20]
    ]
    cache.set(cache_key, results, _CACHE_LONG)
    return _render_results(request, results)


# ------------------------------------------------------------------
# Jira versions
# ------------------------------------------------------------------


@router.get("/jira-versions", response_class=HTMLResponse)
async def search_jira_versions(
    request: Request,
    project: str = Query(""),
) -> HTMLResponse:
    """List versions for a Jira project."""
    if not project:
        return _render_results(request, [])

    cache_key = f"ta:jira-versions:{project}"
    cached = cache.get(cache_key)
    if cached is not None:
        return _render_results(request, cached)

    jira = JiraConnector()
    try:
        versions = await jira.get_versions(project)
    except ConnectorError as exc:
        logger.warning("Jira version typeahead failed for project=%r: %s", project, exc)
        return _render_results(request, [])
    finally:
        await jira.close()

    results = [
        {
            "id": v.get("name", ""),
            "label": v.get("name", ""),
            "sublabel": "released" if v.get("released") else "unreleased",
        }
        for v in versions
    ]
    cache.set(cache_key, results, _CACHE_LONG)
    return _render_results(request, results)
