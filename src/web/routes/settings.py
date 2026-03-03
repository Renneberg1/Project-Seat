"""Project settings routes — view and update project configuration."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from src.cache import cache
from src.connectors.confluence import ConfluenceConnector
from src.connectors.jira import JiraConnector
from src.services.dashboard import DashboardService
from src.repositories.zoom_repo import ZoomRepository
from src.web.deps import (
    get_confluence_connector,
    get_dashboard_service,
    get_jira_connector,
    get_zoom_repo,
    render_project_page,
    templates,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/project/{id}/settings", tags=["settings"])

_DISPLAY_CACHE_TTL = 300  # 5 min


class _DisplayValues:
    """Simple namespace for display values passed to the template."""

    def __init__(self, **kwargs: str):
        for k, v in kwargs.items():
            setattr(self, k, v)

    def __getattr__(self, name: str) -> str:
        return ""


def _looks_like_page_id(value: str | None) -> bool:
    """Return True if value looks like a numeric Confluence page ID."""
    return bool(value and value.strip().isdigit())


def _looks_like_issue_key(value: str | None) -> bool:
    """Return True if value looks like a Jira issue key (e.g. PROG-256)."""
    import re

    return bool(value and re.match(r"^[A-Z]+-\d+$", value.strip(), re.IGNORECASE))


async def _resolve_display_values(
    project,
    confluence: ConfluenceConnector,
    jira: JiraConnector,
) -> _DisplayValues:
    """Resolve opaque IDs to human-readable display strings.

    Skips API calls for values that don't look like valid IDs/keys.
    """
    vals: dict[str, str] = {}

    # Confluence page IDs → titles (only for numeric IDs)
    page_fields = [
        ("confluence_charter_id", getattr(project, "confluence_charter_id", None)),
        ("confluence_xft_id", getattr(project, "confluence_xft_id", None)),
        ("confluence_ceo_review_id", getattr(project, "confluence_ceo_review_id", None)),
        ("dhf_draft_root_id", getattr(project, "dhf_draft_root_id", None)),
        ("dhf_released_root_id", getattr(project, "dhf_released_root_id", None)),
    ]

    ids_to_resolve = [(name, pid) for name, pid in page_fields if _looks_like_page_id(pid)]

    if ids_to_resolve:
        try:
            for field_name, page_id in ids_to_resolve:
                cache_key = f"display:confluence:{page_id}"
                cached = cache.get(cache_key)
                if cached is not None:
                    vals[field_name] = cached
                    continue
                try:
                    page = await confluence.get_page(str(page_id))
                    title = page.get("title", str(page_id))
                    display = f"{title} ({page_id})"
                    cache.set(cache_key, display, _DISPLAY_CACHE_TTL)
                    vals[field_name] = display
                except Exception:
                    vals[field_name] = str(page_id)
        finally:
            await confluence.close()

    # Jira goal key → key + summary (only for valid KEY-123 format)
    goal_key = getattr(project, "jira_goal_key", None)
    if _looks_like_issue_key(goal_key):
        cache_key = f"display:jira:{goal_key}"
        cached = cache.get(cache_key)
        if cached is not None:
            vals["jira_goal_key"] = cached
        else:
            try:
                issue = await jira.get_issue(goal_key, fields=["summary"])
                summary = issue.get("fields", {}).get("summary", "")
                display = f"{goal_key} — {summary}" if summary else goal_key
                cache.set(cache_key, display, _DISPLAY_CACHE_TTL)
                vals["jira_goal_key"] = display
            except Exception:
                vals["jira_goal_key"] = goal_key
            finally:
                await jira.close()

    return _DisplayValues(**vals)


@router.get("/", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    id: int,
    dashboard: DashboardService = Depends(get_dashboard_service),
    confluence: ConfluenceConnector = Depends(get_confluence_connector),
    jira: JiraConnector = Depends(get_jira_connector),
    zoom_repo: ZoomRepository = Depends(get_zoom_repo),
) -> HTMLResponse:
    """Display the project settings form."""
    project = dashboard.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)

    display_values = await _resolve_display_values(project, confluence, jira)
    aliases = zoom_repo.get_aliases(id)

    return render_project_page(request, "project_settings.html", {
        "project": project,
        "display_values": display_values,
        "aliases": aliases,
    }, id)


@router.post("/", response_class=HTMLResponse)
async def settings_save(
    request: Request,
    id: int,
    dashboard: DashboardService = Depends(get_dashboard_service),
    confluence: ConfluenceConnector = Depends(get_confluence_connector),
    jira: JiraConnector = Depends(get_jira_connector),
    zoom_repo: ZoomRepository = Depends(get_zoom_repo),
) -> HTMLResponse:
    """Save updated project settings."""
    project = dashboard.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)

    form = await request.form()

    name = str(form.get("name", project.name)).strip() or project.name
    phase = str(form.get("phase", project.phase)).strip()
    jira_goal_key = str(form.get("jira_goal_key", project.jira_goal_key)).strip()
    confluence_charter_id = str(form.get("confluence_charter_id", "")).strip() or None
    confluence_xft_id = str(form.get("confluence_xft_id", "")).strip() or None
    confluence_ceo_review_id = str(form.get("confluence_ceo_review_id", "")).strip() or None
    dhf_draft_root_id = str(form.get("dhf_draft_root_id", "")).strip() or None
    dhf_released_root_id = str(form.get("dhf_released_root_id", "")).strip() or None
    pi_version = str(form.get("pi_version", "")).strip() or None
    from src.web.routes.project import _extract_plan_url
    jira_plan_url = _extract_plan_url(str(form.get("jira_plan_url", ""))) or None

    # Parse team_projects: each line is "KEY=VersionName"
    # Allows duplicate keys with different versions.
    team_projects_raw = str(form.get("team_projects", "")).strip()
    team_projects: list[list[str]] = []
    for line in team_projects_raw.splitlines():
        line = line.strip()
        if "=" in line:
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip()
            if key:
                team_projects.append([key, val])

    dashboard.update_project(
        id,
        name=name, phase=phase, jira_goal_key=jira_goal_key,
        confluence_charter_id=confluence_charter_id,
        confluence_xft_id=confluence_xft_id,
        confluence_ceo_review_id=confluence_ceo_review_id,
        dhf_draft_root_id=dhf_draft_root_id,
        dhf_released_root_id=dhf_released_root_id,
        pi_version=pi_version, jira_plan_url=jira_plan_url,
        team_projects=team_projects,
    )

    # Save project aliases
    aliases_raw = str(form.get("aliases", "")).strip()
    aliases = [a.strip() for a in aliases_raw.split(",") if a.strip()]
    zoom_repo.set_aliases(id, aliases)

    # Reload project and resolve display values
    project = dashboard.get_project_by_id(id)
    display_values = await _resolve_display_values(project, confluence, jira)

    return render_project_page(request, "project_settings.html", {
        "project": project,
        "display_values": display_values,
        "aliases": aliases,
        "saved": True,
    }, id)
