"""Transcript routes — upload, parse, analyze, review suggestions."""

from __future__ import annotations

from fastapi import APIRouter, Form, Request, UploadFile, File
from fastapi.responses import HTMLResponse

from src.services.dashboard import DashboardService
from src.services.transcript import TranscriptParser, TranscriptService
from src.web.deps import get_nav_context, templates

router = APIRouter(prefix="/project/{id}/transcript", tags=["transcript"])


def _render(request: Request, template: str, context: dict, project_id: int) -> HTMLResponse:
    """Render a template with nav context and project cookie."""
    nav = get_nav_context(request)
    nav["selected_project_id"] = project_id
    response = templates.TemplateResponse(request, template, {**context, **nav})
    response.set_cookie("seat_selected_project", str(project_id), max_age=60 * 60 * 24 * 30)
    return response


@router.get("/", response_class=HTMLResponse)
async def transcript_page(request: Request, id: int) -> HTMLResponse:
    """Upload form + past transcripts list."""
    dashboard = DashboardService()
    project = dashboard.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)

    service = TranscriptService()
    transcripts = service.list_transcripts(id)

    return _render(request, "transcript.html", {
        "project": project,
        "transcripts": transcripts,
    }, id)


@router.post("/upload", response_class=HTMLResponse)
async def upload_transcript(
    request: Request,
    id: int,
    file: UploadFile = File(...),
) -> HTMLResponse:
    """Parse uploaded file, store, return parsed preview partial."""
    dashboard = DashboardService()
    project = dashboard.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)

    content = await file.read()
    filename = file.filename or "transcript.txt"

    parser = TranscriptParser()
    try:
        parsed = parser.parse(filename, content)
    except (ValueError, ImportError) as exc:
        return HTMLResponse(
            f'<div class="error-banner">{exc}</div>',
            status_code=400,
        )

    if not parsed.segments:
        return HTMLResponse(
            '<div class="error-banner">No speech segments found in transcript.</div>',
            status_code=400,
        )

    service = TranscriptService()
    transcript_id = service.store_transcript(id, parsed)

    return templates.TemplateResponse(request, "partials/transcript_parsed.html", {
        "project": project,
        "parsed": parsed,
        "transcript_id": transcript_id,
    })


@router.post("/paste", response_class=HTMLResponse)
async def paste_transcript(
    request: Request,
    id: int,
    transcript_text: str = Form(...),
) -> HTMLResponse:
    """Parse pasted text, store, return parsed preview partial."""
    dashboard = DashboardService()
    project = dashboard.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)

    text = transcript_text.strip()
    if not text:
        return HTMLResponse(
            '<div class="error-banner">Please enter some text.</div>',
            status_code=400,
        )

    parser = TranscriptParser()
    parsed = parser.parse("pasted-input.txt", text.encode("utf-8"))

    if not parsed.segments:
        return HTMLResponse(
            '<div class="error-banner">No speech segments found in the text.</div>',
            status_code=400,
        )

    service = TranscriptService()
    transcript_id = service.store_transcript(id, parsed)

    return templates.TemplateResponse(request, "partials/transcript_parsed.html", {
        "project": project,
        "parsed": parsed,
        "transcript_id": transcript_id,
    })


@router.delete("/{tid}", response_class=HTMLResponse)
async def delete_transcript(request: Request, id: int, tid: int) -> HTMLResponse:
    """Delete a transcript and redirect back."""
    service = TranscriptService()
    service.delete_transcript(tid)
    return HTMLResponse(
        headers={"HX-Redirect": f"/project/{id}/transcript/"},
        content="",
        status_code=200,
    )


# ------------------------------------------------------------------
# Analysis
# ------------------------------------------------------------------

@router.post("/{tid}/analyze", response_class=HTMLResponse)
async def analyze_transcript(request: Request, id: int, tid: int) -> HTMLResponse:
    """Run LLM analysis on a transcript, return suggestions partial."""
    dashboard = DashboardService()
    project = dashboard.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)

    service = TranscriptService()
    try:
        suggestions = await service.analyze_transcript(tid, project)
    except Exception as exc:
        return HTMLResponse(
            f'<div class="error-banner">Analysis failed: {exc}</div>',
            status_code=500,
        )

    record = service.get_transcript(tid)
    meeting_summary = record.meeting_summary if record else ""

    return templates.TemplateResponse(
        request,
        "partials/transcript_suggestions.html",
        {
            "project": project,
            "transcript_id": tid,
            "suggestions": suggestions,
            "meeting_summary": meeting_summary,
        },
    )


@router.get("/{tid}/suggestions", response_class=HTMLResponse)
async def view_suggestions(request: Request, id: int, tid: int) -> HTMLResponse:
    """Full-page view of suggestions for a transcript."""
    dashboard = DashboardService()
    project = dashboard.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)

    service = TranscriptService()
    record = service.get_transcript(tid)
    if record is None:
        return HTMLResponse("Transcript not found", status_code=404)

    suggestions = service.list_suggestions(tid)

    return _render(request, "transcript_suggestions_page.html", {
        "project": project,
        "transcript": record,
        "transcript_id": tid,
        "suggestions": suggestions,
        "meeting_summary": record.meeting_summary or "",
    }, id)


# ------------------------------------------------------------------
# Accept / Reject suggestions
# ------------------------------------------------------------------

@router.post("/{tid}/suggestions/{sid}/accept", response_class=HTMLResponse)
async def accept_suggestion(request: Request, id: int, tid: int, sid: int) -> HTMLResponse:
    """Accept a suggestion — queue it for approval."""
    dashboard = DashboardService()
    project = dashboard.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)

    service = TranscriptService()
    try:
        sug = await service.accept_suggestion(sid, project)
    except ValueError as exc:
        return HTMLResponse(
            f'<div class="error-banner">{exc}</div>',
            status_code=400,
        )
    if sug is None:
        return HTMLResponse("Suggestion not found", status_code=404)

    return templates.TemplateResponse(
        request,
        "partials/suggestion_row.html",
        {"sug": sug, "project": project, "transcript_id": tid},
    )


@router.post("/{tid}/suggestions/{sid}/reject", response_class=HTMLResponse)
async def reject_suggestion(request: Request, id: int, tid: int, sid: int) -> HTMLResponse:
    """Reject a suggestion."""
    service = TranscriptService()
    sug = service.reject_suggestion(sid)
    if sug is None:
        return HTMLResponse("Suggestion not found", status_code=404)

    dashboard = DashboardService()
    project = dashboard.get_project_by_id(id)

    return templates.TemplateResponse(
        request,
        "partials/suggestion_row.html",
        {"sug": sug, "project": project, "transcript_id": tid},
    )


@router.post("/{tid}/suggestions/accept-all", response_class=HTMLResponse)
async def accept_all_suggestions(request: Request, id: int, tid: int) -> HTMLResponse:
    """Accept all pending suggestions for a transcript."""
    dashboard = DashboardService()
    project = dashboard.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)

    service = TranscriptService()
    await service.accept_all_suggestions(tid, project)

    suggestions = service.list_suggestions(tid)
    record = service.get_transcript(tid)

    return templates.TemplateResponse(
        request,
        "partials/transcript_suggestions.html",
        {
            "project": project,
            "transcript_id": tid,
            "suggestions": suggestions,
            "meeting_summary": record.meeting_summary if record else "",
        },
    )
