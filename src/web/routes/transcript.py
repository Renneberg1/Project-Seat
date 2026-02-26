"""Transcript routes — upload, parse, analyze, review suggestions."""

from __future__ import annotations

import html
import json

from fastapi import APIRouter, Depends, Form, Request, UploadFile, File
from fastapi.responses import HTMLResponse

from src.services.dashboard import DashboardService
from src.services.risk_refinement import RiskRefinementService
from src.services.transcript import TranscriptService
from src.services.transcript_parser import TranscriptParser
from src.web.deps import (
    get_dashboard_service,
    get_risk_refinement_service,
    get_transcript_parser,
    get_transcript_service,
    render_project_page,
    templates,
)

router = APIRouter(prefix="/project/{id}/transcript", tags=["transcript"])


@router.get("/", response_class=HTMLResponse)
async def transcript_page(
    request: Request,
    id: int,
    dashboard: DashboardService = Depends(get_dashboard_service),
    service: TranscriptService = Depends(get_transcript_service),
) -> HTMLResponse:
    """Upload form + past transcripts list."""
    project = dashboard.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)
    transcripts = service.list_transcripts(id)

    return render_project_page(request, "transcript.html", {
        "project": project,
        "transcripts": transcripts,
    }, id)


@router.post("/upload", response_class=HTMLResponse)
async def upload_transcript(
    request: Request,
    id: int,
    file: UploadFile = File(...),
    dashboard: DashboardService = Depends(get_dashboard_service),
    parser: TranscriptParser = Depends(get_transcript_parser),
    service: TranscriptService = Depends(get_transcript_service),
) -> HTMLResponse:
    """Parse uploaded file, store, return parsed preview partial."""
    project = dashboard.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)

    content = await file.read()
    filename = file.filename or "transcript.txt"
    try:
        parsed = parser.parse(filename, content)
    except (ValueError, ImportError) as exc:
        return HTMLResponse(
            f'<div class="error-banner">{html.escape(str(exc))}</div>',
            status_code=400,
        )

    if not parsed.segments:
        return HTMLResponse(
            '<div class="error-banner">No speech segments found in transcript.</div>',
            status_code=400,
        )

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
    dashboard: DashboardService = Depends(get_dashboard_service),
    parser: TranscriptParser = Depends(get_transcript_parser),
    service: TranscriptService = Depends(get_transcript_service),
) -> HTMLResponse:
    """Parse pasted text, store, return parsed preview partial."""
    project = dashboard.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)

    text = transcript_text.strip()
    if not text:
        return HTMLResponse(
            '<div class="error-banner">Please enter some text.</div>',
            status_code=400,
        )
    parsed = parser.parse("pasted-input.txt", text.encode("utf-8"))

    if not parsed.segments:
        return HTMLResponse(
            '<div class="error-banner">No speech segments found in the text.</div>',
            status_code=400,
        )

    transcript_id = service.store_transcript(id, parsed)

    return templates.TemplateResponse(request, "partials/transcript_parsed.html", {
        "project": project,
        "parsed": parsed,
        "transcript_id": transcript_id,
    })


@router.delete("/{tid}", response_class=HTMLResponse)
async def delete_transcript(
    request: Request,
    id: int,
    tid: int,
    service: TranscriptService = Depends(get_transcript_service),
) -> HTMLResponse:
    """Delete a transcript and redirect back."""
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
async def analyze_transcript(
    request: Request,
    id: int,
    tid: int,
    dashboard: DashboardService = Depends(get_dashboard_service),
    service: TranscriptService = Depends(get_transcript_service),
) -> HTMLResponse:
    """Run LLM analysis on a transcript, return suggestions partial."""
    project = dashboard.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)
    try:
        suggestions = await service.analyze_transcript(tid, project)
    except Exception as exc:
        return HTMLResponse(
            f'<div class="error-banner">Analysis failed: {html.escape(str(exc))}</div>',
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
async def view_suggestions(
    request: Request,
    id: int,
    tid: int,
    dashboard: DashboardService = Depends(get_dashboard_service),
    service: TranscriptService = Depends(get_transcript_service),
) -> HTMLResponse:
    """Full-page view of suggestions for a transcript."""
    project = dashboard.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)
    record = service.get_transcript(tid)
    if record is None:
        return HTMLResponse("Transcript not found", status_code=404)

    suggestions = service.list_suggestions(tid)

    return render_project_page(request, "transcript_suggestions_page.html", {
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
async def accept_suggestion(
    request: Request,
    id: int,
    tid: int,
    sid: int,
    dashboard: DashboardService = Depends(get_dashboard_service),
    service: TranscriptService = Depends(get_transcript_service),
) -> HTMLResponse:
    """Accept a suggestion — queue it for approval."""
    project = dashboard.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)
    try:
        sug = await service.accept_suggestion(sid, project)
    except ValueError as exc:
        return HTMLResponse(
            f'<div class="error-banner">{html.escape(str(exc))}</div>',
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
async def reject_suggestion(
    request: Request,
    id: int,
    tid: int,
    sid: int,
    dashboard: DashboardService = Depends(get_dashboard_service),
    service: TranscriptService = Depends(get_transcript_service),
) -> HTMLResponse:
    """Reject a suggestion."""
    sug = service.reject_suggestion(sid)
    if sug is None:
        return HTMLResponse("Suggestion not found", status_code=404)

    project = dashboard.get_project_by_id(id)

    return templates.TemplateResponse(
        request,
        "partials/suggestion_row.html",
        {"sug": sug, "project": project, "transcript_id": tid},
    )


@router.post("/{tid}/suggestions/accept-all", response_class=HTMLResponse)
async def accept_all_suggestions(
    request: Request,
    id: int,
    tid: int,
    dashboard: DashboardService = Depends(get_dashboard_service),
    service: TranscriptService = Depends(get_transcript_service),
) -> HTMLResponse:
    """Accept all pending suggestions for a transcript."""
    project = dashboard.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)
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


# ------------------------------------------------------------------
# Risk / Decision refinement
# ------------------------------------------------------------------

@router.post("/{tid}/suggestions/{sid}/refine", response_class=HTMLResponse)
async def start_refinement(
    request: Request,
    id: int,
    tid: int,
    sid: int,
    dashboard: DashboardService = Depends(get_dashboard_service),
    refine_service: RiskRefinementService = Depends(get_risk_refinement_service),
) -> HTMLResponse:
    """Start iterative refinement for a risk/decision suggestion."""
    project = dashboard.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)
    try:
        result = await refine_service.start_risk_refinement(sid, project)
    except ValueError as exc:
        return HTMLResponse(
            f'<div class="error-banner">{html.escape(str(exc))}</div>',
            status_code=400,
        )
    except Exception as exc:
        return HTMLResponse(
            f'<div class="error-banner">Refinement failed: {html.escape(str(exc))}</div>',
            status_code=500,
        )

    sug = refine_service.get_suggestion(sid)

    return templates.TemplateResponse(
        request,
        "partials/risk_refine_panel.html",
        {
            "project": project,
            "transcript_id": tid,
            "suggestion_id": sid,
            "suggestion_type": sug.suggestion_type.value if sug else "risk",
            "result": result,
            "risk_draft": json.dumps(result.get("refined_risk", {})),
            "qa_history": json.dumps([]),
            "round_number": 1,
        },
    )


@router.post("/{tid}/suggestions/{sid}/refine/answer", response_class=HTMLResponse)
async def refine_answer(
    request: Request,
    id: int,
    tid: int,
    sid: int,
    dashboard: DashboardService = Depends(get_dashboard_service),
    refine_service: RiskRefinementService = Depends(get_risk_refinement_service),
) -> HTMLResponse:
    """Submit answers to refinement questions and continue the loop."""
    project = dashboard.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)

    form = await request.form()

    risk_draft = json.loads(form.get("risk_draft", "{}"))
    qa_history = json.loads(form.get("qa_history", "[]"))
    round_number = int(form.get("round_number", "1"))

    # Collect new Q&A pairs from form (risk refine has its own pattern)
    idx = 0
    while True:
        q_key = f"question_{idx}"
        a_key = f"answer_{idx}"
        if q_key not in form:
            break
        question = str(form.get(q_key, ""))
        answer = str(form.get(a_key, ""))
        if question:
            qa_history.append({"question": question, "answer": answer})
        idx += 1

    next_round = round_number + 1

    try:
        result = await refine_service.continue_risk_refinement(
            suggestion_id=sid,
            project=project,
            risk_draft=risk_draft,
            qa_history=qa_history,
            round_number=next_round,
        )
    except Exception as exc:
        return HTMLResponse(
            f'<div class="error-banner">Refinement failed: {html.escape(str(exc))}</div>',
            status_code=500,
        )

    sug = refine_service.get_suggestion(sid)

    return templates.TemplateResponse(
        request,
        "partials/risk_refine_panel.html",
        {
            "project": project,
            "transcript_id": tid,
            "suggestion_id": sid,
            "suggestion_type": sug.suggestion_type.value if sug else "risk",
            "result": result,
            "risk_draft": json.dumps(result.get("refined_risk", {})),
            "qa_history": json.dumps(qa_history),
            "round_number": next_round,
        },
    )


@router.post("/{tid}/suggestions/{sid}/refine/apply", response_class=HTMLResponse)
async def apply_refinement(
    request: Request,
    id: int,
    tid: int,
    sid: int,
    dashboard: DashboardService = Depends(get_dashboard_service),
    refine_service: RiskRefinementService = Depends(get_risk_refinement_service),
) -> HTMLResponse:
    """Apply the refined draft to the suggestion."""
    project = dashboard.get_project_by_id(id)
    if project is None:
        return HTMLResponse("Project not found", status_code=404)

    form = await request.form()
    refined_risk = json.loads(form.get("refined_risk", "{}"))
    sug = refine_service.apply_refinement(sid, refined_risk)
    if sug is None:
        return HTMLResponse("Suggestion not found", status_code=404)

    return templates.TemplateResponse(
        request,
        "partials/suggestion_row.html",
        {"sug": sug, "project": project, "transcript_id": tid},
    )
