"""Project-scoped routes — dashboard, features, documents, approvals."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from src.connectors.base import ConnectorError
from src.database import get_db
from src.engine.approval import ApprovalEngine
from src.models.approval import ApprovalStatus
from src.services.dashboard import DashboardService
from src.services.dhf import DHFService
from src.services.spinup import SpinUpService
from src.web.deps import get_nav_context, templates

router = APIRouter(prefix="/project", tags=["project"])


def _project_response(request: Request, project_id: int):
    """Build a response that sets the project cookie."""
    # Returns (response, set_cookie) — caller must set cookie on the response.
    # We handle this in a middleware-like pattern via _render helper below.
    pass  # not used directly; see _render


def _render(request: Request, template: str, context: dict, project_id: int) -> HTMLResponse:
    """Render a template and set the project selection cookie."""
    nav = get_nav_context(request)
    nav["selected_project_id"] = project_id
    response = templates.TemplateResponse(
        request,
        template,
        {**context, **nav},
    )
    response.set_cookie("seat_selected_project", str(project_id), max_age=60 * 60 * 24 * 30)
    return response


# ------------------------------------------------------------------
# Project Dashboard
# ------------------------------------------------------------------

@router.get("/{id}/dashboard", response_class=HTMLResponse)
async def project_dashboard(request: Request, id: int) -> HTMLResponse:
    """Single-project summary: goal, risks, decisions, documents, approvals."""
    service = DashboardService()
    project = service.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)

    summary = await service.get_project_summary(project)

    dhf_service = DHFService()
    dhf_summary = await dhf_service.get_dhf_summary(project)

    engine = ApprovalEngine()
    recent_approvals = engine.list_all(project_id=id)
    # Show last 10
    recent_approvals = recent_approvals[-10:] if len(recent_approvals) > 10 else recent_approvals

    return _render(request, "project_dashboard.html", {
        "project": project,
        "summary": summary,
        "dhf_summary": dhf_summary,
        "recent_approvals": recent_approvals,
    }, id)


# ------------------------------------------------------------------
# Features (Initiatives)
# ------------------------------------------------------------------

@router.get("/{id}/features", response_class=HTMLResponse)
async def project_features(request: Request, id: int) -> HTMLResponse:
    """Initiative list with progress (done/total Epics, Tasks)."""
    service = DashboardService()
    project = service.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)

    initiatives = await service.get_initiatives(project)

    return _render(request, "project_features.html", {
        "project": project,
        "initiatives": initiatives,
    }, id)


@router.get("/{id}/features/{key}", response_class=HTMLResponse)
async def initiative_detail(request: Request, id: int, key: str) -> HTMLResponse:
    """Initiative drilldown — Epics with child Tasks."""
    service = DashboardService()
    project = service.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)

    detail = await service.get_initiative_detail(key)
    if detail is None:
        return HTMLResponse("Initiative not found", status_code=404)

    return _render(request, "initiative_detail.html", {
        "project": project,
        "detail": detail,
    }, id)


# ------------------------------------------------------------------
# Documents (DHF tracking)
# ------------------------------------------------------------------

@router.get("/{id}/documents", response_class=HTMLResponse)
async def project_documents(request: Request, id: int, area: str | None = None) -> HTMLResponse:
    """DHF document status table with optional area filter."""
    service = DashboardService()
    project = service.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)

    documents: list = []
    areas: list[str] = []
    error: str | None = None

    if project.dhf_draft_root_id and project.dhf_released_root_id:
        dhf_service = DHFService()
        try:
            documents, areas = await dhf_service.get_dhf_table(project)
            if area:
                documents = [d for d in documents if d.area == area]
        except ConnectorError as exc:
            error = str(exc)

    return _render(request, "project_documents.html", {
        "project": project,
        "documents": documents,
        "areas": areas,
        "selected_area": area,
        "error": error,
    }, id)


@router.post("/{id}/documents/config", response_class=HTMLResponse)
async def save_dhf_config(
    request: Request,
    id: int,
    dhf_draft_root_id: str = Form(""),
    dhf_released_root_id: str = Form(""),
) -> RedirectResponse:
    """Save DHF root page IDs for a project."""
    import src.config
    with get_db(src.config.settings.db_path) as conn:
        conn.execute(
            "UPDATE projects SET dhf_draft_root_id = ?, dhf_released_root_id = ? WHERE id = ?",
            (dhf_draft_root_id.strip() or None, dhf_released_root_id.strip() or None, id),
        )
        conn.commit()
    return RedirectResponse(f"/project/{id}/documents", status_code=303)


# ------------------------------------------------------------------
# Project-scoped Approvals
# ------------------------------------------------------------------

@router.get("/{id}/approvals", response_class=HTMLResponse)
async def project_approvals(request: Request, id: int) -> HTMLResponse:
    """Approval queue filtered to this project."""
    service = DashboardService()
    project = service.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)

    engine = ApprovalEngine()
    pending = engine.list_pending(project_id=id)
    all_items = engine.list_all(project_id=id)
    history = [i for i in all_items if i.status != ApprovalStatus.PENDING]

    return _render(request, "project_approvals.html", {
        "project": project,
        "pending": pending,
        "history": history,
        "approval_base_url": f"/project/{id}/approvals",
    }, id)


@router.post("/{id}/approvals/{item_id}/approve", response_class=HTMLResponse)
async def approve_item(request: Request, id: int, item_id: int) -> HTMLResponse:
    """Approve and execute a single item. Returns updated row partial."""
    service = SpinUpService()
    item = await service.execute_approved_item(item_id)
    return templates.TemplateResponse(
        request,
        "partials/approval_row.html",
        {"item": item},
    )


@router.post("/{id}/approvals/{item_id}/reject", response_class=HTMLResponse)
async def reject_item(request: Request, id: int, item_id: int) -> HTMLResponse:
    """Reject a single item. Returns updated row partial."""
    engine = ApprovalEngine()
    item = engine.reject(item_id)
    return templates.TemplateResponse(
        request,
        "partials/approval_row.html",
        {"item": item},
    )


@router.post("/{id}/approvals/approve-all", response_class=HTMLResponse)
async def approve_all(request: Request, id: int) -> HTMLResponse:
    """Approve and execute all pending items for this project."""
    engine = ApprovalEngine()
    service = SpinUpService()
    pending = engine.list_pending(project_id=id)

    for item in pending:
        try:
            await service.execute_approved_item(item.id)
        except Exception:
            pass

    pending = engine.list_pending(project_id=id)
    all_items = engine.list_all(project_id=id)
    history = [i for i in all_items if i.status != ApprovalStatus.PENDING]

    return templates.TemplateResponse(
        request,
        "partials/approval_pending.html",
        {
            "pending": pending,
            "history": history,
            "approval_base_url": f"/project/{id}/approvals",
        },
    )
