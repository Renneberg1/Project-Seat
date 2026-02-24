"""Project settings routes — view and update project configuration."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from src.config import settings as app_settings
from src.database import get_db
from src.services.dashboard import DashboardService
from src.web.deps import get_nav_context, templates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/project/{id}/settings", tags=["settings"])


def _render(request: Request, template: str, context: dict, project_id: int) -> HTMLResponse:
    nav = get_nav_context(request)
    nav["selected_project_id"] = project_id
    response = templates.TemplateResponse(request, template, {**context, **nav})
    response.set_cookie("seat_selected_project", str(project_id), max_age=60 * 60 * 24 * 30)
    return response


@router.get("/", response_class=HTMLResponse)
async def settings_page(request: Request, id: int) -> HTMLResponse:
    """Display the project settings form."""
    dashboard = DashboardService()
    project = dashboard.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)

    return _render(request, "project_settings.html", {"project": project}, id)


@router.post("/", response_class=HTMLResponse)
async def settings_save(request: Request, id: int) -> HTMLResponse:
    """Save updated project settings."""
    dashboard = DashboardService()
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
    jira_plan_url = str(form.get("jira_plan_url", "")).strip() or None

    # Parse team_projects: each line is "KEY=VersionName"
    team_projects_raw = str(form.get("team_projects", "")).strip()
    team_projects: dict[str, str] = {}
    for line in team_projects_raw.splitlines():
        line = line.strip()
        if "=" in line:
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip()
            if key:
                team_projects[key] = val

    with get_db(app_settings.db_path) as conn:
        conn.execute(
            """UPDATE projects SET
                name = ?, phase = ?, jira_goal_key = ?,
                confluence_charter_id = ?, confluence_xft_id = ?,
                confluence_ceo_review_id = ?,
                dhf_draft_root_id = ?, dhf_released_root_id = ?,
                pi_version = ?, jira_plan_url = ?,
                team_projects = ?
            WHERE id = ?""",
            (
                name, phase, jira_goal_key,
                confluence_charter_id, confluence_xft_id,
                confluence_ceo_review_id,
                dhf_draft_root_id, dhf_released_root_id,
                pi_version, jira_plan_url,
                json.dumps(team_projects),
                id,
            ),
        )
        conn.commit()

    # Reload project
    project = dashboard.get_project_by_id(id)
    return _render(request, "project_settings.html", {
        "project": project,
        "saved": True,
    }, id)
