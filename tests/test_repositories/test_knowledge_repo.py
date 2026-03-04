"""Tests for KnowledgeRepository — action items and knowledge entries."""

from __future__ import annotations

from src.repositories.knowledge_repo import KnowledgeRepository
from src.repositories.project_repo import ProjectRepository
from src.repositories.transcript_repo import TranscriptRepository


def _make_project(tmp_db: str) -> int:
    return ProjectRepository(tmp_db).create(jira_goal_key="PROG-1", name="Test")


def _make_transcript(tmp_db: str, pid: int) -> int:
    return TranscriptRepository(tmp_db).insert_transcript(pid, "m.vtt", "text", "{}")


# ------------------------------------------------------------------
# action_items
# ------------------------------------------------------------------


class TestActionItemInsertAndGet:
    def test_insert_returns_id(self, tmp_db: str):
        repo = KnowledgeRepository(tmp_db)
        pid = _make_project(tmp_db)
        aid = repo.insert_action_item(pid, title="Review risk register")
        assert isinstance(aid, int) and aid >= 1

    def test_get_action_item(self, tmp_db: str):
        repo = KnowledgeRepository(tmp_db)
        pid = _make_project(tmp_db)
        aid = repo.insert_action_item(
            pid,
            title="Follow up with vendor",
            owner="Alice",
            due_date="2026-02-01",
            source="manual",
            evidence="Mentioned in standup",
        )
        item = repo.get_action_item(aid)
        assert item is not None
        assert item.title == "Follow up with vendor"
        assert item.owner == "Alice"
        assert item.due_date == "2026-02-01"
        assert item.source == "manual"
        assert item.evidence == "Mentioned in standup"
        assert item.status == "open"

    def test_get_action_item_not_found(self, tmp_db: str):
        repo = KnowledgeRepository(tmp_db)
        assert repo.get_action_item(9999) is None

    def test_insert_with_transcript(self, tmp_db: str):
        repo = KnowledgeRepository(tmp_db)
        pid = _make_project(tmp_db)
        tid = _make_transcript(tmp_db, pid)
        aid = repo.insert_action_item(pid, title="Item", transcript_id=tid)
        assert repo.get_action_item(aid).transcript_id == tid


class TestActionItemList:
    def test_list_action_items(self, tmp_db: str):
        repo = KnowledgeRepository(tmp_db)
        pid = _make_project(tmp_db)
        repo.insert_action_item(pid, title="A1")
        repo.insert_action_item(pid, title="A2")
        items = repo.list_action_items(pid)
        assert len(items) == 2

    def test_list_action_items_filter_status(self, tmp_db: str):
        repo = KnowledgeRepository(tmp_db)
        pid = _make_project(tmp_db)
        aid = repo.insert_action_item(pid, title="Open one")
        repo.insert_action_item(pid, title="Another open")
        repo.update_action_item_status(aid, "done")
        open_items = repo.list_action_items(pid, status="open")
        assert len(open_items) == 1
        assert open_items[0].title == "Another open"

    def test_list_action_items_empty(self, tmp_db: str):
        repo = KnowledgeRepository(tmp_db)
        assert repo.list_action_items(9999) == []


class TestActionItemUpdate:
    def test_update_status(self, tmp_db: str):
        repo = KnowledgeRepository(tmp_db)
        pid = _make_project(tmp_db)
        aid = repo.insert_action_item(pid, title="Task")
        repo.update_action_item_status(aid, "done")
        assert repo.get_action_item(aid).status == "done"


class TestActionItemCount:
    def test_count_action_items(self, tmp_db: str):
        repo = KnowledgeRepository(tmp_db)
        pid = _make_project(tmp_db)
        aid1 = repo.insert_action_item(pid, title="A1")
        repo.insert_action_item(pid, title="A2")
        repo.update_action_item_status(aid1, "done")
        counts = repo.count_action_items(pid)
        assert counts["total"] == 2
        assert counts["open"] == 1

    def test_count_action_items_empty(self, tmp_db: str):
        repo = KnowledgeRepository(tmp_db)
        counts = repo.count_action_items(9999)
        assert counts == {"total": 0, "open": 0}


# ------------------------------------------------------------------
# knowledge_entries
# ------------------------------------------------------------------


class TestKnowledgeEntryInsertAndGet:
    def test_insert_returns_id(self, tmp_db: str):
        repo = KnowledgeRepository(tmp_db)
        pid = _make_project(tmp_db)
        eid = repo.insert_knowledge_entry(pid, entry_type="note", title="Design note")
        assert isinstance(eid, int) and eid >= 1

    def test_get_knowledge_entry(self, tmp_db: str):
        repo = KnowledgeRepository(tmp_db)
        pid = _make_project(tmp_db)
        eid = repo.insert_knowledge_entry(
            pid,
            entry_type="insight",
            title="Performance finding",
            content="The API responds in under 200ms",
            tags=["perf", "api"],
            source="manual",
        )
        entry = repo.get_knowledge_entry(eid)
        assert entry is not None
        assert entry.title == "Performance finding"
        assert entry.entry_type == "insight"
        assert entry.content == "The API responds in under 200ms"
        assert entry.tags == ["perf", "api"]
        assert entry.source == "manual"
        assert entry.published is False

    def test_get_knowledge_entry_not_found(self, tmp_db: str):
        repo = KnowledgeRepository(tmp_db)
        assert repo.get_knowledge_entry(9999) is None

    def test_insert_with_transcript(self, tmp_db: str):
        repo = KnowledgeRepository(tmp_db)
        pid = _make_project(tmp_db)
        tid = _make_transcript(tmp_db, pid)
        eid = repo.insert_knowledge_entry(pid, "note", "Note", transcript_id=tid)
        assert repo.get_knowledge_entry(eid).transcript_id == tid

    def test_insert_with_default_tags(self, tmp_db: str):
        repo = KnowledgeRepository(tmp_db)
        pid = _make_project(tmp_db)
        eid = repo.insert_knowledge_entry(pid, "note", "No tags")
        assert repo.get_knowledge_entry(eid).tags == []


class TestKnowledgeEntryList:
    def test_list_entries(self, tmp_db: str):
        repo = KnowledgeRepository(tmp_db)
        pid = _make_project(tmp_db)
        repo.insert_knowledge_entry(pid, "note", "N1")
        repo.insert_knowledge_entry(pid, "insight", "I1")
        entries = repo.list_knowledge_entries(pid)
        assert len(entries) == 2

    def test_list_entries_filter_type(self, tmp_db: str):
        repo = KnowledgeRepository(tmp_db)
        pid = _make_project(tmp_db)
        repo.insert_knowledge_entry(pid, "note", "N1")
        repo.insert_knowledge_entry(pid, "insight", "I1")
        notes = repo.list_knowledge_entries(pid, entry_type="note")
        assert len(notes) == 1
        assert notes[0].entry_type == "note"

    def test_list_entries_empty(self, tmp_db: str):
        repo = KnowledgeRepository(tmp_db)
        assert repo.list_knowledge_entries(9999) == []


class TestKnowledgeEntryPublish:
    def test_update_published(self, tmp_db: str):
        repo = KnowledgeRepository(tmp_db)
        pid = _make_project(tmp_db)
        eid = repo.insert_knowledge_entry(pid, "insight", "Insight")
        repo.update_published(eid, approval_item_id=42)
        entry = repo.get_knowledge_entry(eid)
        assert entry.published is True
        assert entry.approval_item_id == 42


class TestKnowledgeEntrySearch:
    def test_search_by_title(self, tmp_db: str):
        repo = KnowledgeRepository(tmp_db)
        pid = _make_project(tmp_db)
        repo.insert_knowledge_entry(pid, "note", "Performance analysis")
        repo.insert_knowledge_entry(pid, "note", "Risk assessment")
        results = repo.search_knowledge(pid, "Performance")
        assert len(results) == 1
        assert results[0].title == "Performance analysis"

    def test_search_by_content(self, tmp_db: str):
        repo = KnowledgeRepository(tmp_db)
        pid = _make_project(tmp_db)
        repo.insert_knowledge_entry(
            pid, "note", "Note A", content="The API latency is good"
        )
        repo.insert_knowledge_entry(
            pid, "note", "Note B", content="Database schema review"
        )
        results = repo.search_knowledge(pid, "latency")
        assert len(results) == 1

    def test_search_no_results(self, tmp_db: str):
        repo = KnowledgeRepository(tmp_db)
        pid = _make_project(tmp_db)
        repo.insert_knowledge_entry(pid, "note", "Something")
        assert repo.search_knowledge(pid, "nonexistent") == []

    def test_search_case_insensitive(self, tmp_db: str):
        repo = KnowledgeRepository(tmp_db)
        pid = _make_project(tmp_db)
        repo.insert_knowledge_entry(pid, "note", "UPPER case title")
        results = repo.search_knowledge(pid, "upper")
        assert len(results) == 1
