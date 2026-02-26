"""Tests for transcript parsing and service."""

from __future__ import annotations

import pytest

from src.database import init_db
from src.models.transcript import SuggestionStatus, SuggestionType
from src.services._transcript_helpers import extract_adf_text
from src.services.risk_refinement import RiskRefinementService
from src.services.transcript import TranscriptService
from src.services.transcript_parser import TranscriptParser


# ---------------------------------------------------------------------------
# Sample transcript content
# ---------------------------------------------------------------------------

SAMPLE_VTT = b"""\
WEBVTT

1
00:00:01.000 --> 00:00:05.000
<v Thomas>We need to discuss the risk around the new model performance.</v>

2
00:00:06.000 --> 00:00:12.000
<v Sarah>I agree. The high-res training showed a drop in accuracy metrics.</v>

3
00:00:13.000 --> 00:00:20.000
<v Thomas>Let's create a risk for that and plan an MRMC evaluation.</v>

4
00:00:21.000 --> 00:00:28.000
<v Sarah>We also decided to postpone the UI redesign to Drop 3.</v>
"""

SAMPLE_TXT = b"""\
Thomas: We need to discuss the risk around the new model performance.
Sarah: I agree. The high-res training showed a drop in accuracy metrics.
Thomas: Let's create a risk for that and plan an MRMC evaluation.
Sarah: We also decided to postpone the UI redesign to Drop 3.
"""


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------


class TestTranscriptParser:

    def test_parse_vtt_extracts_speakers(self):
        parser = TranscriptParser()
        result = parser.parse("meeting.vtt", SAMPLE_VTT)

        assert result.filename == "meeting.vtt"
        assert len(result.segments) == 4
        assert "Thomas" in result.speaker_list
        assert "Sarah" in result.speaker_list
        assert result.duration_hint == "00:00:28.000"

    def test_parse_vtt_speaker_text(self):
        parser = TranscriptParser()
        result = parser.parse("meeting.vtt", SAMPLE_VTT)

        first = result.segments[0]
        assert first.speaker == "Thomas"
        assert "risk" in first.text.lower()
        assert first.timestamp_start == "00:00:01.000"

    def test_parse_txt_extracts_speakers(self):
        parser = TranscriptParser()
        result = parser.parse("meeting.txt", SAMPLE_TXT)

        assert result.filename == "meeting.txt"
        assert len(result.segments) == 4
        assert "Thomas" in result.speaker_list
        assert "Sarah" in result.speaker_list

    def test_parse_txt_speaker_text(self):
        parser = TranscriptParser()
        result = parser.parse("meeting.txt", SAMPLE_TXT)

        first = result.segments[0]
        assert first.speaker == "Thomas"
        assert "risk" in first.text.lower()

    def test_parse_unsupported_format_raises(self):
        parser = TranscriptParser()
        with pytest.raises(ValueError, match="Unsupported"):
            parser.parse("meeting.mp4", b"data")

    def test_parse_vtt_raw_text_format(self):
        parser = TranscriptParser()
        result = parser.parse("meeting.vtt", SAMPLE_VTT)

        # raw_text should be speaker: text format
        assert "Thomas:" in result.raw_text
        assert "Sarah:" in result.raw_text

    def test_parse_empty_vtt(self):
        parser = TranscriptParser()
        result = parser.parse("empty.vtt", b"WEBVTT\n\n")

        assert result.segments == []
        assert result.speaker_list == []


# ---------------------------------------------------------------------------
# Service storage tests (require temp DB)
# ---------------------------------------------------------------------------


class TestTranscriptService:

    @pytest.fixture()
    def db_path(self, tmp_path):
        path = str(tmp_path / "test.db")
        init_db(path)
        # Insert a test project
        import sqlite3
        conn = sqlite3.connect(path)
        conn.execute(
            "INSERT INTO projects (jira_goal_key, name, status, phase) VALUES (?, ?, ?, ?)",
            ("PROG-100", "Test Project", "active", "planning"),
        )
        conn.commit()
        conn.close()
        return path

    def test_store_and_list_transcripts(self, db_path):
        parser = TranscriptParser()
        parsed = parser.parse("meeting.vtt", SAMPLE_VTT)

        service = TranscriptService(db_path=db_path)
        tid = service.store_transcript(1, parsed)

        assert tid > 0

        records = service.list_transcripts(1)
        assert len(records) == 1
        assert records[0].filename == "meeting.vtt"
        assert "Thomas:" in records[0].raw_text

    def test_get_transcript(self, db_path):
        parser = TranscriptParser()
        parsed = parser.parse("meeting.txt", SAMPLE_TXT)

        service = TranscriptService(db_path=db_path)
        tid = service.store_transcript(1, parsed)

        record = service.get_transcript(tid)
        assert record is not None
        assert record.id == tid
        assert record.filename == "meeting.txt"

    def test_delete_transcript(self, db_path):
        parser = TranscriptParser()
        parsed = parser.parse("meeting.vtt", SAMPLE_VTT)

        service = TranscriptService(db_path=db_path)
        tid = service.store_transcript(1, parsed)
        service.delete_transcript(tid)

        assert service.get_transcript(tid) is None

    def test_get_transcript_summary(self, db_path):
        service = TranscriptService(db_path=db_path)
        summary = service.get_transcript_summary(1)

        assert summary["transcript_count"] == 0
        assert summary["suggestion_count"] == 0
        assert summary["pending_count"] == 0

    def test_store_multiple_transcripts(self, db_path):
        parser = TranscriptParser()
        service = TranscriptService(db_path=db_path)

        service.store_transcript(1, parser.parse("m1.vtt", SAMPLE_VTT))
        service.store_transcript(1, parser.parse("m2.txt", SAMPLE_TXT))

        records = service.list_transcripts(1)
        assert len(records) == 2


# ---------------------------------------------------------------------------
# Accept / reject suggestion tests (require temp DB with seeded data)
# ---------------------------------------------------------------------------


class TestSuggestionWorkflow:
    """Test accept, reject, and accept-all flows at the service level."""

    @pytest.fixture()
    def db_path(self, tmp_path):
        path = str(tmp_path / "test.db")
        init_db(path)
        import sqlite3
        conn = sqlite3.connect(path)
        conn.execute(
            "INSERT INTO projects (id, jira_goal_key, name, status, phase, "
            "confluence_charter_id, confluence_xft_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (1, "PROG-100", "Test Project", "active", "planning", "111", "222"),
        )
        conn.execute(
            "INSERT INTO transcript_cache (id, project_id, filename, raw_text) "
            "VALUES (?, ?, ?, ?)",
            (1, 1, "meeting.vtt", "Thomas: Risk discussion"),
        )
        conn.commit()
        conn.close()
        return path

    def _insert_suggestion(self, db_path, **overrides):
        import json, sqlite3
        defaults = dict(
            transcript_id=1,
            project_id=1,
            suggestion_type="risk",
            title="Test Risk",
            detail="Some detail",
            evidence="Speaker said X",
            proposed_payload=json.dumps({
                "project_key": "RISK",
                "issue_type_id": "10832",
                "summary": "Test Risk",
                "fields": {"parent": {"key": "PROG-100"}},
            }),
            proposed_action="create_jira_issue",
            proposed_preview="Type: risk\nTitle: Test Risk",
            confidence=0.8,
            status="pending",
        )
        defaults.update(overrides)
        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            """INSERT INTO transcript_suggestions
               (transcript_id, project_id, suggestion_type, title, detail,
                evidence, proposed_payload, proposed_action, proposed_preview,
                confidence, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                defaults["transcript_id"], defaults["project_id"],
                defaults["suggestion_type"], defaults["title"], defaults["detail"],
                defaults["evidence"], defaults["proposed_payload"],
                defaults["proposed_action"], defaults["proposed_preview"],
                defaults["confidence"], defaults["status"],
            ),
        )
        conn.commit()
        sug_id = cursor.lastrowid
        conn.close()
        return sug_id

    def _make_project(self):
        from src.models.project import Project
        return Project(
            id=1, jira_goal_key="PROG-100", name="Test Project",
            confluence_charter_id="111", confluence_xft_id="222",
            status="active", phase="planning", created_at="2026-01-01",
        )

    async def test_accept_suggestion_queues_approval_item(self, db_path):
        from unittest.mock import AsyncMock, patch
        sug_id = self._insert_suggestion(db_path)
        service = TranscriptService(db_path=db_path)
        project = self._make_project()

        with patch("src.services.transcript.resolve_adf_doc_mentions", new_callable=AsyncMock) as mock_adf, \
             patch("src.services.transcript.resolve_confluence_mentions", new_callable=AsyncMock) as mock_conf, \
             patch("src.services.transcript.JiraConnector") as MockJira:
            mock_adf.side_effect = lambda doc, jira: doc
            mock_conf.side_effect = lambda text, jira: text
            MockJira.return_value.close = AsyncMock()
            result = await service.accept_suggestion(sug_id, project)

        assert result is not None
        assert result.status == SuggestionStatus.QUEUED
        assert result.approval_item_id is not None
        # Verify the approval item exists
        from src.engine.approval import ApprovalEngine
        engine = ApprovalEngine(db_path=db_path)
        item = engine.get(result.approval_item_id)
        assert item is not None

    async def test_accept_suggestion_pending_goal_key_raises(self, db_path):
        sug_id = self._insert_suggestion(db_path)
        service = TranscriptService(db_path=db_path)
        project = self._make_project()
        project.jira_goal_key = "pending"

        with pytest.raises(ValueError, match="Goal key"):
            await service.accept_suggestion(sug_id, project)

    def test_reject_suggestion_updates_status(self, db_path):
        sug_id = self._insert_suggestion(db_path)
        service = TranscriptService(db_path=db_path)

        result = service.reject_suggestion(sug_id)

        assert result is not None
        assert result.status == SuggestionStatus.REJECTED

    async def test_accept_all_suggestions_queues_all(self, db_path):
        from unittest.mock import AsyncMock, patch
        self._insert_suggestion(db_path, title="Risk A")
        self._insert_suggestion(db_path, title="Risk B")
        service = TranscriptService(db_path=db_path)
        project = self._make_project()

        with patch("src.services.transcript.resolve_adf_doc_mentions", new_callable=AsyncMock) as mock_adf, \
             patch("src.services.transcript.resolve_confluence_mentions", new_callable=AsyncMock) as mock_conf, \
             patch("src.services.transcript.JiraConnector") as MockJira:
            mock_adf.side_effect = lambda doc, jira: doc
            mock_conf.side_effect = lambda text, jira: text
            MockJira.return_value.close = AsyncMock()
            item_ids = await service.accept_all_suggestions(1, project)

        assert len(item_ids) == 2
        # All suggestions should be queued
        suggestions = service.list_suggestions(1)
        assert all(s.status == SuggestionStatus.QUEUED for s in suggestions)

    def test_reject_already_rejected_is_idempotent(self, db_path):
        sug_id = self._insert_suggestion(db_path)
        service = TranscriptService(db_path=db_path)

        service.reject_suggestion(sug_id)
        result = service.reject_suggestion(sug_id)

        assert result.status == SuggestionStatus.REJECTED


# ---------------------------------------------------------------------------
# Risk refinement tests
# ---------------------------------------------------------------------------


class TestRiskRefinement:
    """Test extract_risk_draft, apply_refinement, and service-level refinement helpers."""

    @pytest.fixture()
    def db_path(self, tmp_path):
        path = str(tmp_path / "test.db")
        init_db(path)
        import sqlite3
        conn = sqlite3.connect(path)
        conn.execute(
            "INSERT INTO projects (id, jira_goal_key, name, status, phase, "
            "confluence_charter_id, confluence_xft_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (1, "PROG-100", "Test Project", "active", "planning", "111", "222"),
        )
        conn.execute(
            "INSERT INTO transcript_cache (id, project_id, filename, raw_text) "
            "VALUES (?, ?, ?, ?)",
            (1, 1, "meeting.vtt", "Thomas: Risk discussion"),
        )
        conn.commit()
        conn.close()
        return path

    def _insert_risk_suggestion(self, db_path):
        import json as _json, sqlite3
        payload = {
            "project_key": "RISK",
            "issue_type_id": "10832",
            "summary": "Model accuracy regression",
            "fields": {
                "parent": {"key": "PROG-100"},
                "description": {
                    "type": "doc", "version": 1,
                    "content": [
                        {"type": "paragraph", "content": [
                            {"type": "text", "text": "Background", "marks": [{"type": "strong"}]},
                        ]},
                        {"type": "paragraph", "content": [
                            {"type": "text", "text": "High-res training showed accuracy drop"},
                        ]},
                        {"type": "rule"},
                        {"type": "paragraph", "content": [
                            {"type": "text", "text": "Evidence from transcript", "marks": [{"type": "strong"}]},
                        ]},
                        {"type": "paragraph", "content": [
                            {"type": "text", "text": "Sarah said accuracy dropped"},
                        ]},
                    ],
                },
                "priority": {"name": "High"},
                "customfield_11166": {
                    "type": "doc", "version": 1,
                    "content": [
                        {"type": "paragraph", "content": [
                            {"type": "text", "text": "Could delay timeline by 5 days"},
                        ]},
                    ],
                },
                "customfield_11342": {
                    "type": "doc", "version": 1,
                    "content": [
                        {"type": "paragraph", "content": [
                            {"type": "text", "text": "Run MRMC evaluation"},
                        ]},
                    ],
                },
                "customfield_13267": 5,
            },
        }
        conn = sqlite3.connect(db_path)
        cursor = conn.execute(
            """INSERT INTO transcript_suggestions
               (transcript_id, project_id, suggestion_type, title, detail,
                evidence, proposed_payload, proposed_action, proposed_preview,
                confidence, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (1, 1, "risk", "Model accuracy regression",
             "High-res training showed accuracy drop",
             "Sarah said accuracy dropped",
             _json.dumps(payload), "create_jira_issue",
             "Type: risk\nTitle: Model accuracy regression",
             0.8, "pending"),
        )
        conn.commit()
        sug_id = cursor.lastrowid
        conn.close()
        return sug_id

    def test_extract_adf_text(self, db_path):
        adf = {
            "type": "doc", "version": 1,
            "content": [
                {"type": "paragraph", "content": [
                    {"type": "text", "text": "Background", "marks": [{"type": "strong"}]},
                ]},
                {"type": "paragraph", "content": [
                    {"type": "text", "text": "Some actual content"},
                ]},
            ],
        }
        result = extract_adf_text(adf)
        assert result == "Some actual content"

    def test_extract_adf_text_none_input(self, db_path):
        assert extract_adf_text(None) == ""
        assert extract_adf_text({}) == ""

    def test_extract_risk_draft(self, db_path):
        sug_id = self._insert_risk_suggestion(db_path)
        service = RiskRefinementService(db_path=db_path)
        sug = service.get_suggestion(sug_id)

        draft = service._extract_risk_draft(sug)

        assert draft["title"] == "Model accuracy regression"
        assert "accuracy drop" in draft["background"]
        assert "delay timeline" in draft["impact_analysis"]
        assert "MRMC" in draft["mitigation"]
        assert draft["priority"] == "High"
        assert draft["timeline_impact_days"] == "5"
        assert "Sarah" in draft["evidence"]

    def test_apply_refinement_updates_suggestion(self, db_path):
        sug_id = self._insert_risk_suggestion(db_path)
        service = RiskRefinementService(db_path=db_path)

        refined = {
            "title": "Refined Risk Title",
            "background": "Refined background with more detail",
            "impact_analysis": "Severity: High, Probability: Medium",
            "mitigation": "Step 1: Do X. Step 2: Do Y.",
            "priority": "High",
            "timeline_impact_days": 10,
            "evidence": "Sarah: 'accuracy dropped by 5%'",
        }

        result = service.apply_refinement(sug_id, refined)

        assert result is not None
        assert result.title == "Refined Risk Title"
        assert result.detail == "Refined background with more detail"
        assert result.evidence == "Sarah: 'accuracy dropped by 5%'"
        assert result.confidence == 1.0
        assert "Refined Risk Title" in result.proposed_preview

        # Verify payload was rebuilt
        import json as _json
        payload = _json.loads(result.proposed_payload)
        assert payload["summary"] == "Refined Risk Title"
        assert payload["fields"]["priority"]["name"] == "High"

    def test_apply_refinement_nonexistent_returns_none(self, db_path):
        service = RiskRefinementService(db_path=db_path)
        result = service.apply_refinement(999, {"title": "X"})
        assert result is None

    async def test_continue_risk_refinement_max_rounds_forces_satisfied(self, db_path):
        sug_id = self._insert_risk_suggestion(db_path)
        service = RiskRefinementService(db_path=db_path)

        from src.models.project import Project
        project = Project(
            id=1, jira_goal_key="PROG-100", name="Test Project",
            confluence_charter_id="111", confluence_xft_id="222",
            status="active", phase="planning", created_at="2026-01-01",
        )

        draft = {"title": "Final draft", "background": "bg"}
        result = await service.continue_risk_refinement(
            suggestion_id=sug_id,
            project=project,
            risk_draft=draft,
            qa_history=[],
            round_number=5,  # MAX_REFINE_ROUNDS
        )

        assert result["satisfied"] is True
        assert result["refined_risk"] == draft
