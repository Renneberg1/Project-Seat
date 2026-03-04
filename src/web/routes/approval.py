"""Approval queue routes (global view)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

logger = logging.getLogger(__name__)

from src.engine.approval import ApprovalEngine
from src.models.approval import ApprovalStatus
from src.services.spinup import SpinUpService
from src.web.deps import get_approval_engine, get_nav_context, get_spinup_service, templates

router = APIRouter(prefix="/approval", tags=["approval"])


@router.get("/", response_class=HTMLResponse)
async def approval_queue(
    request: Request,
    engine: ApprovalEngine = Depends(get_approval_engine),
) -> HTMLResponse:
    """Render the full approval queue page."""
    pending = engine.list_pending()
    all_items = engine.list_all()
    history = [i for i in all_items if i.status != ApprovalStatus.PENDING]
    # Cap at 100, split into last 10 (visible) + 10-100 (expandable)
    capped_history = history[-100:] if len(history) > 100 else history
    recent_history = capped_history[-10:] if len(capped_history) > 10 else capped_history
    older_history = capped_history[:-10] if len(capped_history) > 10 else []

    return templates.TemplateResponse(
        request,
        "approval.html",
        {
            "pending": pending,
            "history": recent_history,
            "older_history": older_history,
            "approval_base_url": "/approval",
            **get_nav_context(request),
        },
    )


@router.post("/{item_id}/approve", response_class=HTMLResponse)
async def approve_item(
    request: Request,
    item_id: int,
    service: SpinUpService = Depends(get_spinup_service),
) -> HTMLResponse:
    """Approve and execute a single item. Returns updated row partial."""
    item = await service.execute_approved_item(item_id)
    return templates.TemplateResponse(
        request,
        "partials/approval_row.html",
        {"item": item},
    )


@router.post("/{item_id}/reject", response_class=HTMLResponse)
async def reject_item(
    request: Request,
    item_id: int,
    engine: ApprovalEngine = Depends(get_approval_engine),
) -> HTMLResponse:
    """Reject a single item. Returns updated row partial."""
    item = engine.reject(item_id)
    return templates.TemplateResponse(
        request,
        "partials/approval_row.html",
        {"item": item},
    )


@router.post("/approve-all", response_class=HTMLResponse)
async def approve_all(
    request: Request,
    engine: ApprovalEngine = Depends(get_approval_engine),
    service: SpinUpService = Depends(get_spinup_service),
) -> HTMLResponse:
    """Approve and execute all pending items in order. Returns refreshed pending list."""
    pending = engine.list_pending()

    for item in pending:
        try:
            await service.execute_approved_item(item.id)
        except Exception:
            logger.warning("approve_all: item %d failed", item.id, exc_info=True)

    # Return the refreshed pending list (should be empty) and history
    pending = engine.list_pending()
    all_items = engine.list_all()
    history = [i for i in all_items if i.status != ApprovalStatus.PENDING]

    return templates.TemplateResponse(
        request,
        "partials/approval_pending.html",
        {
            "pending": pending,
            "history": history,
            "approval_base_url": "/approval",
        },
    )
