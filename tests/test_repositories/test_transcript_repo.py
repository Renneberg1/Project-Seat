"""Tests for TranscriptRepository — transcript cache and suggestion CRUD."""

from __future__ import annotations

from src.models.transcript import SuggestionStatus, SuggestionType
from src.repositories.project_repo import ProjectRepository
from src.repositories.transcript_repo import TranscriptRepository


def _make_project(tmp_db: str) -> int:
    return ProjectRepository(tmp_db).create(jira_goal_key="PROG-1", name="Test")


def _insert_transcript(repo: TranscriptRepository, project_id: int | None = None) -> int:
    return repo.insert_transcript(
        project_id=project_id,
        filename="meeting.vtt",
        raw_text="Hello world",
        processed_json='{"segments": []}',
    )


def _insert_suggestion(repo: TranscriptRepository, tid: int, pid: int, **kw) -> int:
    defaults = dict(
        transcript_id=tid,
        project_id=pid,
        suggestion_type="risk",
        title="Risk: data loss",
        detail="Potential data loss scenario",
        evidence="Speaker said ...",
        proposed_payload='{"summary": "Risk"}',
        proposed_action="create_jira_issue",
        proposed_preview="Create RISK ticket",
        confidence=0.85,
        status="pending",
    )
    defaults.update(kw)
    return repo.insert_suggestion(**defaults)


# ------------------------------------------------------------------
# Transcript cache
# ------------------------------------------------------------------


class TestTranscriptInsertAndGet:
    def test_insert_returns_id(self, tmp_db: str):
        repo = TranscriptRepository(tmp_db)
        tid = _insert_transcript(repo)
        assert isinstance(tid, int) and tid >= 1

    def test_get_transcript(self, tmp_db: str):
        repo = TranscriptRepository(tmp_db)
        pid = _make_project(tmp_db)
        tid = _insert_transcript(repo, project_id=pid)
        rec = repo.get_transcript(tid)
        assert rec is not None
        assert rec.filename == "meeting.vtt"
        assert rec.raw_text == "Hello world"
        assert rec.project_id == pid
        assert rec.source == "manual"

    def test_get_transcript_not_found(self, tmp_db: str):
        repo = TranscriptRepository(tmp_db)
        assert repo.get_transcript(9999) is None

    def test_insert_with_zoom_source(self, tmp_db: str):
        repo = TranscriptRepository(tmp_db)
        tid = repo.insert_transcript(None, "zoom.vtt", "text", "{}", source="zoom")
        rec = repo.get_transcript(tid)
        assert rec.source == "zoom"


class TestTranscriptList:
    def test_list_transcripts_for_project(self, tmp_db: str):
        repo = TranscriptRepository(tmp_db)
        pid = _make_project(tmp_db)
        _insert_transcript(repo, project_id=pid)
        _insert_transcript(repo, project_id=pid)
        records = repo.list_transcripts(pid)
        assert len(records) == 2

    def test_list_transcripts_empty(self, tmp_db: str):
        repo = TranscriptRepository(tmp_db)
        assert repo.list_transcripts(9999) == []

    def test_list_all_transcripts_no_filter(self, tmp_db: str):
        repo = TranscriptRepository(tmp_db)
        pid = _make_project(tmp_db)
        _insert_transcript(repo, project_id=pid)
        _insert_transcript(repo, project_id=None)
        assert len(repo.list_all_transcripts()) == 2

    def test_list_all_transcripts_filter_source(self, tmp_db: str):
        repo = TranscriptRepository(tmp_db)
        repo.insert_transcript(None, "a.vtt", "x", "{}", source="manual")
        repo.insert_transcript(None, "b.vtt", "y", "{}", source="zoom")
        assert len(repo.list_all_transcripts(source="zoom")) == 1

    def test_list_all_transcripts_filter_unassigned(self, tmp_db: str):
        repo = TranscriptRepository(tmp_db)
        pid = _make_project(tmp_db)
        _insert_transcript(repo, project_id=pid)
        _insert_transcript(repo, project_id=None)
        unassigned = repo.list_all_transcripts(unassigned=True)
        assert len(unassigned) == 1
        assert unassigned[0].project_id is None


class TestTranscriptDelete:
    def test_delete_transcript(self, tmp_db: str):
        repo = TranscriptRepository(tmp_db)
        pid = _make_project(tmp_db)
        tid = _insert_transcript(repo, project_id=pid)
        repo.delete_transcript(tid)
        assert repo.get_transcript(tid) is None

    def test_delete_transcript_cascades_suggestions(self, tmp_db: str):
        repo = TranscriptRepository(tmp_db)
        pid = _make_project(tmp_db)
        tid = _insert_transcript(repo, project_id=pid)
        sid = _insert_suggestion(repo, tid, pid)
        repo.delete_transcript(tid)
        assert repo.get_suggestion(sid) is None


class TestTranscriptMiscellaneous:
    def test_update_meeting_summary(self, tmp_db: str):
        repo = TranscriptRepository(tmp_db)
        tid = _insert_transcript(repo)
        repo.update_meeting_summary(tid, "Summary of meeting")
        rec = repo.get_transcript(tid)
        assert rec.meeting_summary == "Summary of meeting"

    def test_assign_project(self, tmp_db: str):
        repo = TranscriptRepository(tmp_db)
        pid = _make_project(tmp_db)
        tid = _insert_transcript(repo, project_id=None)
        repo.assign_project(tid, pid)
        assert repo.get_transcript(tid).project_id == pid

    def test_get_meeting_summaries(self, tmp_db: str):
        repo = TranscriptRepository(tmp_db)
        pid = _make_project(tmp_db)
        tid = _insert_transcript(repo, project_id=pid)
        repo.update_meeting_summary(tid, "Summary 1")
        summaries = repo.get_meeting_summaries(pid)
        assert len(summaries) == 1
        assert summaries[0]["summary"] == "Summary 1"

    def test_get_transcript_summary_counts(self, tmp_db: str):
        repo = TranscriptRepository(tmp_db)
        pid = _make_project(tmp_db)
        tid = _insert_transcript(repo, project_id=pid)
        _insert_suggestion(repo, tid, pid)
        summary = repo.get_transcript_summary(pid)
        assert summary["transcript_count"] == 1
        assert summary["suggestion_count"] == 1
        assert summary["pending_count"] == 1


# ------------------------------------------------------------------
# Suggestions
# ------------------------------------------------------------------


class TestSuggestionCRUD:
    def test_insert_and_get_suggestion(self, tmp_db: str):
        repo = TranscriptRepository(tmp_db)
        pid = _make_project(tmp_db)
        tid = _insert_transcript(repo, project_id=pid)
        sid = _insert_suggestion(repo, tid, pid)
        s = repo.get_suggestion(sid)
        assert s is not None
        assert s.title == "Risk: data loss"
        assert s.suggestion_type == SuggestionType.RISK
        assert s.status == SuggestionStatus.PENDING
        assert s.confidence == 0.85

    def test_get_suggestion_not_found(self, tmp_db: str):
        repo = TranscriptRepository(tmp_db)
        assert repo.get_suggestion(9999) is None

    def test_list_suggestions(self, tmp_db: str):
        repo = TranscriptRepository(tmp_db)
        pid = _make_project(tmp_db)
        tid = _insert_transcript(repo, project_id=pid)
        _insert_suggestion(repo, tid, pid, title="S1")
        _insert_suggestion(repo, tid, pid, title="S2")
        suggestions = repo.list_suggestions(tid)
        assert len(suggestions) == 2

    def test_list_suggestions_empty(self, tmp_db: str):
        repo = TranscriptRepository(tmp_db)
        assert repo.list_suggestions(9999) == []


class TestSuggestionUpdate:
    def test_update_suggestion_status(self, tmp_db: str):
        repo = TranscriptRepository(tmp_db)
        pid = _make_project(tmp_db)
        tid = _insert_transcript(repo, project_id=pid)
        sid = _insert_suggestion(repo, tid, pid)
        repo.update_suggestion_status(sid, SuggestionStatus.ACCEPTED.value)
        assert repo.get_suggestion(sid).status == SuggestionStatus.ACCEPTED

    def test_update_suggestion_status_with_approval_id(self, tmp_db: str):
        from src.models.approval import ApprovalAction
        from src.repositories.approval_repo import ApprovalRepository

        repo = TranscriptRepository(tmp_db)
        pid = _make_project(tmp_db)
        tid = _insert_transcript(repo, project_id=pid)
        sid = _insert_suggestion(repo, tid, pid)
        # Create a real approval queue item to satisfy FK constraint
        approval_repo = ApprovalRepository(tmp_db)
        aq_id = approval_repo.propose(
            ApprovalAction.CREATE_JIRA_ISSUE, {}, "preview", project_id=pid,
        )
        repo.update_suggestion_status(sid, SuggestionStatus.QUEUED.value, approval_item_id=aq_id)
        s = repo.get_suggestion(sid)
        assert s.status == SuggestionStatus.QUEUED
        assert s.approval_item_id == aq_id

    def test_update_suggestion_content(self, tmp_db: str):
        repo = TranscriptRepository(tmp_db)
        pid = _make_project(tmp_db)
        tid = _insert_transcript(repo, project_id=pid)
        sid = _insert_suggestion(repo, tid, pid)
        repo.update_suggestion_content(
            sid,
            title="Refined risk",
            detail="Better detail",
            evidence="Updated quote",
            proposed_payload='{"v":2}',
            proposed_preview="Updated preview",
            confidence=0.95,
        )
        s = repo.get_suggestion(sid)
        assert s.title == "Refined risk"
        assert s.confidence == 0.95


class TestSuggestionDelete:
    def test_delete_suggestions(self, tmp_db: str):
        repo = TranscriptRepository(tmp_db)
        pid = _make_project(tmp_db)
        tid = _insert_transcript(repo, project_id=pid)
        _insert_suggestion(repo, tid, pid)
        _insert_suggestion(repo, tid, pid)
        repo.delete_suggestions(tid)
        assert repo.list_suggestions(tid) == []

    def test_delete_non_accepted_keeps_accepted(self, tmp_db: str):
        repo = TranscriptRepository(tmp_db)
        pid = _make_project(tmp_db)
        tid = _insert_transcript(repo, project_id=pid)
        sid_pending = _insert_suggestion(repo, tid, pid, title="Pending")
        sid_accepted = _insert_suggestion(repo, tid, pid, title="Accepted", status="accepted")
        sid_rejected = _insert_suggestion(repo, tid, pid, title="Rejected", status="rejected")
        repo.delete_non_accepted_suggestions(tid)
        remaining = repo.list_suggestions(tid)
        assert len(remaining) == 1
        assert remaining[0].title == "Accepted"
