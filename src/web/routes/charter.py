"""Charter routes — view sections, LLM Q&A, edit proposals, accept/reject."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

logger = logging.getLogger(__name__)

from src.services.charter import CharterService
from src.services.dashboard import DashboardService
from src.web.deps import (
    collect_qa_pairs,
    error_banner,
    get_charter_service,
    get_dashboard_service,
    render_project_page,
    templates,
)

router = APIRouter(prefix="/project/{id}/charter", tags=["charter"])


# ------------------------------------------------------------------
# Main page
# ------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
async def charter_page(
    request: Request,
    id: int,
    dashboard: DashboardService = Depends(get_dashboard_service),
    service: CharterService = Depends(get_charter_service),
) -> HTMLResponse:
    """Display current Charter sections + textarea + past suggestions."""
    project = dashboard.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)
    try:
        sections = await service.fetch_charter_sections(project)
    except Exception:
        logger.warning("Charter fetch failed for project %d", id, exc_info=True)
        sections = []

    suggestions = service.list_suggestions(id)

    return render_project_page(request, "charter.html", {
        "project": project,
        "sections": sections,
        "suggestions": suggestions,
    }, id)


# ------------------------------------------------------------------
# LLM Step 1: Ask questions
# ------------------------------------------------------------------

@router.post("/ask", response_class=HTMLResponse)
async def charter_ask(
    request: Request,
    id: int,
    user_input: str = Form(...),
    dashboard: DashboardService = Depends(get_dashboard_service),
    service: CharterService = Depends(get_charter_service),
) -> HTMLResponse:
    """LLM generates clarifying questions, returns questions form partial."""
    project = dashboard.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)

    if not project.confluence_charter_id:
        return error_banner("No Charter page configured for this project.", status_code=400)
    try:
        questions = await service.generate_questions(project, user_input)
    except Exception as exc:
        return error_banner(f"LLM analysis failed: {exc}", status_code=500)

    return templates.TemplateResponse(request, "partials/charter_questions.html", {
        "project": project,
        "questions": questions,
        "user_input": user_input,
    })


# ------------------------------------------------------------------
# LLM Step 2: Analyze and propose edits
# ------------------------------------------------------------------

@router.post("/analyze", response_class=HTMLResponse)
async def charter_analyze(
    request: Request,
    id: int,
    dashboard: DashboardService = Depends(get_dashboard_service),
    service: CharterService = Depends(get_charter_service),
) -> HTMLResponse:
    """Receives original input + answers, LLM proposes edits, returns suggestions partial."""
    project = dashboard.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)

    form = await request.form()
    user_input = form.get("user_input", "")
    qa_pairs = collect_qa_pairs(form)
    try:
        suggestions = await service.analyze_charter_update(project, str(user_input), qa_pairs)
    except Exception as exc:
        return error_banner(f"LLM analysis failed: {exc}", status_code=500)

    return templates.TemplateResponse(request, "partials/charter_suggestions.html", {
        "project": project,
        "suggestions": suggestions,
        "analysis_summary": suggestions[0].analysis_summary if suggestions else "",
    })


# ------------------------------------------------------------------
# Accept / Reject suggestions
# ------------------------------------------------------------------

@router.post("/suggestions/{sid}/accept", response_class=HTMLResponse)
async def accept_charter_suggestion(
    request: Request,
    id: int,
    sid: int,
    dashboard: DashboardService = Depends(get_dashboard_service),
    service: CharterService = Depends(get_charter_service),
) -> HTMLResponse:
    """Accept a charter suggestion — queue it for approval."""
    project = dashboard.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)
    try:
        sug = await service.accept_suggestion(sid, project)
    except ValueError as exc:
        return error_banner(str(exc), status_code=400)
    if sug is None:
        return HTMLResponse("Suggestion not found", status_code=404)

    return templates.TemplateResponse(
        request,
        "partials/charter_suggestion_row.html",
        {"sug": sug, "project": project},
    )


@router.post("/suggestions/{sid}/reject", response_class=HTMLResponse)
async def reject_charter_suggestion(
    request: Request,
    id: int,
    sid: int,
    dashboard: DashboardService = Depends(get_dashboard_service),
    service: CharterService = Depends(get_charter_service),
) -> HTMLResponse:
    """Reject a charter suggestion."""
    project = dashboard.get_project_by_id(id)
    sug = service.reject_suggestion(sid)
    if sug is None:
        return HTMLResponse("Suggestion not found", status_code=404)

    return templates.TemplateResponse(
        request,
        "partials/charter_suggestion_row.html",
        {"sug": sug, "project": project},
    )


@router.post("/suggestions/accept-all", response_class=HTMLResponse)
async def accept_all_charter_suggestions(
    request: Request,
    id: int,
    dashboard: DashboardService = Depends(get_dashboard_service),
    service: CharterService = Depends(get_charter_service),
) -> HTMLResponse:
    """Accept all pending charter suggestions."""
    project = dashboard.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)
    await service.accept_all_suggestions(project)

    suggestions = service.list_suggestions(id)
    return templates.TemplateResponse(request, "partials/charter_suggestions.html", {
        "project": project,
        "suggestions": suggestions,
        "analysis_summary": suggestions[0].analysis_summary if suggestions else "",
    })
