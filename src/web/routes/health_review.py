"""Health Review routes — on-demand LLM health check with Q&A flow."""

from __future__ import annotations

import html
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

logger = logging.getLogger(__name__)

from src.services.dashboard import DashboardService
from src.services.health_review import HealthReviewService
from src.web.deps import (
    collect_qa_pairs,
    get_dashboard_service,
    get_health_review_service,
    render_project_page,
    templates,
)

router = APIRouter(prefix="/project/{id}/health-review", tags=["health_review"])


# ------------------------------------------------------------------
# Main page
# ------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
async def health_review_page(
    request: Request,
    id: int,
    dashboard: DashboardService = Depends(get_dashboard_service),
    service: HealthReviewService = Depends(get_health_review_service),
) -> HTMLResponse:
    """Display the health review page with history of past reviews."""
    project = dashboard.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)
    past_reviews = service.list_reviews(id)

    return render_project_page(request, "project_health_review.html", {
        "project": project,
        "past_reviews": past_reviews,
    }, id)


# ------------------------------------------------------------------
# LLM Step 1: Ask questions
# ------------------------------------------------------------------

@router.post("/ask", response_class=HTMLResponse)
async def health_review_ask(
    request: Request,
    id: int,
    dashboard: DashboardService = Depends(get_dashboard_service),
    service: HealthReviewService = Depends(get_health_review_service),
) -> HTMLResponse:
    """LLM reviews project data and generates clarifying questions."""
    project = dashboard.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)
    try:
        questions = await service.generate_questions(project)
    except Exception as exc:
        logger.exception("Health review /ask failed")
        return HTMLResponse(
            f'<div class="error-banner">Health review failed: {html.escape(str(exc))}</div>',
            status_code=500,
        )

    return templates.TemplateResponse(request, "partials/health_review_questions.html", {
        "project": project,
        "questions": questions,
    })


# ------------------------------------------------------------------
# LLM Step 2: Generate review
# ------------------------------------------------------------------

@router.post("/analyze", response_class=HTMLResponse)
async def health_review_analyze(
    request: Request,
    id: int,
    dashboard: DashboardService = Depends(get_dashboard_service),
    service: HealthReviewService = Depends(get_health_review_service),
) -> HTMLResponse:
    """Receives Q&A answers and produces the structured health review."""
    project = dashboard.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)

    form = await request.form()
    qa_pairs = collect_qa_pairs(form)
    try:
        review = await service.generate_review(project, qa_pairs)
    except Exception as exc:
        return HTMLResponse(
            f'<div class="error-banner">Health review failed: {html.escape(str(exc))}</div>',
            status_code=500,
        )

    # Persist the review
    review_id = service.save_review(project.id, review)
    review["id"] = review_id

    return templates.TemplateResponse(request, "partials/health_review_output.html", {
        "project": project,
        "review": review,
    })
