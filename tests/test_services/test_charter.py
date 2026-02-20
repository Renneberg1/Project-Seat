"""Tests for the Charter service — question generation, edit proposals, suggestion management."""

from __future__ import annotations

import json
import sqlite3
from unittest.mock import AsyncMock, patch

import pytest

from src.database import init_db
from src.models.charter import CharterSuggestionStatus
from src.models.project import Project
from src.services.charter import CharterService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    init_db(path)
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO projects (id, jira_goal_key, name, status, phase, "
        "confluence_charter_id, confluence_xft_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (1, "PROG-100", "Test Project", "active", "planning", "111", "222"),
    )
    conn.commit()
    conn.close()
    return path


def _make_project() -> Project:
    return Project(
        id=1, jira_goal_key="PROG-100", name="Test Project",
        confluence_charter_id="111", confluence_xft_id="222",
        status="active", phase="planning", created_at="2026-01-01",
    )


def _insert_suggestion(db_path, **overrides):
    defaults = dict(
        project_id=1,
        section_name="Commercial Objective",
        current_text="Old objective",
        proposed_text="New objective",
        rationale="User requested change",
        confidence=0.85,
        proposed_payload=json.dumps({
            "page_id": "111",
            "section_replace_mode": True,
            "section_name": "Commercial Objective",
            "new_content": "New objective",
        }),
        proposed_preview="Section: Commercial Objective\nProposed: New objective",
        analysis_summary="Updated objective",
        status="pending",
    )
    defaults.update(overrides)
    conn = sqlite3.connect(db_path)
    cursor = conn.execute(
        """INSERT INTO charter_suggestions
           (project_id, section_name, current_text, proposed_text,
            rationale, confidence, proposed_payload, proposed_preview,
            analysis_summary, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            defaults["project_id"], defaults["section_name"],
            defaults["current_text"], defaults["proposed_text"],
            defaults["rationale"], defaults["confidence"],
            defaults["proposed_payload"], defaults["proposed_preview"],
            defaults["analysis_summary"], defaults["status"],
        ),
    )
    conn.commit()
    sug_id = cursor.lastrowid
    conn.close()
    return sug_id


# ---------------------------------------------------------------------------
# generate_questions
# ---------------------------------------------------------------------------


class TestGenerateQuestions:

    async def test_calls_agent_and_returns_questions(self, db_path):
        service = CharterService(db_path=db_path)
        project = _make_project()

        mock_questions = [
            {"question": "What date?", "section_name": "Date", "why_needed": "Missing"},
        ]

        mock_provider = AsyncMock()
        mock_provider.close = AsyncMock()

        with patch.object(service, "fetch_charter_sections", new_callable=AsyncMock) as mock_fetch, \
             patch("src.engine.agent.get_provider", return_value=mock_provider), \
             patch("src.engine.agent.CharterAgent") as MockAgent:
            mock_fetch.return_value = [
                {"name": "Date", "content": "[Insert Date]"},
            ]
            instance = MockAgent.return_value
            instance.ask_questions = AsyncMock(return_value={"questions": mock_questions})

            result = await service.generate_questions(project, "Change the date")

        assert len(result) == 1
        assert result[0]["question"] == "What date?"


# ---------------------------------------------------------------------------
# analyze_charter_update
# ---------------------------------------------------------------------------


class TestAnalyzeCharterUpdate:

    async def test_stores_suggestions_in_db(self, db_path):
        service = CharterService(db_path=db_path)
        project = _make_project()

        mock_edits = {
            "summary": "Updated scope",
            "section_edits": [
                {
                    "section_name": "Commercial Objective",
                    "proposed_text": "New AI product launch",
                    "rationale": "User specified new objective",
                    "confidence": 0.9,
                },
            ],
        }

        mock_provider = AsyncMock()
        mock_provider.close = AsyncMock()

        with patch.object(service, "fetch_charter_sections", new_callable=AsyncMock) as mock_fetch, \
             patch("src.engine.agent.get_provider", return_value=mock_provider), \
             patch("src.engine.agent.CharterAgent") as MockAgent:
            mock_fetch.return_value = [
                {"name": "Commercial Objective", "content": "Old objective"},
            ]
            instance = MockAgent.return_value
            instance.propose_edits = AsyncMock(return_value=mock_edits)

            suggestions = await service.analyze_charter_update(
                project, "New objective", [{"question": "Q", "answer": "A"}]
            )

        assert len(suggestions) == 1
        assert suggestions[0].section_name == "Commercial Objective"
        assert suggestions[0].proposed_text == "New AI product launch"
        assert suggestions[0].status == CharterSuggestionStatus.PENDING

    async def test_stores_analysis_summary(self, db_path):
        service = CharterService(db_path=db_path)
        project = _make_project()

        mock_edits = {
            "summary": "Big changes coming",
            "section_edits": [
                {
                    "section_name": "Date",
                    "proposed_text": "2027-01-01",
                    "rationale": "New date",
                    "confidence": 0.8,
                },
            ],
        }

        mock_provider = AsyncMock()
        mock_provider.close = AsyncMock()

        with patch.object(service, "fetch_charter_sections", new_callable=AsyncMock) as mock_fetch, \
             patch("src.engine.agent.get_provider", return_value=mock_provider), \
             patch("src.engine.agent.CharterAgent") as MockAgent:
            mock_fetch.return_value = [{"name": "Date", "content": "TBD"}]
            instance = MockAgent.return_value
            instance.propose_edits = AsyncMock(return_value=mock_edits)

            suggestions = await service.analyze_charter_update(
                project, "Change date", []
            )

        assert suggestions[0].analysis_summary == "Big changes coming"


# ---------------------------------------------------------------------------
# accept / reject suggestions
# ---------------------------------------------------------------------------


class TestSuggestionWorkflow:

    def test_accept_suggestion_creates_approval_item(self, db_path):
        sug_id = _insert_suggestion(db_path)
        service = CharterService(db_path=db_path)
        project = _make_project()

        result = service.accept_suggestion(sug_id, project)

        assert result is not None
        assert result.status == CharterSuggestionStatus.QUEUED
        assert result.approval_item_id is not None

        from src.engine.approval import ApprovalEngine
        engine = ApprovalEngine(db_path=db_path)
        item = engine.get(result.approval_item_id)
        assert item is not None
        payload = json.loads(item.payload)
        assert payload["section_replace_mode"] is True
        assert payload["section_name"] == "Commercial Objective"

    def test_accept_no_charter_id_raises(self, db_path):
        sug_id = _insert_suggestion(db_path)
        service = CharterService(db_path=db_path)
        project = _make_project()
        project.confluence_charter_id = None

        with pytest.raises(ValueError, match="no Charter page"):
            service.accept_suggestion(sug_id, project)

    def test_reject_suggestion_updates_status(self, db_path):
        sug_id = _insert_suggestion(db_path)
        service = CharterService(db_path=db_path)

        result = service.reject_suggestion(sug_id)

        assert result is not None
        assert result.status == CharterSuggestionStatus.REJECTED

    def test_accept_all_queues_all_pending(self, db_path):
        _insert_suggestion(db_path, section_name="Date")
        _insert_suggestion(db_path, section_name="Status")
        service = CharterService(db_path=db_path)
        project = _make_project()

        item_ids = service.accept_all_suggestions(project)

        assert len(item_ids) == 2
        suggestions = service.list_suggestions(project.id)
        assert all(s.status == CharterSuggestionStatus.QUEUED for s in suggestions)

    def test_list_suggestions(self, db_path):
        _insert_suggestion(db_path, section_name="A")
        _insert_suggestion(db_path, section_name="B")
        service = CharterService(db_path=db_path)

        suggestions = service.list_suggestions(1)
        assert len(suggestions) == 2
