"""Knowledge base routes — action items, notes, insights per project."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from src.services.dashboard import DashboardService
from src.services.knowledge import KnowledgeService
from src.web.deps import (
    get_dashboard_service,
    get_knowledge_service,
    render_project_page,
    templates,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/project/{id}/knowledge", tags=["knowledge"])


@router.get("/", response_class=HTMLResponse)
async def knowledge_page(
    request: Request,
    id: int,
    tab: str = "actions",
    dashboard: DashboardService = Depends(get_dashboard_service),
    knowledge: KnowledgeService = Depends(get_knowledge_service),
) -> HTMLResponse:
    """Display the knowledge base page with tabs."""
    project = dashboard.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)

    action_items = knowledge.list_action_items(id)
    notes = knowledge.list_knowledge_entries(id, "note")
    insights = knowledge.list_knowledge_entries(id, "insight")
    counts = knowledge.count_action_items(id)

    return render_project_page(request, "project_knowledge.html", {
        "project": project,
        "action_items": action_items,
        "notes": notes,
        "insights": insights,
        "action_counts": counts,
        "active_tab": tab,
    }, id)


@router.post("/action-items/{aid}/status", response_class=HTMLResponse)
async def update_action_status(
    request: Request,
    id: int,
    aid: int,
    knowledge: KnowledgeService = Depends(get_knowledge_service),
) -> HTMLResponse:
    """Update an action item's status."""
    form = await request.form()
    status = str(form.get("status", "open"))
    knowledge.update_action_item_status(aid, status)

    item = knowledge._repo.get_action_item(aid)
    return templates.TemplateResponse(request, "partials/action_item_row.html", {
        "item": item,
        "project_id": id,
    })


@router.post("/action-items/add", response_class=HTMLResponse)
async def add_action_item(
    request: Request,
    id: int,
    dashboard: DashboardService = Depends(get_dashboard_service),
    knowledge: KnowledgeService = Depends(get_knowledge_service),
) -> HTMLResponse:
    """Manually add an action item."""
    form = await request.form()
    title = str(form.get("title", "")).strip()
    owner = str(form.get("owner", "")).strip()
    due_date = str(form.get("due_date", "")).strip() or None

    if not title:
        return HTMLResponse("Title is required", status_code=400)

    knowledge.add_action_item(id, title, owner, due_date)

    # Re-render full page
    project = dashboard.get_project_by_id(id)
    action_items = knowledge.list_action_items(id)
    notes = knowledge.list_knowledge_entries(id, "note")
    insights = knowledge.list_knowledge_entries(id, "insight")
    counts = knowledge.count_action_items(id)

    return render_project_page(request, "project_knowledge.html", {
        "project": project,
        "action_items": action_items,
        "notes": notes,
        "insights": insights,
        "action_counts": counts,
        "active_tab": "actions",
    }, id)


@router.post("/entries/add", response_class=HTMLResponse)
async def add_knowledge_entry(
    request: Request,
    id: int,
    dashboard: DashboardService = Depends(get_dashboard_service),
    knowledge: KnowledgeService = Depends(get_knowledge_service),
) -> HTMLResponse:
    """Manually add a knowledge entry (note or insight)."""
    form = await request.form()
    entry_type = str(form.get("entry_type", "note"))
    title = str(form.get("title", "")).strip()
    content = str(form.get("content", "")).strip()
    tags_raw = str(form.get("tags", "")).strip()
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if tags_raw else []

    if not title:
        return HTMLResponse("Title is required", status_code=400)

    knowledge.add_knowledge_entry(id, entry_type, title, content, tags)

    project = dashboard.get_project_by_id(id)
    action_items = knowledge.list_action_items(id)
    notes = knowledge.list_knowledge_entries(id, "note")
    insights = knowledge.list_knowledge_entries(id, "insight")
    counts = knowledge.count_action_items(id)

    return render_project_page(request, "project_knowledge.html", {
        "project": project,
        "action_items": action_items,
        "notes": notes,
        "insights": insights,
        "action_counts": counts,
        "active_tab": "notes" if entry_type == "note" else "insights",
    }, id)


@router.post("/entries/{eid}/publish", response_class=HTMLResponse)
async def publish_entry(
    request: Request,
    id: int,
    eid: int,
    dashboard: DashboardService = Depends(get_dashboard_service),
    knowledge: KnowledgeService = Depends(get_knowledge_service),
) -> HTMLResponse:
    """Queue a knowledge entry for Confluence publish."""
    project = dashboard.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)

    try:
        await knowledge.publish_to_confluence(eid, project)
    except ValueError as exc:
        return HTMLResponse(str(exc), status_code=400)

    entry = knowledge._repo.get_knowledge_entry(eid)
    return templates.TemplateResponse(request, "partials/knowledge_entry_card.html", {
        "entry": entry,
        "project_id": id,
    })


@router.get("/search", response_class=HTMLResponse)
async def search_knowledge(
    request: Request,
    id: int,
    q: str = "",
    dashboard: DashboardService = Depends(get_dashboard_service),
    knowledge: KnowledgeService = Depends(get_knowledge_service),
) -> HTMLResponse:
    """Search knowledge entries."""
    project = dashboard.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)

    results = knowledge.search_knowledge(id, q) if q else []

    return render_project_page(request, "project_knowledge.html", {
        "project": project,
        "action_items": [],
        "notes": [e for e in results if e.entry_type == "note"],
        "insights": [e for e in results if e.entry_type == "insight"],
        "action_counts": knowledge.count_action_items(id),
        "active_tab": "search",
        "search_query": q,
        "search_results": results,
    }, id)
