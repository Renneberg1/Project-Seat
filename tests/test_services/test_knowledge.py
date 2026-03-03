"""Tests for KnowledgeService and KnowledgeRepository."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config import Settings, AtlassianSettings, LLMSettings
from src.database import init_db, get_db
from src.repositories.knowledge_repo import KnowledgeRepository
from src.services.knowledge import KnowledgeService


@pytest.fixture()
def db_path(tmp_path: Path) -> str:
    path = str(tmp_path / "knowledge_test.db")
    init_db(path)
    return path


@pytest.fixture()
def repo(db_path: str) -> KnowledgeRepository:
    return KnowledgeRepository(db_path)


@pytest.fixture()
def service(db_path: str) -> KnowledgeService:
    settings = Settings(
        atlassian=AtlassianSettings(domain="test", email="test@test.com", api_token="fake"),
        llm=LLMSettings(),
        db_path=db_path,
    )
    return KnowledgeService(db_path=db_path, settings=settings)


def _seed_project(db_path: str) -> int:
    with get_db(db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO projects (jira_goal_key, name, status, phase) VALUES (?, ?, ?, ?)",
            ("PROG-1", "Test Project", "active", "planning"),
        )
        conn.commit()
        return cursor.lastrowid


class TestActionItems:
    def test_insert_and_list(self, repo: KnowledgeRepository, db_path: str) -> None:
        pid = _seed_project(db_path)
        aid = repo.insert_action_item(pid, "Write unit tests", owner="Alice")
        items = repo.list_action_items(pid)
        assert len(items) == 1
        assert items[0].title == "Write unit tests"
        assert items[0].owner == "Alice"
        assert items[0].status == "open"

    def test_filter_by_status(self, repo: KnowledgeRepository, db_path: str) -> None:
        pid = _seed_project(db_path)
        repo.insert_action_item(pid, "Task 1")
        aid2 = repo.insert_action_item(pid, "Task 2")
        repo.update_action_item_status(aid2, "done")

        open_items = repo.list_action_items(pid, "open")
        done_items = repo.list_action_items(pid, "done")
        assert len(open_items) == 1
        assert len(done_items) == 1

    def test_count(self, repo: KnowledgeRepository, db_path: str) -> None:
        pid = _seed_project(db_path)
        repo.insert_action_item(pid, "Task 1")
        repo.insert_action_item(pid, "Task 2")
        aid3 = repo.insert_action_item(pid, "Task 3")
        repo.update_action_item_status(aid3, "done")

        counts = repo.count_action_items(pid)
        assert counts == {"total": 3, "open": 2}


class TestKnowledgeEntries:
    def test_insert_and_list(self, repo: KnowledgeRepository, db_path: str) -> None:
        pid = _seed_project(db_path)
        repo.insert_knowledge_entry(pid, "note", "Meeting notes", content="Discussed XYZ", tags=["sprint-1"])
        entries = repo.list_knowledge_entries(pid, "note")
        assert len(entries) == 1
        assert entries[0].title == "Meeting notes"
        assert entries[0].tags == ["sprint-1"]

    def test_filter_by_type(self, repo: KnowledgeRepository, db_path: str) -> None:
        pid = _seed_project(db_path)
        repo.insert_knowledge_entry(pid, "note", "A note")
        repo.insert_knowledge_entry(pid, "insight", "An insight")

        notes = repo.list_knowledge_entries(pid, "note")
        insights = repo.list_knowledge_entries(pid, "insight")
        assert len(notes) == 1
        assert len(insights) == 1

    def test_search(self, repo: KnowledgeRepository, db_path: str) -> None:
        pid = _seed_project(db_path)
        repo.insert_knowledge_entry(pid, "note", "API Design Review", content="Discussed REST endpoints")
        repo.insert_knowledge_entry(pid, "note", "Sprint Planning", content="Assigned tasks")

        results = repo.search_knowledge(pid, "API")
        assert len(results) == 1
        assert results[0].title == "API Design Review"

        results = repo.search_knowledge(pid, "tasks")
        assert len(results) == 1
        assert results[0].title == "Sprint Planning"


class TestStoreFromAnalysis:
    def test_routes_suggestions(self, service: KnowledgeService, db_path: str) -> None:
        pid = _seed_project(db_path)

        suggestions = [
            {"type": "action_item", "title": "Fix bug", "owner_name": "Bob", "due_date_hint": "2026-03-15", "evidence": "Bob said he'd fix it"},
            {"type": "note", "title": "API status", "background": "API is 80% complete", "tags": ["api"]},
            {"type": "insight", "title": "Risk pattern", "background": "Integration risks are recurring", "tags": ["risk", "pattern"]},
        ]

        counts = service.store_from_analysis(pid, transcript_id=None, suggestions=suggestions)
        assert counts == {"action_items": 1, "notes": 1, "insights": 1}

        items = service.list_action_items(pid)
        assert len(items) == 1
        assert items[0].title == "Fix bug"
        assert items[0].owner == "Bob"

        notes = service.list_knowledge_entries(pid, "note")
        assert len(notes) == 1
        assert notes[0].tags == ["api"]

        insights = service.list_knowledge_entries(pid, "insight")
        assert len(insights) == 1

    def test_manual_add(self, service: KnowledgeService, db_path: str) -> None:
        pid = _seed_project(db_path)

        service.add_action_item(pid, "Manual task", owner="Charlie")
        service.add_knowledge_entry(pid, "note", "Manual note", content="Some content", tags=["manual"])

        items = service.list_action_items(pid)
        assert len(items) == 1
        assert items[0].source == "manual"

        notes = service.list_knowledge_entries(pid, "note")
        assert len(notes) == 1
        assert notes[0].source == "manual"
