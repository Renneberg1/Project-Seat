"""Approval queue routes."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from src.engine.approval import ApprovalEngine
from src.models.approval import ApprovalStatus
from src.services.spinup import SpinUpService
from src.web.deps import templates

router = APIRouter(prefix="/approval", tags=["approval"])


@router.get("/", response_class=HTMLResponse)
async def approval_queue(request: Request) -> HTMLResponse:
    """Render the full approval queue page."""
    engine = ApprovalEngine()
    pending = engine.list_pending()
    all_items = engine.list_all()
    history = [i for i in all_items if i.status != ApprovalStatus.PENDING]

    return templates.TemplateResponse(
        request,
        "approval.html",
        {"pending": pending, "history": history},
    )


@router.post("/{item_id}/approve", response_class=HTMLResponse)
async def approve_item(request: Request, item_id: int) -> HTMLResponse:
    """Approve and execute a single item. Returns updated row partial."""
    service = SpinUpService()
    item = await service.execute_approved_item(item_id)
    return templates.TemplateResponse(
        request,
        "partials/approval_row.html",
        {"item": item},
    )


@router.post("/{item_id}/reject", response_class=HTMLResponse)
async def reject_item(request: Request, item_id: int) -> HTMLResponse:
    """Reject a single item. Returns updated row partial."""
    engine = ApprovalEngine()
    item = engine.reject(item_id)
    return templates.TemplateResponse(
        request,
        "partials/approval_row.html",
        {"item": item},
    )


@router.post("/approve-all", response_class=HTMLResponse)
async def approve_all(request: Request) -> HTMLResponse:
    """Approve and execute all pending items in order. Returns refreshed pending list."""
    engine = ApprovalEngine()
    service = SpinUpService()
    pending = engine.list_pending()

    for item in pending:
        try:
            await service.execute_approved_item(item.id)
        except Exception:
            pass  # Individual failures are captured in the item status

    # Return the refreshed pending list (should be empty) and history
    pending = engine.list_pending()
    all_items = engine.list_all()
    history = [i for i in all_items if i.status != ApprovalStatus.PENDING]

    return templates.TemplateResponse(
        request,
        "partials/approval_pending.html",
        {"pending": pending, "history": history},
    )
