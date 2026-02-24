"""Spin-up wizard routes."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from src.config import settings as app_settings
from src.models.project import SpinUpRequest
from src.services.spinup import SpinUpService
from src.web.deps import get_nav_context, templates

router = APIRouter(prefix="/spinup", tags=["spinup"])


@router.get("/", response_class=HTMLResponse)
async def spinup_form(request: Request) -> HTMLResponse:
    """Render the spin-up wizard form."""
    return templates.TemplateResponse(
        request,
        "spinup.html",
        {**get_nav_context(request)},
    )


@router.post("/", response_class=HTMLResponse)
async def spinup_submit(
    request: Request,
    project_name: str = Form(...),
    program: str = Form(...),
    team_projects: str = Form(""),
    target_date: str = Form(""),
    labels: str = Form(""),
    goal_summary: str = Form(""),
    pi_version: str = Form(""),
    jira_plan_url: str = Form(""),
) -> HTMLResponse:
    """Parse the form, queue spin-up actions, and show result page."""
    # Parse comma-separated values
    team_list = [[t.strip(), project_name] for t in team_projects.split(",") if t.strip()]
    label_list = [l.strip() for l in labels.split(",") if l.strip()]

    req = SpinUpRequest(
        project_name=project_name,
        program=program,
        team_projects=team_list,
        target_date=target_date,
        labels=label_list,
        goal_summary=goal_summary,
        confluence_space_key=app_settings.atlassian.confluence_space_key,
        pi_version=pi_version.strip(),
        jira_plan_url=jira_plan_url.strip(),
    )

    service = SpinUpService()
    item_ids = await service.prepare_spinup(req)

    return templates.TemplateResponse(
        request,
        "spinup_result.html",
        {
            "item_count": len(item_ids),
            "project_name": project_name,
            **get_nav_context(request),
        },
    )
