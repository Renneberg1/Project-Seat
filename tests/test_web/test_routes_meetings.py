"""Tests for unified Meetings page routes."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from src.database import get_db
from src.models.project import Project
from src.models.transcript import ParsedTranscript, TranscriptRecord, TranscriptSegment


def _insert_project(db_path, name="Test Project", goal_key="PROG-100"):
    with get_db(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO projects (jira_goal_key, name, status, phase) VALUES (?, ?, ?, ?)",
            (goal_key, name, "active", "planning"),
        )
        conn.commit()
        return cursor.lastrowid


def _make_project(pid=1, name="Test Project", goal_key="PROG-100"):
    return Project(
        id=pid, jira_goal_key=goal_key, name=name,
        confluence_charter_id=None, confluence_xft_id=None,
        status="active", phase="planning", created_at="2026-01-01",
        dhf_draft_root_id=None, dhf_released_root_id=None,
    )


def _make_parsed(filename="test.txt"):
    return ParsedTranscript(
        filename=filename,
        segments=[
            TranscriptSegment(speaker="Alice", text="We need to discuss risks."),
            TranscriptSegment(speaker="Bob", text="Agreed."),
        ],
        raw_text="Alice: We need to discuss risks.\nBob: Agreed.",
        speaker_list=["Alice", "Bob"],
    )


def _make_transcript_record(tid=1, project_id=None, source="manual"):
    return TranscriptRecord(
        id=tid, project_id=project_id, filename="test.vtt",
        raw_text="Alice: Hello", processed_json=None,
        meeting_summary=None, source=source, created_at="2026-01-01",
    )


# ---------------------------------------------------------------------------
# GET /meetings/ — page loads
# ---------------------------------------------------------------------------


def test_meetings_page_returns_200(client, tmp_db):
    with patch("src.web.deps.TranscriptService") as MockTS, \
         patch("src.web.deps.ZoomRepository") as MockZR, \
         patch("src.web.deps.DashboardService") as MockDS:
        MockTS.return_value.list_all_transcripts.return_value = []
        MockZR.return_value.get_config.return_value = None
        MockZR.return_value.get_last_sync_time.return_value = None
        MockZR.return_value.list_all.return_value = []
        MockDS.return_value.list_projects.return_value = []
        result = client.get("/meetings/")
    assert result.status_code == 200
    assert "Meetings" in result.text
    assert "Add Transcript" in result.text


def test_meetings_page_shows_connect_zoom_when_not_connected(client, tmp_db):
    with patch("src.web.deps.TranscriptService") as MockTS, \
         patch("src.web.deps.ZoomRepository") as MockZR, \
         patch("src.web.deps.DashboardService") as MockDS:
        MockTS.return_value.list_all_transcripts.return_value = []
        MockZR.return_value.get_config.return_value = None
        MockZR.return_value.get_last_sync_time.return_value = None
        MockZR.return_value.list_all.return_value = []
        MockDS.return_value.list_projects.return_value = []
        result = client.get("/meetings/")
    assert result.status_code == 200
    assert "Connect Zoom" in result.text


def test_meetings_page_shows_sync_when_connected(client, tmp_db):
    with patch("src.web.deps.TranscriptService") as MockTS, \
         patch("src.web.deps.ZoomRepository") as MockZR, \
         patch("src.web.deps.DashboardService") as MockDS:
        MockTS.return_value.list_all_transcripts.return_value = []
        MockZR.return_value.get_config.return_value = "some-token"
        MockZR.return_value.get_last_sync_time.return_value = "2026-01-01"
        MockZR.return_value.list_all.return_value = []
        MockDS.return_value.list_projects.return_value = []
        result = client.get("/meetings/")
    assert result.status_code == 200
    assert "Sync Zoom" in result.text
    assert "Connect Zoom" not in result.text


def test_meetings_page_with_transcripts(client, tmp_db):
    pid = _insert_project(tmp_db)
    project = _make_project(pid)
    record = _make_transcript_record(1, pid, "manual")

    with patch("src.web.deps.TranscriptService") as MockTS, \
         patch("src.web.deps.ZoomRepository") as MockZR, \
         patch("src.web.deps.DashboardService") as MockDS:
        MockTS.return_value.list_all_transcripts.return_value = [record]
        MockZR.return_value.get_config.return_value = None
        MockZR.return_value.get_last_sync_time.return_value = None
        MockZR.return_value.list_all.return_value = []
        MockDS.return_value.list_projects.return_value = [project]
        MockDS.return_value.get_project_by_id.return_value = project
        result = client.get("/meetings/")
    assert result.status_code == 200
    assert "test.vtt" in result.text


def test_meetings_page_filters_by_source(client, tmp_db):
    with patch("src.web.deps.TranscriptService") as MockTS, \
         patch("src.web.deps.ZoomRepository") as MockZR, \
         patch("src.web.deps.DashboardService") as MockDS:
        MockTS.return_value.list_all_transcripts.return_value = []
        MockZR.return_value.get_config.return_value = None
        MockZR.return_value.get_last_sync_time.return_value = None
        MockZR.return_value.list_all.return_value = []
        MockDS.return_value.list_projects.return_value = []
        result = client.get("/meetings/?source=manual")
    assert result.status_code == 200
    # Verify the manual filter tab is active
    MockTS.return_value.list_all_transcripts.assert_called_once_with(
        source="manual", project_id=None, unassigned=False,
    )


# ---------------------------------------------------------------------------
# POST /meetings/upload — file upload
# ---------------------------------------------------------------------------


def test_upload_returns_parsed_preview(client, tmp_db):
    pid = _insert_project(tmp_db)
    project = _make_project(pid)
    parsed = _make_parsed("test.txt")

    with patch("src.web.deps.TranscriptParser") as MockParser, \
         patch("src.web.deps.TranscriptService") as MockTS, \
         patch("src.web.deps.DashboardService") as MockDS:
        MockParser.return_value.parse.return_value = parsed
        MockTS.return_value.store_transcript.return_value = 1
        MockDS.return_value.list_projects.return_value = [project]
        result = client.post(
            "/meetings/upload",
            files={"file": ("test.txt", b"Alice: Risks.\nBob: Agreed.", "text/plain")},
        )
    assert result.status_code == 200
    assert "Alice" in result.text
    assert "Assign &" in result.text and "Analyze" in result.text


def test_upload_stores_unassigned(client, tmp_db):
    parsed = _make_parsed("test.txt")

    with patch("src.web.deps.TranscriptParser") as MockParser, \
         patch("src.web.deps.TranscriptService") as MockTS, \
         patch("src.web.deps.DashboardService") as MockDS:
        MockParser.return_value.parse.return_value = parsed
        MockTS.return_value.store_transcript.return_value = 1
        MockDS.return_value.list_projects.return_value = []
        client.post(
            "/meetings/upload",
            files={"file": ("test.txt", b"Alice: Risks.", "text/plain")},
        )
        MockTS.return_value.store_transcript.assert_called_once_with(None, parsed)


# ---------------------------------------------------------------------------
# POST /meetings/paste — text paste
# ---------------------------------------------------------------------------


def test_paste_returns_parsed_preview(client, tmp_db):
    parsed = _make_parsed("pasted-input.txt")

    with patch("src.web.deps.TranscriptParser") as MockParser, \
         patch("src.web.deps.TranscriptService") as MockTS, \
         patch("src.web.deps.DashboardService") as MockDS:
        MockParser.return_value.parse.return_value = parsed
        MockTS.return_value.store_transcript.return_value = 1
        MockDS.return_value.list_projects.return_value = []
        result = client.post(
            "/meetings/paste",
            data={"transcript_text": "Alice: Discussion.\nBob: Yes."},
        )
    assert result.status_code == 200
    assert "Alice" in result.text


def test_paste_empty_text_returns_400(client, tmp_db):
    result = client.post(
        "/meetings/paste",
        data={"transcript_text": "   "},
    )
    assert result.status_code == 400
    assert "enter some text" in result.text


# ---------------------------------------------------------------------------
# POST /meetings/{tid}/assign-and-analyze
# ---------------------------------------------------------------------------


def test_assign_and_analyze_no_project_returns_400(client, tmp_db):
    with patch("src.web.deps.TranscriptService") as MockTS, \
         patch("src.web.deps.DashboardService") as MockDS:
        result = client.post(
            "/meetings/1/assign-and-analyze",
            data={},
        )
    assert result.status_code == 400
    assert "at least one project" in result.text


def test_assign_and_analyze_transcript_not_found(client, tmp_db):
    with patch("src.web.deps.TranscriptService") as MockTS, \
         patch("src.web.deps.DashboardService") as MockDS:
        MockTS.return_value.get_transcript.return_value = None
        result = client.post(
            "/meetings/999/assign-and-analyze",
            data={"project_ids": "1"},
        )
    assert result.status_code == 404


def test_assign_and_analyze_success(client, tmp_db):
    pid = _insert_project(tmp_db)
    project = _make_project(pid)
    record = _make_transcript_record(1, None)

    with patch("src.web.deps.TranscriptService") as MockTS, \
         patch("src.web.deps.DashboardService") as MockDS:
        MockTS.return_value.get_transcript.return_value = record
        MockTS.return_value.assign_transcript.return_value = None
        MockTS.return_value.analyze_transcript = AsyncMock(return_value=[])
        MockDS.return_value.get_project_by_id.return_value = project
        result = client.post(
            "/meetings/1/assign-and-analyze",
            data={"project_ids": str(pid)},
        )
    assert result.status_code == 200
    assert result.headers.get("hx-redirect") == "/meetings/"


# ---------------------------------------------------------------------------
# POST /meetings/{tid}/delete
# ---------------------------------------------------------------------------


def test_delete_transcript(client, tmp_db):
    with patch("src.web.deps.TranscriptService") as MockTS:
        MockTS.return_value.delete_transcript.return_value = None
        result = client.post("/meetings/1/delete")
    assert result.status_code == 200
    assert result.headers.get("hx-redirect") == "/meetings/"


# ---------------------------------------------------------------------------
# POST /meetings/zoom/{rec_id}/dismiss
# ---------------------------------------------------------------------------


def test_dismiss_recording(client, tmp_db):
    with patch("src.web.deps.ZoomRepository") as MockZR:
        MockZR.return_value.dismiss_recording.return_value = None
        result = client.post("/meetings/zoom/1/dismiss")
    assert result.status_code == 200


# ---------------------------------------------------------------------------
# Backward compat redirects
# ---------------------------------------------------------------------------


def test_zoom_inbox_redirects_to_meetings(client, tmp_db):
    result = client.get("/zoom/inbox", follow_redirects=False)
    assert result.status_code == 302
    assert "/meetings/" in result.headers["location"]


def test_zoom_triage_redirects_to_meetings(client, tmp_db):
    result = client.get("/zoom/triage", follow_redirects=False)
    assert result.status_code == 302
    assert "/meetings/" in result.headers["location"]
