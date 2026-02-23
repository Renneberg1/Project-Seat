"""Health Review routes — on-demand LLM health check with Q&A flow."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

logger = logging.getLogger(__name__)

from src.services.dashboard import DashboardService
from src.services.health_review import HealthReviewService
from src.web.deps import get_nav_context, templates

router = APIRouter(prefix="/project/{id}/health-review", tags=["health_review"])


def _render(request: Request, template: str, context: dict, project_id: int) -> HTMLResponse:
    """Render a template with nav context and project cookie."""
    nav = get_nav_context(request)
    nav["selected_project_id"] = project_id
    response = templates.TemplateResponse(request, template, {**context, **nav})
    response.set_cookie("seat_selected_project", str(project_id), max_age=60 * 60 * 24 * 30)
    return response


# ------------------------------------------------------------------
# Main page
# ------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
async def health_review_page(request: Request, id: int) -> HTMLResponse:
    """Display the health review page with history of past reviews."""
    dashboard = DashboardService()
    project = dashboard.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)

    service = HealthReviewService()
    past_reviews = service.list_reviews(id)

    return _render(request, "project_health_review.html", {
        "project": project,
        "past_reviews": past_reviews,
    }, id)


# ------------------------------------------------------------------
# LLM Step 1: Ask questions
# ------------------------------------------------------------------

@router.post("/ask", response_class=HTMLResponse)
async def health_review_ask(request: Request, id: int) -> HTMLResponse:
    """LLM reviews project data and generates clarifying questions."""
    dashboard = DashboardService()
    project = dashboard.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)

    service = HealthReviewService()
    try:
        questions = await service.generate_questions(project)
    except Exception as exc:
        logger.exception("Health review /ask failed")
        return HTMLResponse(
            f'<div class="error-banner">Health review failed: {exc}</div>',
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
async def health_review_analyze(request: Request, id: int) -> HTMLResponse:
    """Receives Q&A answers and produces the structured health review."""
    dashboard = DashboardService()
    project = dashboard.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)

    form = await request.form()

    # Collect Q&A pairs from form fields
    qa_pairs: list[dict[str, str]] = []
    i = 0
    while True:
        q = form.get(f"question_{i}")
        a = form.get(f"answer_{i}")
        if q is None:
            break
        qa_pairs.append({"question": str(q), "answer": str(a or "")})
        i += 1

    service = HealthReviewService()
    try:
        review = await service.generate_review(project, qa_pairs)
    except Exception as exc:
        return HTMLResponse(
            f'<div class="error-banner">Health review failed: {exc}</div>',
            status_code=500,
        )

    # Persist the review
    review_id = service.save_review(project.id, review)
    review["id"] = review_id

    return templates.TemplateResponse(request, "partials/health_review_output.html", {
        "project": project,
        "review": review,
    })
