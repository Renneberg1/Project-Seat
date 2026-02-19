"""Import existing project routes."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from src.connectors.base import ConnectorError
from src.services.import_project import ImportService
from src.web.deps import get_nav_context, templates

router = APIRouter(prefix="/import", tags=["import"])


@router.get("/", response_class=HTMLResponse)
async def import_form(request: Request) -> HTMLResponse:
    """Render the import form page."""
    return templates.TemplateResponse(
        request,
        "import.html",
        {**get_nav_context(request)},
    )


@router.post("/fetch", response_class=HTMLResponse)
async def import_fetch(
    request: Request,
    goal_key: str = Form(...),
) -> HTMLResponse:
    """HTMX: fetch Goal from Jira and return a confirmation partial."""
    goal_key = goal_key.strip().upper()
    service = ImportService()
    try:
        preview = await service.fetch_preview(goal_key)
    except ConnectorError as exc:
        return HTMLResponse(
            f'<div class="error-banner">Failed to fetch {goal_key}: {exc}</div>',
            status_code=200,
        )

    return templates.TemplateResponse(
        request,
        "partials/import_confirm.html",
        {"preview": preview},
    )


@router.post("/save", response_class=HTMLResponse)
async def import_save(
    request: Request,
    goal_key: str = Form(...),
    name: str = Form(...),
    charter_id: str = Form(""),
    xft_id: str = Form(""),
) -> RedirectResponse:
    """Save the imported project to the local DB and redirect to its dashboard."""
    service = ImportService()
    try:
        project_id = service.save_project(
            goal_key=goal_key.strip(),
            name=name.strip(),
            charter_id=charter_id.strip() or None,
            xft_id=xft_id.strip() or None,
        )
    except ValueError as exc:
        return templates.TemplateResponse(
            request,
            "import.html",
            {"error": str(exc), **get_nav_context(request)},
        )

    return RedirectResponse(f"/project/{project_id}/dashboard", status_code=303)
