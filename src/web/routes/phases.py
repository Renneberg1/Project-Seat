"""Phase Gates routes — pipeline view and phase updates."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from src.models.dashboard import PIPELINE_PHASES
from src.services.dashboard import DashboardService
from src.web.deps import get_nav_context, templates

router = APIRouter(tags=["phases"])


@router.get("/phases/", response_class=HTMLResponse)
async def phases(request: Request) -> HTMLResponse:
    """Render the pipeline view with live Jira data."""
    service = DashboardService()
    summaries = await service.get_all_summaries()

    # Group summaries by phase
    phases_with_projects: list[dict] = []
    for value, label in PIPELINE_PHASES:
        phase_summaries = [s for s in summaries if s.project.phase == value]
        phases_with_projects.append({
            "value": value,
            "label": label,
            "summaries": phase_summaries,
        })

    return templates.TemplateResponse(
        request,
        "phases.html",
        {
            "phases": phases_with_projects,
            "total_projects": len(summaries),
            "pipeline_phases": PIPELINE_PHASES,
            "now_date": date.today().isoformat(),
            **get_nav_context(request),
        },
    )


@router.post("/phases/{project_id}/phase", response_class=HTMLResponse)
async def update_phase(
    request: Request,
    project_id: int,
    phase: str = Form(...),
) -> HTMLResponse:
    """Update a project's pipeline phase. Returns refreshed project card partial."""
    service = DashboardService()
    service.update_phase(project_id, phase)

    project = service.get_project_by_id(project_id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)

    summary = await service.get_project_summary(project)
    return templates.TemplateResponse(
        request,
        "partials/project_card.html",
        {"summary": summary, "pipeline_phases": PIPELINE_PHASES, "now_date": date.today().isoformat()},
    )
