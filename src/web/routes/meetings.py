"""Unified Meetings page — upload, Zoom sync, assign, analyze, delete."""

from __future__ import annotations

import html
import logging

from fastapi import APIRouter, Depends, Form, Request, UploadFile, File
from fastapi.responses import HTMLResponse

from src.repositories.zoom_repo import ZoomRepository
from src.services.dashboard import DashboardService
from src.services.transcript import TranscriptService
from src.services.transcript_parser import TranscriptParser
from src.services.zoom_ingestion import ZoomIngestionService
from src.web.deps import (
    error_banner,
    get_dashboard_service,
    get_nav_context,
    get_transcript_parser,
    get_transcript_service,
    get_zoom_ingestion_service,
    get_zoom_matching_service,
    get_zoom_repo,
    templates,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["meetings"])


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _build_project_names(dash: DashboardService, project_ids: set[int]) -> dict[int, str]:
    """Build {project_id: name} lookup."""
    result = {}
    for pid in project_ids:
        proj = dash.get_project_by_id(pid)
        if proj:
            result[pid] = proj.name
    return result


def _merge_meeting_rows(
    transcripts: list,
    zoom_recordings: list,
    zoom_repo: ZoomRepository,
) -> list[dict]:
    """Merge transcript_cache rows and pending Zoom recordings into a unified list.

    Each row is a dict with a ``kind`` key ("transcript" or "zoom") plus the data.
    Sorted by date descending.
    """
    rows: list[dict] = []

    for t in transcripts:
        rows.append({
            "kind": "transcript",
            "transcript": t,
            "date": t.created_at,
        })

    # Zoom recordings that don't yet have a transcript in transcript_cache
    # (i.e. still in the Zoom processing pipeline)
    transcript_zoom_uuids: set[int] = set()  # recording IDs that already have transcript rows
    for item in zoom_recordings:
        mappings = zoom_repo.get_mappings_for_recording(item.id)
        rows.append({
            "kind": "zoom",
            "recording": item,
            "mappings": mappings,
            "date": item.start_time,
        })

    # Sort by date descending
    rows.sort(key=lambda r: r["date"] or "", reverse=True)
    return rows


# ------------------------------------------------------------------
# GET /meetings/ — unified page
# ------------------------------------------------------------------

@router.get("/meetings/", response_class=HTMLResponse)
async def meetings_page(
    request: Request,
    source: str | None = None,
    project: int | None = None,
    assigned: str | None = None,
    status: str | None = None,
    connected: str | None = None,
    error: str | None = None,
    service: TranscriptService = Depends(get_transcript_service),
    zoom_repo: ZoomRepository = Depends(get_zoom_repo),
    dash: DashboardService = Depends(get_dashboard_service),
) -> HTMLResponse:
    """Unified meetings page: transcripts + Zoom recordings."""
    zoom_connected = zoom_repo.get_config("zoom_refresh_token") is not None
    last_sync = zoom_repo.get_last_sync_time()

    # Query transcripts
    unassigned = assigned == "false"
    transcripts = service.list_all_transcripts(
        source=source if source in ("manual", "zoom") else None,
        project_id=project,
        unassigned=unassigned,
    )

    # Query Zoom recordings that are still in the processing pipeline
    # (not yet turned into transcript_cache rows)
    pending_statuses = ("new", "downloaded", "matching", "matched", "unmatched", "failed")
    zoom_pending: list = []
    if source != "manual":  # Don't show Zoom rows when filtering to manual only
        if status:
            zoom_pending = zoom_repo.list_by_status(status)
        else:
            all_zoom = zoom_repo.list_all()
            zoom_pending = [r for r in all_zoom if r.processing_status in pending_statuses]

    # Filter transcripts by status if requested
    if status == "failed":
        # Only show transcripts that have no suggestions (failed analysis)
        transcripts = []  # Zoom-only for failed filter

    # Merge into unified rows
    rows = _merge_meeting_rows(transcripts, zoom_pending, zoom_repo)

    # Build project name lookup
    pids: set[int] = set()
    for r in rows:
        if r["kind"] == "transcript" and r["transcript"].project_id:
            pids.add(r["transcript"].project_id)
        elif r["kind"] == "zoom":
            for m in r.get("mappings", []):
                pids.add(m.project_id)
    project_names = _build_project_names(dash, pids)

    # All projects for assign dropdown
    all_projects = dash.list_projects()

    nav = get_nav_context(request)
    return templates.TemplateResponse(request, "meetings.html", {
        **nav,
        "rows": rows,
        "last_sync": last_sync,
        "zoom_connected": zoom_connected,
        "connected": connected == "1",
        "error": error,
        "project_names": project_names,
        "all_projects": all_projects,
        "filter_source": source or "all",
        "filter_assigned": assigned,
        "filter_status": status,
        "filter_project": project,
    })


# ------------------------------------------------------------------
# POST /meetings/upload — upload file (unassigned)
# ------------------------------------------------------------------

@router.post("/meetings/upload", response_class=HTMLResponse)
async def upload_transcript(
    request: Request,
    file: UploadFile = File(...),
    parser: TranscriptParser = Depends(get_transcript_parser),
    service: TranscriptService = Depends(get_transcript_service),
    dash: DashboardService = Depends(get_dashboard_service),
) -> HTMLResponse:
    """Parse uploaded file, store unassigned, return parsed preview."""
    content = await file.read()
    filename = file.filename or "transcript.txt"
    try:
        parsed = parser.parse(filename, content)
    except (ValueError, ImportError) as exc:
        return error_banner(str(exc), status_code=400)

    if not parsed.segments:
        return error_banner("No speech segments found in transcript.", status_code=400)

    transcript_id = service.store_transcript(None, parsed)
    all_projects = dash.list_projects()

    return templates.TemplateResponse(request, "partials/transcript_parsed.html", {
        "parsed": parsed,
        "transcript_id": transcript_id,
        "all_projects": all_projects,
        "unassigned": True,
    })


# ------------------------------------------------------------------
# POST /meetings/paste — paste text (unassigned)
# ------------------------------------------------------------------

@router.post("/meetings/paste", response_class=HTMLResponse)
async def paste_transcript(
    request: Request,
    transcript_text: str = Form(...),
    parser: TranscriptParser = Depends(get_transcript_parser),
    service: TranscriptService = Depends(get_transcript_service),
    dash: DashboardService = Depends(get_dashboard_service),
) -> HTMLResponse:
    """Parse pasted text, store unassigned, return parsed preview."""
    text = transcript_text.strip()
    if not text:
        return error_banner("Please enter some text.", status_code=400)
    parsed = parser.parse("pasted-input.txt", text.encode("utf-8"))

    if not parsed.segments:
        return error_banner("No speech segments found in the text.", status_code=400)

    transcript_id = service.store_transcript(None, parsed)
    all_projects = dash.list_projects()

    return templates.TemplateResponse(request, "partials/transcript_parsed.html", {
        "parsed": parsed,
        "transcript_id": transcript_id,
        "all_projects": all_projects,
        "unassigned": True,
    })


# ------------------------------------------------------------------
# POST /meetings/{tid}/assign-and-analyze
# ------------------------------------------------------------------

@router.post("/meetings/{tid}/assign-and-analyze", response_class=HTMLResponse)
async def assign_and_analyze(
    request: Request,
    tid: int,
    service: TranscriptService = Depends(get_transcript_service),
    dash: DashboardService = Depends(get_dashboard_service),
) -> HTMLResponse:
    """Assign transcript to project(s) and trigger LLM analysis."""
    form = await request.form()
    project_ids_raw = form.getlist("project_ids")
    project_ids = [int(p) for p in project_ids_raw if str(p).isdigit()]

    if not project_ids:
        return error_banner("Please select at least one project.", status_code=400)

    record = service.get_transcript(tid)
    if record is None:
        return HTMLResponse("Transcript not found", status_code=404)

    # Assign first project to the existing transcript row
    first_pid = project_ids[0]
    service.assign_transcript(tid, first_pid)

    # For additional projects, clone the transcript row
    extra_tids: list[tuple[int, int]] = [(tid, first_pid)]
    if len(project_ids) > 1:
        from src.models.transcript import ParsedTranscript, TranscriptSegment
        import json

        processed = record.processed_json
        if processed:
            data = json.loads(processed)
            parsed = ParsedTranscript(
                filename=record.filename,
                segments=[
                    TranscriptSegment(**s) for s in data.get("segments", [])
                ],
                raw_text=record.raw_text,
                speaker_list=data.get("speaker_list", []),
                duration_hint=data.get("duration_hint"),
            )
        else:
            parsed = ParsedTranscript(
                filename=record.filename, segments=[], raw_text=record.raw_text,
                speaker_list=[],
            )

        for pid in project_ids[1:]:
            clone_tid = service.store_transcript(pid, parsed, source=record.source)
            extra_tids.append((clone_tid, pid))

    # Run analysis for each project
    errors: list[str] = []
    for t_id, pid in extra_tids:
        project = dash.get_project_by_id(pid)
        if project is None:
            errors.append(f"Project {pid} not found")
            continue
        try:
            await service.analyze_transcript(t_id, project)
        except Exception as exc:
            logger.error("Analysis failed for transcript %d, project %d: %s", t_id, pid, exc)
            errors.append(f"Analysis failed for {project.name}: {str(exc)[:200]}")

    if errors:
        error_html = '<div class="error-banner">' + "<br>".join(html.escape(e) for e in errors) + '</div>'
        return HTMLResponse(error_html, status_code=500)

    response = HTMLResponse("")
    response.headers["HX-Redirect"] = "/meetings/"
    return response


# ------------------------------------------------------------------
# POST /meetings/{tid}/delete
# ------------------------------------------------------------------

@router.post("/meetings/{tid}/delete", response_class=HTMLResponse)
async def delete_transcript(
    request: Request,
    tid: int,
    service: TranscriptService = Depends(get_transcript_service),
) -> HTMLResponse:
    """Delete a transcript."""
    service.delete_transcript(tid)
    response = HTMLResponse("")
    response.headers["HX-Redirect"] = "/meetings/"
    return response


# ------------------------------------------------------------------
# POST /meetings/{tid}/reassign
# ------------------------------------------------------------------

@router.post("/meetings/{tid}/reassign", response_class=HTMLResponse)
async def reassign_transcript(
    request: Request,
    tid: int,
    service: TranscriptService = Depends(get_transcript_service),
    dash: DashboardService = Depends(get_dashboard_service),
) -> HTMLResponse:
    """Reassign a transcript to a different project and re-run analysis."""
    form = await request.form()
    new_pid_raw = form.get("project_id", "")
    if not str(new_pid_raw).isdigit():
        return error_banner("Please select a project.", status_code=400)
    new_pid = int(new_pid_raw)

    record = service.get_transcript(tid)
    if record is None:
        return HTMLResponse("Transcript not found", status_code=404)

    if record.project_id == new_pid:
        return error_banner("Already assigned to that project.", status_code=400)

    # Reassign: update project_id and clear old suggestions
    service.assign_transcript(tid, new_pid)
    service._repo.delete_suggestions(tid)
    service._repo.update_meeting_summary(tid, None)

    # Re-run analysis
    project = dash.get_project_by_id(new_pid)
    if project:
        try:
            await service.analyze_transcript(tid, project)
        except Exception as exc:
            logger.error("Re-analysis failed after reassign for transcript %d: %s", tid, exc)

    response = HTMLResponse("")
    response.headers["HX-Redirect"] = "/meetings/"
    return response


# ------------------------------------------------------------------
# POST /meetings/zoom/sync
# ------------------------------------------------------------------

@router.post("/meetings/zoom/sync", response_class=HTMLResponse)
async def zoom_sync(
    request: Request,
    service: ZoomIngestionService = Depends(get_zoom_ingestion_service),
    zoom_repo: ZoomRepository = Depends(get_zoom_repo),
    ts: TranscriptService = Depends(get_transcript_service),
    dash: DashboardService = Depends(get_dashboard_service),
) -> HTMLResponse:
    """Trigger Zoom sync and re-render the meetings page."""
    stats = await service.run_full_sync()

    # Re-render the full page with sync stats
    zoom_connected = True
    last_sync = zoom_repo.get_last_sync_time()

    transcripts = ts.list_all_transcripts()
    pending_statuses = ("new", "downloaded", "matching", "matched", "unmatched", "failed")
    all_zoom = zoom_repo.list_all()
    zoom_pending = [r for r in all_zoom if r.processing_status in pending_statuses]

    rows = _merge_meeting_rows(transcripts, zoom_pending, zoom_repo)

    pids: set[int] = set()
    for r in rows:
        if r["kind"] == "transcript" and r["transcript"].project_id:
            pids.add(r["transcript"].project_id)
        elif r["kind"] == "zoom":
            for m in r.get("mappings", []):
                pids.add(m.project_id)
    project_names = _build_project_names(dash, pids)
    all_projects = dash.list_projects()

    nav = get_nav_context(request)
    return templates.TemplateResponse(request, "meetings.html", {
        **nav,
        "rows": rows,
        "last_sync": last_sync,
        "zoom_connected": zoom_connected,
        "sync_stats": stats,
        "project_names": project_names,
        "all_projects": all_projects,
        "filter_source": "all",
    })


# ------------------------------------------------------------------
# POST /meetings/zoom/fetch-by-uuid — manual meeting UUID lookup
# ------------------------------------------------------------------

@router.post("/meetings/zoom/fetch-by-uuid", response_class=HTMLResponse)
async def fetch_by_uuid(
    request: Request,
    meeting_uuid: str = Form(...),
    ingestion: ZoomIngestionService = Depends(get_zoom_ingestion_service),
    zoom_repo: ZoomRepository = Depends(get_zoom_repo),
    ts: TranscriptService = Depends(get_transcript_service),
    dash: DashboardService = Depends(get_dashboard_service),
    parser: TranscriptParser = Depends(get_transcript_parser),
    matcher: "ZoomMatchingService" = Depends(get_zoom_matching_service),
) -> HTMLResponse:
    """Fetch a single meeting's transcript by UUID, then download → match → analyze."""
    meeting_uuid = meeting_uuid.strip()
    if not meeting_uuid:
        return error_banner("Please enter a meeting UUID.", status_code=400)

    try:
        rec_id = await ingestion.fetch_meeting_by_uuid(meeting_uuid)
    except Exception as exc:
        logger.error("Fetch by UUID failed: %s", exc)
        return _render_meetings_page(request, zoom_repo, ts, dash, fetch_result={
            "ok": False, "message": f"Failed to fetch meeting: {html.escape(str(exc)[:300])}",
        })

    if rec_id is None:
        return _render_meetings_page(request, zoom_repo, ts, dash, fetch_result={
            "ok": False, "message": "No transcript found for that meeting UUID.",
        })

    # Process the recording: download → match → analyze
    msg = "Meeting transcript found and added to inbox."
    rec = zoom_repo.get_by_id(rec_id)
    if rec and rec.processing_status == "new":
        try:
            vtt_bytes = await ingestion.download_transcript(rec_id)
            if vtt_bytes:
                parsed = parser.parse(f"{rec.topic}.vtt", vtt_bytes)
                project_ids = await matcher.match_recording(rec, parsed.raw_text[:2000])

                if project_ids:
                    zoom_repo.update_status(rec_id, "matched", match_method=matcher.last_match_method)
                    for pid in project_ids:
                        project = dash.get_project_by_id(pid)
                        if project:
                            tid = ts.store_transcript(pid, parsed, source="zoom")
                            zoom_repo.add_project_mapping(rec_id, pid, tid)
                            await ts.analyze_transcript(tid, project)
                    zoom_repo.update_status(rec_id, "complete")
                    msg = "Meeting fetched, matched, and analyzed."
                else:
                    zoom_repo.update_status(rec_id, "unmatched")
                    msg = "Meeting fetched but could not auto-match to a project. Use Assign to pick one."
            else:
                zoom_repo.update_status(rec_id, "failed", error_message="Transcript download returned no data")
                msg = "Meeting found but transcript download failed."
        except Exception as exc:
            logger.error("Processing after fetch failed for recording %d: %s", rec_id, exc)
            zoom_repo.update_status(rec_id, "failed", error_message=str(exc)[:500])
            msg = f"Meeting fetched but processing failed: {html.escape(str(exc)[:200])}"

    return _render_meetings_page(request, zoom_repo, ts, dash, fetch_result={
        "ok": zoom_repo.get_by_id(rec_id).processing_status in ("complete", "matched") if rec_id else False,
        "message": msg,
    })


def _render_meetings_page(
    request: Request,
    zoom_repo: ZoomRepository,
    ts: TranscriptService,
    dash: DashboardService,
    *,
    fetch_result: dict | None = None,
) -> HTMLResponse:
    """Re-render the full meetings page (shared helper)."""
    zoom_connected = zoom_repo.get_config("zoom_refresh_token") is not None
    last_sync = zoom_repo.get_last_sync_time()

    transcripts = ts.list_all_transcripts()
    pending_statuses = ("new", "downloaded", "matching", "matched", "unmatched", "failed")
    all_zoom = zoom_repo.list_all()
    zoom_pending = [r for r in all_zoom if r.processing_status in pending_statuses]

    rows = _merge_meeting_rows(transcripts, zoom_pending, zoom_repo)

    pids: set[int] = set()
    for r in rows:
        if r["kind"] == "transcript" and r["transcript"].project_id:
            pids.add(r["transcript"].project_id)
        elif r["kind"] == "zoom":
            for m in r.get("mappings", []):
                pids.add(m.project_id)
    project_names = _build_project_names(dash, pids)
    all_projects = dash.list_projects()

    nav = get_nav_context(request)
    ctx = {
        **nav,
        "rows": rows,
        "last_sync": last_sync,
        "zoom_connected": zoom_connected,
        "project_names": project_names,
        "all_projects": all_projects,
        "filter_source": "all",
    }
    if fetch_result:
        ctx["fetch_result"] = fetch_result

    return templates.TemplateResponse(request, "meetings.html", ctx)


# ------------------------------------------------------------------
# POST /meetings/zoom/{rec_id}/reanalyse
# ------------------------------------------------------------------

@router.post("/meetings/zoom/{rec_id}/reanalyse", response_class=HTMLResponse)
async def reanalyse_recording(
    request: Request,
    rec_id: int,
    zoom_repo: ZoomRepository = Depends(get_zoom_repo),
    ingestion: ZoomIngestionService = Depends(get_zoom_ingestion_service),
    dash: DashboardService = Depends(get_dashboard_service),
    ts: TranscriptService = Depends(get_transcript_service),
    parser: TranscriptParser = Depends(get_transcript_parser),
) -> HTMLResponse:
    """Re-run LLM analysis on stored transcripts for a completed recording."""
    rec = zoom_repo.get_by_id(rec_id)
    if rec is None:
        return HTMLResponse("Recording not found", status_code=404)

    mappings = zoom_repo.get_mappings_for_recording(rec_id)
    if not mappings:
        return HTMLResponse("No project mappings found", status_code=400)

    try:
        parsed = None
        needs_download = any(not m.transcript_id for m in mappings)
        if needs_download:
            vtt_bytes = await ingestion.download_transcript(rec_id)
            if vtt_bytes:
                parsed = parser.parse(f"{rec.topic}.vtt", vtt_bytes)

        for m in mappings:
            project = dash.get_project_by_id(m.project_id)
            if not project:
                continue

            tid = m.transcript_id
            if not tid:
                if not parsed:
                    continue
                tid = ts.store_transcript(m.project_id, parsed, source="zoom")
                zoom_repo.update_mapping_transcript(rec_id, m.project_id, tid)

            await ts.analyze_transcript(tid, project, preserve_accepted=True)

        zoom_repo.update_status(rec_id, "complete")
    except Exception as exc:
        logger.error("Re-analyse failed for recording %d: %s", rec_id, exc)
        zoom_repo.update_status(rec_id, "failed", error_message=str(exc)[:500])
        for m in mappings:
            zoom_repo.update_mapping_status(rec_id, m.project_id, "failed")

    rec = zoom_repo.get_by_id(rec_id)
    mappings = zoom_repo.get_mappings_for_recording(rec_id)
    pids = {m.project_id for m in mappings}
    project_names = _build_project_names(dash, pids)
    all_projects = dash.list_projects()

    return templates.TemplateResponse(request, "partials/meeting_row.html", {
        "row": {"kind": "zoom", "recording": rec, "mappings": mappings, "date": rec.start_time},
        "project_names": project_names,
        "all_projects": all_projects,
    })


# ------------------------------------------------------------------
# POST /meetings/zoom/{rec_id}/dismiss
# ------------------------------------------------------------------

@router.post("/meetings/zoom/{rec_id}/dismiss", response_class=HTMLResponse)
async def dismiss_recording(
    request: Request,
    rec_id: int,
    zoom_repo: ZoomRepository = Depends(get_zoom_repo),
) -> HTMLResponse:
    """Dismiss a Zoom recording."""
    zoom_repo.dismiss_recording(rec_id)
    # Return empty string with swap to delete the row
    return HTMLResponse("")


# ------------------------------------------------------------------
# POST /meetings/zoom/{rec_id}/retry
# ------------------------------------------------------------------

@router.post("/meetings/zoom/{rec_id}/retry", response_class=HTMLResponse)
async def retry_recording(
    request: Request,
    rec_id: int,
    zoom_repo: ZoomRepository = Depends(get_zoom_repo),
    ingestion: ZoomIngestionService = Depends(get_zoom_ingestion_service),
    dash: DashboardService = Depends(get_dashboard_service),
    ts: TranscriptService = Depends(get_transcript_service),
    parser: TranscriptParser = Depends(get_transcript_parser),
    matcher: "ZoomMatchingService" = Depends(get_zoom_matching_service),
) -> HTMLResponse:
    """Re-run matching + analysis for a recording."""
    zoom_repo.update_status(rec_id, "new")

    rec = zoom_repo.get_by_id(rec_id)
    if rec:
        try:
            # If transcript URL is missing, try to refresh it from Zoom
            if not rec.transcript_url:
                new_url = await ingestion.refresh_transcript_url(rec_id)
                if not new_url:
                    zoom_repo.update_status(
                        rec_id, "failed",
                        error_message="Transcript still not available on Zoom",
                    )
                    rec = zoom_repo.get_by_id(rec_id)
                    mappings = zoom_repo.get_mappings_for_recording(rec_id) if rec else []
                    pids = {m.project_id for m in mappings}
                    project_names = _build_project_names(dash, pids)
                    all_projects = dash.list_projects()
                    return templates.TemplateResponse(request, "partials/meeting_row.html", {
                        "row": {"kind": "zoom", "recording": rec, "mappings": mappings, "date": rec.start_time if rec else ""},
                        "project_names": project_names,
                        "all_projects": all_projects,
                    })

            vtt_bytes = await ingestion.download_transcript(rec_id)
            if vtt_bytes:
                parsed = parser.parse(f"{rec.topic}.vtt", vtt_bytes)

                project_ids = await matcher.match_recording(rec, parsed.raw_text[:2000])

                if project_ids:
                    zoom_repo.update_status(rec_id, "matched", match_method=matcher.last_match_method)
                    for pid in project_ids:
                        project = dash.get_project_by_id(pid)
                        if project:
                            tid = ts.store_transcript(pid, parsed, source="zoom")
                            zoom_repo.add_project_mapping(rec_id, pid, tid)
                            await ts.analyze_transcript(tid, project)
                    zoom_repo.update_status(rec_id, "complete")
                else:
                    zoom_repo.update_status(rec_id, "unmatched")
        except Exception as exc:
            logger.error("Retry failed: %s", exc)
            zoom_repo.update_status(rec_id, "failed", error_message=str(exc)[:500])

    rec = zoom_repo.get_by_id(rec_id)
    mappings = zoom_repo.get_mappings_for_recording(rec_id) if rec else []
    pids = {m.project_id for m in mappings}
    project_names = _build_project_names(dash, pids)
    all_projects = dash.list_projects()

    return templates.TemplateResponse(request, "partials/meeting_row.html", {
        "row": {"kind": "zoom", "recording": rec, "mappings": mappings, "date": rec.start_time if rec else ""},
        "project_names": project_names,
        "all_projects": all_projects,
    })


# ------------------------------------------------------------------
# POST /meetings/zoom/{rec_id}/assign
# ------------------------------------------------------------------

@router.post("/meetings/zoom/{rec_id}/assign", response_class=HTMLResponse)
async def assign_recording(
    request: Request,
    rec_id: int,
    zoom_repo: ZoomRepository = Depends(get_zoom_repo),
    ingestion: ZoomIngestionService = Depends(get_zoom_ingestion_service),
    dash: DashboardService = Depends(get_dashboard_service),
    ts: TranscriptService = Depends(get_transcript_service),
    parser: TranscriptParser = Depends(get_transcript_parser),
) -> HTMLResponse:
    """Manually assign a Zoom recording to project(s), then trigger analysis."""
    form = await request.form()
    project_ids_raw = form.getlist("project_ids")
    project_ids = [int(p) for p in project_ids_raw if str(p).isdigit()]

    if not project_ids:
        return HTMLResponse("No projects selected", status_code=400)

    rec = zoom_repo.get_by_id(rec_id)
    if rec is None:
        return HTMLResponse("Recording not found", status_code=404)

    for pid in project_ids:
        zoom_repo.add_project_mapping(rec_id, pid)

    zoom_repo.update_status(rec_id, "matched", match_method="manual")

    if rec.processing_status in ("new", "unmatched"):
        try:
            vtt_bytes = await ingestion.download_transcript(rec_id)
            if not vtt_bytes:
                zoom_repo.update_status(rec_id, "failed", error_message="Transcript download returned no data")
            else:
                parsed = parser.parse(f"{rec.topic}.vtt", vtt_bytes)

                for pid in project_ids:
                    project = dash.get_project_by_id(pid)
                    if project:
                        tid = ts.store_transcript(pid, parsed, source="zoom")
                        zoom_repo.update_mapping_transcript(rec_id, pid, tid)
                        await ts.analyze_transcript(tid, project)

                zoom_repo.update_status(rec_id, "complete")
        except Exception as exc:
            logger.error("Assign analysis failed: %s", exc)
            zoom_repo.update_status(rec_id, "failed", error_message=str(exc)[:500])

    response = HTMLResponse("")
    response.headers["HX-Redirect"] = "/meetings/"
    return response


# ------------------------------------------------------------------
# POST /meetings/zoom/{rec_id}/reassign
# ------------------------------------------------------------------

@router.post("/meetings/zoom/{rec_id}/reassign", response_class=HTMLResponse)
async def reassign_recording(
    request: Request,
    rec_id: int,
    zoom_repo: ZoomRepository = Depends(get_zoom_repo),
    ingestion: ZoomIngestionService = Depends(get_zoom_ingestion_service),
    dash: DashboardService = Depends(get_dashboard_service),
    ts: TranscriptService = Depends(get_transcript_service),
    parser: TranscriptParser = Depends(get_transcript_parser),
) -> HTMLResponse:
    """Reassign a Zoom recording to a different project."""
    form = await request.form()
    new_pid_raw = form.get("project_id", "")
    if not str(new_pid_raw).isdigit():
        return error_banner("Please select a project.", status_code=400)
    new_pid = int(new_pid_raw)

    rec = zoom_repo.get_by_id(rec_id)
    if rec is None:
        return HTMLResponse("Recording not found", status_code=404)

    # Remove old mappings and their transcripts/suggestions
    old_mappings = zoom_repo.get_mappings_for_recording(rec_id)
    for m in old_mappings:
        if m.transcript_id:
            ts.delete_transcript(m.transcript_id)
        zoom_repo.remove_project_mapping(rec_id, m.project_id)

    # Add new mapping
    zoom_repo.add_project_mapping(rec_id, new_pid)
    zoom_repo.update_status(rec_id, "matched", match_method="manual")

    # Download transcript and run analysis for new project
    try:
        vtt_bytes = await ingestion.download_transcript(rec_id)
        if not vtt_bytes:
            zoom_repo.update_status(rec_id, "failed", error_message="Transcript download returned no data")
        else:
            parsed = parser.parse(f"{rec.topic}.vtt", vtt_bytes)
            project = dash.get_project_by_id(new_pid)
            if project:
                tid = ts.store_transcript(new_pid, parsed, source="zoom")
                zoom_repo.update_mapping_transcript(rec_id, new_pid, tid)
                await ts.analyze_transcript(tid, project)
            zoom_repo.update_status(rec_id, "complete")
    except Exception as exc:
        logger.error("Reassign analysis failed: %s", exc)
        zoom_repo.update_status(rec_id, "failed", error_message=str(exc)[:500])

    rsp = HTMLResponse("")
    rsp.headers["HX-Redirect"] = "/meetings/"
    return rsp
