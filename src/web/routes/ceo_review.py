"""CEO Review routes — LLM-powered fortnightly status update for CEO Review page."""

from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

logger = logging.getLogger(__name__)

from src.connectors.jira import JiraConnector
from src.engine.mentions import resolve_confluence_mentions
from src.services.ceo_review import CeoReviewService
from src.services.dashboard import DashboardService
from src.web.deps import get_nav_context, templates

router = APIRouter(prefix="/project/{id}/ceo-review", tags=["ceo_review"])


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
async def ceo_review_page(request: Request, id: int) -> HTMLResponse:
    """Display the CEO Review page with PM notes form and past reviews."""
    dashboard = DashboardService()
    project = dashboard.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)

    service = CeoReviewService()

    # Auto-discover CEO Review page if not yet set
    if not project.confluence_ceo_review_id and project.confluence_charter_id:
        try:
            page_id = await service.discover_ceo_review_page(project)
            if page_id:
                from src.database import get_db
                with get_db() as conn:
                    conn.execute(
                        "UPDATE projects SET confluence_ceo_review_id = ? WHERE id = ?",
                        (page_id, project.id),
                    )
                    conn.commit()
                project.confluence_ceo_review_id = page_id
                logger.info("Auto-discovered CEO Review page %s for project %d", page_id, id)
        except Exception as exc:
            logger.warning("CEO review page auto-discovery failed: %s", exc)

    past_reviews = service.list_reviews(id)

    return _render(request, "project_ceo_review.html", {
        "project": project,
        "past_reviews": past_reviews,
    }, id)


# ------------------------------------------------------------------
# LLM Step 1: Ask questions
# ------------------------------------------------------------------

@router.post("/ask", response_class=HTMLResponse)
async def ceo_review_ask(request: Request, id: int) -> HTMLResponse:
    """Gather context, compute metrics, ask LLM for clarifying questions."""
    dashboard = DashboardService()
    project = dashboard.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)

    form = await request.form()
    pm_notes = str(form.get("pm_notes", ""))

    service = CeoReviewService()
    try:
        questions, metrics = await service.generate_questions(project, pm_notes)
    except Exception as exc:
        logger.exception("CEO review /ask failed")
        return HTMLResponse(
            f'<div class="error-banner">CEO review failed: {exc}</div>',
            status_code=500,
        )

    return templates.TemplateResponse(request, "partials/ceo_review_questions.html", {
        "project": project,
        "questions": questions,
        "pm_notes": pm_notes,
    })


# ------------------------------------------------------------------
# LLM Step 2: Generate review
# ------------------------------------------------------------------

@router.post("/analyze", response_class=HTMLResponse)
async def ceo_review_analyze(request: Request, id: int) -> HTMLResponse:
    """Receives Q&A answers + PM notes, produces the CEO review."""
    dashboard = DashboardService()
    project = dashboard.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)

    form = await request.form()
    pm_notes = str(form.get("pm_notes", ""))

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

    service = CeoReviewService()
    try:
        review = await service.generate_review(project, pm_notes, qa_pairs)
    except Exception as exc:
        logger.exception("CEO review /analyze failed")
        return HTMLResponse(
            f'<div class="error-banner">CEO review failed: {exc}</div>',
            status_code=500,
        )

    # Render Confluence XHTML and resolve @mentions
    xhtml = service.render_confluence_xhtml(review)
    jira = JiraConnector()
    try:
        xhtml = await resolve_confluence_mentions(xhtml, jira)
    finally:
        await jira.close()
    review_id = service.save_review(project.id, review, xhtml)
    review["id"] = review_id

    return templates.TemplateResponse(request, "partials/ceo_review_preview.html", {
        "project": project,
        "review": review,
        "review_id": review_id,
    })


# ------------------------------------------------------------------
# Accept / Reject
# ------------------------------------------------------------------

@router.post("/{rid}/accept", response_class=HTMLResponse)
async def ceo_review_accept(request: Request, id: int, rid: int) -> HTMLResponse:
    """Accept and queue the review for Confluence publish."""
    dashboard = DashboardService()
    project = dashboard.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)

    service = CeoReviewService()
    try:
        result = service.accept_review(rid, project)
    except ValueError as exc:
        return HTMLResponse(
            f'<div class="error-banner">{exc}</div>',
            status_code=400,
        )

    if result and result.status.value == "queued":
        return HTMLResponse(
            '<div class="success-banner">CEO Review queued for approval. '
            'Check the <a href="/approval/">Approval Queue</a>.</div>'
        )
    return HTMLResponse(
        '<div class="error-banner">Could not queue review. It may have already been processed.</div>',
        status_code=400,
    )


@router.post("/{rid}/reject", response_class=HTMLResponse)
async def ceo_review_reject(request: Request, id: int, rid: int) -> HTMLResponse:
    """Reject the CEO review."""
    service = CeoReviewService()
    service.reject_review(rid)
    return HTMLResponse(
        '<div class="info-banner">Review rejected.</div>'
    )
