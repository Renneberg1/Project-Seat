"""Project-scoped routes — dashboard, features, documents, approvals."""

from __future__ import annotations

import asyncio
import logging
import re
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
from src.services.health_review import HealthReviewService
from src.services.release import ReleaseService
from src.services.spinup import SpinUpService
from src.services.team_progress import TeamProgressService, TeamVersionReport
from src.services.team_snapshot import TeamSnapshotService
from src.services.transcript import TranscriptService
from src.web.deps import render_project_page, templates

router = APIRouter(prefix="/project", tags=["project"])


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
    all_approvals = engine.list_all(project_id=id)
    # Cap at 100, split into last 10 (visible) + 10-100 (expandable)
    capped = all_approvals[-100:] if len(all_approvals) > 100 else all_approvals
    recent_approvals = capped[-10:] if len(capped) > 10 else capped
    older_approvals = capped[:-10] if len(capped) > 10 else []

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
    release_pending = release_total - release_published

    transcript_service = TranscriptService()
    transcript_summary = transcript_service.get_transcript_summary(id)

    team_service = TeamProgressService()
    team_reports = await team_service.get_team_reports(project)

    # --- New dashboard context ---
    # Latest health rating (SQLite only, no API call)
    health_svc = HealthReviewService()
    reviews = health_svc.list_reviews(id)
    latest_health_rating = reviews[0]["health_rating"] if reviews else None

    # Overall % done across all teams
    total_issues = sum(r.total_issues for r in team_reports)
    total_done = sum(r.done_count for r in team_reports)
    overall_pct_done = round(100 * total_done / total_issues) if total_issues > 0 else 0
    total_blockers = sum(r.blocker_count for r in team_reports)

    # Risk breakdown by status
    risk_by_status: dict[str, int] = {"Open": 0, "Controlled": 0, "Closed": 0}
    for risk in summary.risks:
        status = risk.status
        if status in risk_by_status:
            risk_by_status[status] += 1
        else:
            risk_by_status["Open"] += 1  # default bucket

    # Days to release
    days_to_release = None
    if summary.goal and summary.goal.due_date:
        try:
            release_date = date.fromisoformat(summary.goal.due_date)
            days_to_release = (release_date - date.today()).days
        except ValueError:
            pass

    return render_project_page(request, "project_dashboard.html", {
        "project": project,
        "summary": summary,
        "dhf_summary": dhf_summary,
        "pi_summary": pi_summary,
        "recent_approvals": recent_approvals,
        "older_approvals": older_approvals,
        "confluence_page_base": confluence_page_base,
        "market_release": market_release,
        "active_locked_release": active_locked,
        "release_published": release_published,
        "release_pending": release_pending,
        "release_total": release_total,
        "transcript_summary": transcript_summary,
        "team_reports": team_reports,
        "latest_health_rating": latest_health_rating,
        "overall_pct_done": overall_pct_done,
        "total_blockers": total_blockers,
        "risk_by_status": risk_by_status,
        "days_to_release": days_to_release,
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
        cache.invalidate(f"team_progress:{project.jira_goal_key}")
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

    return render_project_page(request, "project_features.html", {
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

    return render_project_page(request, "initiative_detail.html", {
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

    return render_project_page(request, "project_documents.html", {
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


@router.post("/{id}/plan/config")
async def save_plan_config(
    request: Request,
    id: int,
    jira_plan_url: str = Form(""),
) -> RedirectResponse:
    """Save Jira Plan URL for a project.

    Accepts either a bare URL or a full ``<iframe src="...">`` snippet
    (which is what Jira Plans "Share > Embed" copies to the clipboard).
    """
    import src.config
    url = _extract_plan_url(jira_plan_url)
    with get_db(src.config.settings.db_path) as conn:
        conn.execute(
            "UPDATE projects SET jira_plan_url = ? WHERE id = ?",
            (url or None, id),
        )
        conn.commit()
    return RedirectResponse(f"/project/{id}/dashboard", status_code=303)


_IFRAME_SRC_RE = re.compile(r"""<iframe\b[^>]*\bsrc\s*=\s*['"]([^'"]+)['"]""", re.IGNORECASE)


def _extract_plan_url(raw: str) -> str:
    """Extract a valid Atlassian plan embed URL from user input.

    Handles three input styles:
    1. Full ``<iframe src="https://...">`` snippet → extracts the src URL
    2. Bare URL (``https://company.atlassian.net/...``)
    3. Empty / invalid → returns ``""``
    """
    raw = raw.strip()
    if not raw:
        return ""

    # If user pasted an <iframe> tag, pull out the src attribute
    m = _IFRAME_SRC_RE.search(raw)
    if m:
        raw = m.group(1).strip()

    if raw.startswith("https://") and "atlassian.net" in raw:
        return raw

    return ""


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
# Team Progress
# ------------------------------------------------------------------


@router.get("/{id}/team-progress", response_class=HTMLResponse)
async def project_team_progress(request: Request, id: int) -> HTMLResponse:
    """Per-team fix version progress (issue counts + story points)."""
    service = DashboardService()
    project = service.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)

    team_service = TeamProgressService()
    reports = await team_service.get_team_reports(project)

    # Save today's snapshot (idempotent — ensures data even without orchestrator)
    snapshot_svc = TeamSnapshotService()
    if reports:
        snapshot_svc.save_snapshot(project, reports)

    # Fetch historical snapshots for burnup chart
    snapshots_json = snapshot_svc.get_snapshots(project.id)

    # Fetch project due date for burnup projection line
    service = DashboardService()
    summary = await service.get_project_summary(project)
    project_due_date = None
    if summary.goal and summary.goal.due_date:
        project_due_date = summary.goal.due_date  # ISO string e.g. "2026-09-01"

    # Compute totals row
    totals = None
    if reports:
        totals = TeamVersionReport(
            team_key="TOTAL",
            version_name=project.name,
            total_issues=sum(r.total_issues for r in reports),
            done_count=sum(r.done_count for r in reports),
            in_progress_count=sum(r.in_progress_count for r in reports),
            todo_count=sum(r.todo_count for r in reports),
            blocker_count=sum(r.blocker_count for r in reports),
            sp_total=sum(r.sp_total for r in reports),
            sp_done=sum(r.sp_done for r in reports),
            sp_in_progress=sum(r.sp_in_progress for r in reports),
            sp_missing_count=sum(r.sp_missing_count for r in reports),
        )

    return render_project_page(request, "project_team_progress.html", {
        "project": project,
        "reports": reports,
        "totals": totals,
        "snapshots_json": snapshots_json,
        "project_due_date": project_due_date,
    }, id)


@router.post("/{id}/team-projects/config")
async def save_team_projects_config(
    request: Request,
    id: int,
    team_projects: str = Form(""),
) -> RedirectResponse:
    """Save team project keys for a project."""
    import json
    import src.config
    # Parse KEY:VERSION pairs (e.g. "AIM:HOP Drop 2, CTCV:HOP Drop 2")
    # Allows duplicate keys with different versions.
    team_list: list[list[str]] = []
    # We need the project name for default version fallback
    service_dash = DashboardService()
    project_obj = service_dash.get_project_by_id(id)
    default_version = project_obj.name if project_obj else ""
    for entry in team_projects.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" in entry:
            key, version = entry.split(":", 1)
            team_list.append([key.strip().upper(), version.strip()])
        else:
            team_list.append([entry.upper(), default_version])
    with get_db(src.config.settings.db_path) as conn:
        conn.execute(
            "UPDATE projects SET team_projects = ? WHERE id = ?",
            (json.dumps(team_list) if team_list else None, id),
        )
        conn.commit()
    # Invalidate any cached team progress for this project
    service = DashboardService()
    project = service.get_project_by_id(id)
    if project:
        cache.invalidate(f"team_progress:{project.jira_goal_key}")
    return RedirectResponse(f"/project/{id}/team-progress", status_code=303)


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
    # Cap at 100, split into last 10 (visible) + 10-100 (expandable)
    capped_history = history[-100:] if len(history) > 100 else history
    recent_history = capped_history[-10:] if len(capped_history) > 10 else capped_history
    older_history = capped_history[:-10] if len(capped_history) > 10 else []

    return render_project_page(request, "project_approvals.html", {
        "project": project,
        "pending": pending,
        "history": recent_history,
        "older_history": older_history,
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
