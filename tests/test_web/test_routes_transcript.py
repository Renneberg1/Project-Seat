"""Tests for transcript routes — upload, paste, and analysis."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.database import get_db
from src.models.project import Project
from src.models.transcript import ParsedTranscript, TranscriptSegment


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


# ---------------------------------------------------------------------------
# GET /project/{id}/transcript/ — page loads
# ---------------------------------------------------------------------------


def test_transcript_page_returns_200(client, tmp_db):
    pid = _insert_project(tmp_db)
    project = _make_project(pid)
    with patch("src.web.deps.DashboardService") as MockDS, \
         patch("src.web.deps.TranscriptService") as MockTS:
        MockDS.return_value.get_project_by_id.return_value = project
        MockTS.return_value.list_transcripts.return_value = []
        result = client.get(f"/project/{pid}/transcript/")
    assert result.status_code == 200
    assert "Upload File" in result.text
    assert "Paste Text" in result.text


def test_transcript_page_404_for_missing_project(client):
    with patch("src.web.deps.DashboardService") as MockDS:
        MockDS.return_value.get_project_by_id.return_value = None
        result = client.get("/project/999/transcript/")
    assert result.status_code == 404


# ---------------------------------------------------------------------------
# POST /project/{id}/transcript/upload — file upload
# ---------------------------------------------------------------------------


def test_upload_file_returns_parsed_preview(client, tmp_db):
    pid = _insert_project(tmp_db)
    project = _make_project(pid)
    parsed = _make_parsed("test.txt")

    with patch("src.web.deps.DashboardService") as MockDS, \
         patch("src.web.deps.TranscriptParser") as MockParser, \
         patch("src.web.deps.TranscriptService") as MockTS:
        MockDS.return_value.get_project_by_id.return_value = project
        MockParser.return_value.parse.return_value = parsed
        MockTS.return_value.store_transcript.return_value = 1
        result = client.post(
            f"/project/{pid}/transcript/upload",
            files={"file": ("test.txt", b"Alice: We need to discuss risks.\nBob: Agreed.", "text/plain")},
        )
    assert result.status_code == 200
    assert "Alice" in result.text
    assert "Analyze with LLM" in result.text


# ---------------------------------------------------------------------------
# POST /project/{id}/transcript/paste — direct text input
# ---------------------------------------------------------------------------


def test_paste_text_returns_parsed_preview(client, tmp_db):
    pid = _insert_project(tmp_db)
    project = _make_project(pid)
    parsed = _make_parsed("pasted-input.txt")

    with patch("src.web.deps.DashboardService") as MockDS, \
         patch("src.web.deps.TranscriptParser") as MockParser, \
         patch("src.web.deps.TranscriptService") as MockTS:
        MockDS.return_value.get_project_by_id.return_value = project
        MockParser.return_value.parse.return_value = parsed
        MockTS.return_value.store_transcript.return_value = 1
        result = client.post(
            f"/project/{pid}/transcript/paste",
            data={"transcript_text": "Alice: We should track this risk.\nBob: I agree."},
        )
    assert result.status_code == 200
    assert "Alice" in result.text
    assert "Analyze with LLM" in result.text


def test_paste_empty_text_returns_400(client, tmp_db):
    pid = _insert_project(tmp_db)
    project = _make_project(pid)
    with patch("src.web.deps.DashboardService") as MockDS:
        MockDS.return_value.get_project_by_id.return_value = project
        result = client.post(
            f"/project/{pid}/transcript/paste",
            data={"transcript_text": "   "},
        )
    assert result.status_code == 400
    assert "enter some text" in result.text


def test_paste_calls_parser_with_txt_extension(client, tmp_db):
    """Paste route passes content to parser as a .txt file so _parse_txt is used."""
    pid = _insert_project(tmp_db)
    project = _make_project(pid)
    parsed = _make_parsed("pasted-input.txt")
    text = "Some meeting notes."

    with patch("src.web.deps.DashboardService") as MockDS, \
         patch("src.web.deps.TranscriptParser") as MockParser, \
         patch("src.web.deps.TranscriptService") as MockTS:
        MockDS.return_value.get_project_by_id.return_value = project
        MockParser.return_value.parse.return_value = parsed
        MockTS.return_value.store_transcript.return_value = 1
        client.post(
            f"/project/{pid}/transcript/paste",
            data={"transcript_text": text},
        )
        MockParser.return_value.parse.assert_called_once_with(
            "pasted-input.txt", text.encode("utf-8")
        )


def test_paste_404_for_missing_project(client):
    with patch("src.web.deps.DashboardService") as MockDS:
        MockDS.return_value.get_project_by_id.return_value = None
        result = client.post(
            "/project/999/transcript/paste",
            data={"transcript_text": "some text"},
        )
    assert result.status_code == 404


# ---------------------------------------------------------------------------
# Risk refinement routes
# ---------------------------------------------------------------------------

import json
from unittest.mock import AsyncMock
from src.models.transcript import SuggestionStatus, SuggestionType, TranscriptSuggestion


def _make_suggestion(sid=1):
    return TranscriptSuggestion(
        id=sid, transcript_id=1, project_id=1,
        suggestion_type=SuggestionType.RISK,
        title="Test Risk", detail="Some detail",
        evidence="Speaker said X",
        proposed_payload=json.dumps({"summary": "Test Risk", "fields": {}}),
        proposed_action="create_jira_issue",
        proposed_preview="Type: risk\nTitle: Test Risk",
        confidence=0.8, status=SuggestionStatus.PENDING,
        approval_item_id=None, created_at="2026-01-01",
    )


def test_start_refinement_returns_panel(client, tmp_db):
    pid = _insert_project(tmp_db)
    project = _make_project(pid)
    sug = _make_suggestion()

    refine_result = {
        "satisfied": False,
        "quality_assessment": "Title needs work.",
        "questions": [
            {"question": "What metrics?", "field": "background", "why_needed": "Details needed"},
        ],
        "refined_risk": {
            "title": "Risk Title", "background": "bg", "impact_analysis": "impact",
            "mitigation": "mit", "priority": "High", "timeline_impact_days": 5,
            "evidence": "quote",
        },
    }

    with patch("src.web.deps.DashboardService") as MockDS, \
         patch("src.web.deps.RiskRefinementService") as MockRS:
        MockDS.return_value.get_project_by_id.return_value = project
        mock_service = MockRS.return_value
        mock_service.start_risk_refinement = AsyncMock(return_value=refine_result)
        mock_service.get_suggestion.return_value = sug
        result = client.post(f"/project/{pid}/transcript/1/suggestions/1/refine")

    assert result.status_code == 200
    assert "Title needs work" in result.text
    assert "What metrics?" in result.text
    assert "Submit Answers" in result.text


def test_start_refinement_404_missing_project(client):
    with patch("src.web.deps.DashboardService") as MockDS:
        MockDS.return_value.get_project_by_id.return_value = None
        result = client.post("/project/999/transcript/1/suggestions/1/refine")
    assert result.status_code == 404


def test_refine_answer_returns_updated_panel(client, tmp_db):
    pid = _insert_project(tmp_db)
    project = _make_project(pid)
    sug = _make_suggestion()

    satisfied_result = {
        "satisfied": True,
        "quality_assessment": "All criteria met.",
        "questions": [],
        "refined_risk": {
            "title": "Refined Risk", "background": "detailed bg",
            "impact_analysis": "detailed impact", "mitigation": "concrete steps",
            "priority": "High", "timeline_impact_days": 5, "evidence": "full quote",
        },
    }

    with patch("src.web.deps.DashboardService") as MockDS, \
         patch("src.web.deps.RiskRefinementService") as MockRS:
        MockDS.return_value.get_project_by_id.return_value = project
        mock_service = MockRS.return_value
        mock_service.continue_risk_refinement = AsyncMock(return_value=satisfied_result)
        mock_service.get_suggestion.return_value = sug
        result = client.post(
            f"/project/{pid}/transcript/1/suggestions/1/refine/answer",
            data={
                "risk_draft": json.dumps({"title": "Draft"}),
                "qa_history": json.dumps([]),
                "round_number": "1",
                "question_0": "What metrics?",
                "answer_0": "Accuracy dropped 5%",
            },
        )

    assert result.status_code == 200
    assert "All criteria met" in result.text
    assert "Apply Refinement" in result.text


def test_apply_refinement_returns_suggestion_row(client, tmp_db):
    pid = _insert_project(tmp_db)
    project = _make_project(pid)
    sug = _make_suggestion()

    with patch("src.web.deps.DashboardService") as MockDS, \
         patch("src.web.deps.RiskRefinementService") as MockRS:
        MockDS.return_value.get_project_by_id.return_value = project
        mock_service = MockRS.return_value
        mock_service.apply_refinement.return_value = sug
        result = client.post(
            f"/project/{pid}/transcript/1/suggestions/1/refine/apply",
            data={
                "refined_risk": json.dumps({
                    "title": "Final Risk",
                    "background": "bg",
                    "impact_analysis": "impact",
                    "mitigation": "mit",
                    "priority": "High",
                    "timeline_impact_days": 5,
                    "evidence": "quote",
                }),
            },
        )

    assert result.status_code == 200
    assert "Test Risk" in result.text  # suggestion title from _make_suggestion


def test_apply_refinement_404_when_suggestion_missing(client, tmp_db):
    pid = _insert_project(tmp_db)
    project = _make_project(pid)

    with patch("src.web.deps.DashboardService") as MockDS, \
         patch("src.web.deps.RiskRefinementService") as MockRS:
        MockDS.return_value.get_project_by_id.return_value = project
        MockRS.return_value.apply_refinement.return_value = None
        result = client.post(
            f"/project/{pid}/transcript/1/suggestions/999/refine/apply",
            data={"refined_risk": json.dumps({"title": "X"})},
        )

    assert result.status_code == 404
