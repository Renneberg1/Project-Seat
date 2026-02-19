"""Project-scoped routes — dashboard, features, documents, approvals."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

logger = logging.getLogger(__name__)

from src.cache import cache
from src.config import settings as app_settings
from src.connectors.base import ConnectorError
from src.database import get_db
from src.engine.approval import ApprovalEngine
from src.services.import_project import ImportService
from src.models.approval import ApprovalStatus
from src.models.dhf import DocumentStatus
from src.models.release import ReleaseStatus
from src.services.dashboard import DashboardService
from src.services.dhf import DHFService
from src.services.release import ReleaseService
from src.services.spinup import SpinUpService
from src.services.transcript import TranscriptService
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

    # Run independent data fetches concurrently
    dhf_service = DHFService()

    async def _fetch_dhf():
        if not project.dhf_draft_root_id or not project.dhf_released_root_id:
            return [], []
        try:
            return await dhf_service.get_dhf_table(project)
        except ConnectorError:
            return [], []

    summary, (dhf_docs, _dhf_areas), pi_ideas = await asyncio.gather(
        service.get_project_summary(project),
        _fetch_dhf(),
        service.get_product_ideas(project),
    )

    # Compute DHF summary locally from the already-fetched docs
    from src.models.dhf import DHFSummary
    if dhf_docs:
        released = sum(1 for d in dhf_docs if d.status == DocumentStatus.RELEASED)
        draft_update = sum(1 for d in dhf_docs if d.status == DocumentStatus.DRAFT_UPDATE)
        in_draft = sum(1 for d in dhf_docs if d.status == DocumentStatus.IN_DRAFT)
        dhf_summary = DHFSummary(
            total_count=len(dhf_docs), released_count=released,
            draft_update_count=draft_update, in_draft_count=in_draft,
        )
    else:
        dhf_summary = DHFSummary(
            total_count=0, released_count=0, draft_update_count=0, in_draft_count=0,
        )

    pi_summary = service.summarise_product_ideas(pi_ideas)

    engine = ApprovalEngine()
    recent_approvals = engine.list_all(project_id=id)
    # Show last 10
    recent_approvals = recent_approvals[-10:] if len(recent_approvals) > 10 else recent_approvals

    confluence_page_base = f"https://{app_settings.atlassian.domain}.atlassian.net/wiki/spaces/{app_settings.atlassian.confluence_space_key}/pages"

    market_release = None
    if summary.goal and summary.goal.due_date:
        try:
            tech = date.fromisoformat(summary.goal.due_date)
            mr = tech.replace(month=tech.month + 1) if tech.month < 12 else tech.replace(year=tech.year + 1, month=1)
            market_release = mr.isoformat()
        except ValueError:
            logger.warning("Failed to compute market release date from %s", summary.goal.due_date)

    # Check for active locked release for the Documents card
    release_service = ReleaseService()
    releases = release_service.list_releases(id)
    active_locked = next((r for r in releases if r.locked), None)
    release_published = 0
    release_total = 0
    if active_locked:
        locked_selected = release_service.get_selected_documents(active_locked.id)
        release_total = len(locked_selected)
        if release_total > 0 and dhf_docs:
            current_versions = {d.title: d.released_version for d in dhf_docs}
            snapshot = active_locked.version_snapshot or {}
            statuses = release_service.compute_release_status(
                snapshot, current_versions, locked_selected,
            )
            release_published = sum(1 for _, s in statuses if s == ReleaseStatus.PUBLISHED)

    transcript_service = TranscriptService()
    transcript_summary = transcript_service.get_transcript_summary(id)

    return _render(request, "project_dashboard.html", {
        "project": project,
        "summary": summary,
        "dhf_summary": dhf_summary,
        "pi_summary": pi_summary,
        "recent_approvals": recent_approvals,
        "confluence_page_base": confluence_page_base,
        "market_release": market_release,
        "active_locked_release": active_locked,
        "release_published": release_published,
        "release_total": release_total,
        "transcript_summary": transcript_summary,
    }, id)


@router.delete("/{id}", response_class=HTMLResponse)
async def delete_project(request: Request, id: int) -> HTMLResponse:
    """Remove a project from the local DB (no Jira/Confluence changes)."""
    service = ImportService()
    service.delete_project(id)
    return HTMLResponse(headers={"HX-Redirect": "/phases/"}, content="", status_code=200)


# ------------------------------------------------------------------
# Cache refresh
# ------------------------------------------------------------------

@router.post("/{id}/refresh", response_class=HTMLResponse)
async def refresh_project(request: Request, id: int) -> HTMLResponse:
    """Clear cached data for a project so the next load fetches fresh data."""
    service = DashboardService()
    project = service.get_project_by_id(id)
    if project is not None:
        cache.invalidate(f"summary:{project.jira_goal_key}")
        cache.invalidate(f"initiatives:{project.jira_goal_key}")
        if project.pi_version:
            cache.invalidate(f"pi:{project.pi_version}")
        if project.dhf_draft_root_id and project.dhf_released_root_id:
            cache.invalidate(f"dhf:{project.dhf_draft_root_id}:{project.dhf_released_root_id}")
    # Redirect back to the referring page (or dashboard)
    referer = request.headers.get("HX-Current-URL", f"/project/{id}/dashboard")
    return HTMLResponse(headers={"HX-Redirect": referer}, content="", status_code=200)


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

    initiatives, pi_ideas = await asyncio.gather(
        service.get_initiatives(project),
        service.get_product_ideas(project),
    )

    _PI_PRIORITY_ORDER = {"Must Have": 0, "Should Have": 1, "Could Have": 2}
    pi_ideas.sort(key=lambda i: _PI_PRIORITY_ORDER.get(i.release_priority or "", 9))

    return _render(request, "project_features.html", {
        "project": project,
        "initiatives": initiatives,
        "pi_ideas": pi_ideas,
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
async def project_documents(
    request: Request, id: int, area: str | None = None, release_id: int | None = None,
) -> HTMLResponse:
    """DHF document status table with optional area filter and release context."""
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

    # Release context
    release_service = ReleaseService()
    releases = release_service.list_releases(id)
    active_release = None
    selected_docs: set[str] = set()
    release_statuses: dict[str, str] = {}
    published_count = 0
    pending_count = 0

    if release_id:
        active_release = release_service.get_release(release_id)

    if active_release:
        selected_docs = release_service.get_selected_documents(active_release.id)
        if active_release.locked and selected_docs:
            snapshot = active_release.version_snapshot or {}
            current_versions = {d.title: d.released_version for d in documents}
            statuses = release_service.compute_release_status(
                snapshot, current_versions, selected_docs,
            )
            release_statuses = {title: status.value for title, status in statuses}
            published_count = sum(1 for _, s in statuses if s == ReleaseStatus.PUBLISHED)
            pending_count = sum(1 for _, s in statuses if s == ReleaseStatus.PENDING)

    return _render(request, "project_documents.html", {
        "project": project,
        "documents": documents,
        "areas": areas,
        "selected_area": area,
        "error": error,
        "releases": releases,
        "active_release": active_release,
        "selected_docs": selected_docs,
        "release_statuses": release_statuses,
        "published_count": published_count,
        "pending_count": pending_count,
    }, id)


@router.post("/{id}/pi/config")
async def save_pi_config(
    request: Request,
    id: int,
    pi_version: str = Form(""),
) -> RedirectResponse:
    """Save PI version for a project."""
    import src.config
    with get_db(src.config.settings.db_path) as conn:
        conn.execute(
            "UPDATE projects SET pi_version = ? WHERE id = ?",
            (pi_version.strip() or None, id),
        )
        conn.commit()
    return RedirectResponse(f"/project/{id}/dashboard", status_code=303)


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
# Releases (scope-freeze & publish tracking)
# ------------------------------------------------------------------

@router.post("/{id}/releases")
async def create_release(
    request: Request, id: int, release_name: str = Form(""),
) -> RedirectResponse:
    """Create a new named release for a project."""
    name = release_name.strip()
    if not name:
        return RedirectResponse(f"/project/{id}/documents", status_code=303)
    service = ReleaseService()
    release = service.create_release(id, name)
    return RedirectResponse(f"/project/{id}/documents?release_id={release.id}", status_code=303)


@router.delete("/{id}/releases/{release_id}", response_class=HTMLResponse)
async def delete_release(request: Request, id: int, release_id: int) -> HTMLResponse:
    """Delete a release and its document selections."""
    service = ReleaseService()
    service.delete_release(release_id)
    return HTMLResponse(
        headers={"HX-Redirect": f"/project/{id}/documents"}, content="", status_code=200,
    )


@router.post("/{id}/releases/{release_id}/documents")
async def save_release_documents(
    request: Request, id: int, release_id: int,
) -> RedirectResponse:
    """Save document selection for a release (checkboxes)."""
    form = await request.form()
    titles = set(form.getlist("doc_titles"))
    service = ReleaseService()
    service.save_documents(release_id, titles)
    return RedirectResponse(f"/project/{id}/documents?release_id={release_id}", status_code=303)


@router.post("/{id}/releases/{release_id}/lock")
async def lock_release(request: Request, id: int, release_id: int) -> RedirectResponse:
    """Lock release scope — save document selection from form, then snapshot versions."""
    dashboard = DashboardService()
    project = dashboard.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)

    release_service = ReleaseService()

    # Save document selection submitted with the lock form
    form = await request.form()
    form_titles = set(form.getlist("doc_titles"))
    if form_titles:
        release_service.save_documents(release_id, form_titles)

    selected = release_service.get_selected_documents(release_id)

    # Build version snapshot from current DHF data
    snapshot: dict[str, str | None] = {}
    if project.dhf_draft_root_id and project.dhf_released_root_id:
        dhf_service = DHFService()
        try:
            documents, _ = await dhf_service.get_dhf_table(project)
            for doc in documents:
                if doc.title in selected:
                    snapshot[doc.title] = doc.released_version
        except ConnectorError:
            logger.warning("Failed to fetch DHF versions for release lock — snapshot will be incomplete", exc_info=True)

    release_service.lock_release(release_id, snapshot)
    return RedirectResponse(f"/project/{id}/documents?release_id={release_id}", status_code=303)


@router.post("/{id}/releases/{release_id}/unlock")
async def unlock_release(request: Request, id: int, release_id: int) -> RedirectResponse:
    """Unlock release scope (preserves snapshot)."""
    service = ReleaseService()
    service.unlock_release(release_id)
    return RedirectResponse(f"/project/{id}/documents?release_id={release_id}", status_code=303)


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
        {"item": item, "approval_base_url": f"/project/{id}/approvals"},
    )


@router.post("/{id}/approvals/{item_id}/retry", response_class=HTMLResponse)
async def retry_item(request: Request, id: int, item_id: int) -> HTMLResponse:
    """Reset a failed item to pending so it can be re-approved."""
    engine = ApprovalEngine()
    try:
        engine.retry(item_id)
    except ValueError:
        return HTMLResponse("Item is not in failed state", status_code=400)
    # Redirect to refresh the full approvals page
    return HTMLResponse(
        headers={"HX-Redirect": f"/project/{id}/approvals"},
        content="",
        status_code=200,
    )


@router.post("/{id}/approvals/approve-all", response_class=HTMLResponse)
async def approve_all(request: Request, id: int) -> HTMLResponse:
    """Approve and execute all pending items for this project."""
    engine = ApprovalEngine()
    service = SpinUpService()
    pending = engine.list_pending(project_id=id)

    success_count = 0
    fail_count = 0
    for item in pending:
        try:
            await service.execute_approved_item(item.id)
            success_count += 1
        except Exception:
            fail_count += 1
            logger.warning("Failed to execute approval item %d", item.id, exc_info=True)

    logger.info("Approve-all for project %d: %d succeeded, %d failed", id, success_count, fail_count)

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
