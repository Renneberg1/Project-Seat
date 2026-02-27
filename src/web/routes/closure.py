"""Closure Report routes — LLM-powered project closure report for Confluence."""

from __future__ import annotations

import html
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

logger = logging.getLogger(__name__)

from src.services.closure import ClosureService
from src.services.dashboard import DashboardService
from src.web.deps import (
    collect_qa_pairs,
    get_closure_service,
    get_dashboard_service,
    render_project_page,
    templates,
)

router = APIRouter(prefix="/project/{id}/closure", tags=["closure"])


# ------------------------------------------------------------------
# Main page
# ------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
async def closure_page(
    request: Request,
    id: int,
    dashboard: DashboardService = Depends(get_dashboard_service),
    service: ClosureService = Depends(get_closure_service),
) -> HTMLResponse:
    """Display the Closure Report page with PM notes form and past reports."""
    project = dashboard.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)

    past_reports = service.list_reports(id)

    return render_project_page(request, "project_closure.html", {
        "project": project,
        "past_reports": past_reports,
    }, id)


# ------------------------------------------------------------------
# LLM Step 1: Ask questions
# ------------------------------------------------------------------

@router.post("/ask", response_class=HTMLResponse)
async def closure_ask(
    request: Request,
    id: int,
    dashboard: DashboardService = Depends(get_dashboard_service),
    service: ClosureService = Depends(get_closure_service),
) -> HTMLResponse:
    """Gather context, compute metrics, ask LLM for clarifying questions."""
    project = dashboard.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)

    form = await request.form()
    pm_notes = str(form.get("pm_notes", ""))
    try:
        questions, metrics = await service.generate_questions(project, pm_notes)
    except Exception as exc:
        logger.exception("Closure report /ask failed")
        return HTMLResponse(
            f'<div class="error-banner">Closure report failed: {html.escape(str(exc))}</div>',
            status_code=500,
        )

    return templates.TemplateResponse(request, "partials/closure_questions.html", {
        "project": project,
        "questions": questions,
        "pm_notes": pm_notes,
    })


# ------------------------------------------------------------------
# LLM Step 2: Generate report
# ------------------------------------------------------------------

@router.post("/analyze", response_class=HTMLResponse)
async def closure_analyze(
    request: Request,
    id: int,
    dashboard: DashboardService = Depends(get_dashboard_service),
    service: ClosureService = Depends(get_closure_service),
) -> HTMLResponse:
    """Receives Q&A answers + PM notes, produces the closure report."""
    project = dashboard.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)

    form = await request.form()
    pm_notes = str(form.get("pm_notes", ""))
    qa_pairs = collect_qa_pairs(form)
    try:
        report = await service.generate_report(project, pm_notes, qa_pairs)
    except Exception as exc:
        logger.exception("Closure report /analyze failed")
        return HTMLResponse(
            f'<div class="error-banner">Closure report failed: {html.escape(str(exc))}</div>',
            status_code=500,
        )

    xhtml = service.render_confluence_xhtml(report)
    report_id = service.save_report(project.id, report, xhtml)
    report["id"] = report_id

    return templates.TemplateResponse(request, "partials/closure_preview.html", {
        "project": project,
        "report": report,
        "report_id": report_id,
    })


# ------------------------------------------------------------------
# Accept / Reject
# ------------------------------------------------------------------

@router.post("/{rid}/accept", response_class=HTMLResponse)
async def closure_accept(
    request: Request,
    id: int,
    rid: int,
    dashboard: DashboardService = Depends(get_dashboard_service),
    service: ClosureService = Depends(get_closure_service),
) -> HTMLResponse:
    """Accept and queue the report for Confluence publish."""
    project = dashboard.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)
    try:
        result = service.accept_report(rid, project)
    except ValueError as exc:
        return HTMLResponse(
            f'<div class="error-banner">{html.escape(str(exc))}</div>',
            status_code=400,
        )

    if result and result.status.value == "queued":
        return HTMLResponse(
            '<div class="success-banner">Closure Report queued for approval. '
            'Check the <a href="/approval/">Approval Queue</a>.</div>'
        )
    return HTMLResponse(
        '<div class="error-banner">Could not queue report. It may have already been processed.</div>',
        status_code=400,
    )


@router.post("/{rid}/reject", response_class=HTMLResponse)
async def closure_reject(
    request: Request,
    id: int,
    rid: int,
    service: ClosureService = Depends(get_closure_service),
) -> HTMLResponse:
    """Reject the closure report."""
    service.reject_report(rid)
    return HTMLResponse(
        '<div class="info-banner">Report rejected.</div>'
    )
