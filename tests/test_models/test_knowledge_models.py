"""Tests for Knowledge database models — ActionItem and KnowledgeEntry."""

from __future__ import annotations

import json

from src.models.knowledge import ActionItem, KnowledgeEntry


# ---------------------------------------------------------------------------
# ActionItem: direct construction
# ---------------------------------------------------------------------------


def test_action_item_construction():
    item = ActionItem(
        id=1,
        project_id=42,
        transcript_id=10,
        title="Follow up on risk assessment",
        owner="Alice",
        due_date="2026-03-15",
        status="open",
        source="transcript",
        evidence="Discussed in sprint planning meeting",
        created_at="2026-03-01T10:00:00",
        updated_at="2026-03-01T10:00:00",
    )

    assert item.id == 1
    assert item.project_id == 42
    assert item.transcript_id == 10
    assert item.title == "Follow up on risk assessment"
    assert item.owner == "Alice"
    assert item.due_date == "2026-03-15"
    assert item.status == "open"
    assert item.source == "transcript"


def test_action_item_nullable_fields():
    item = ActionItem(
        id=2,
        project_id=42,
        transcript_id=None,
        title="Review docs",
        owner="Bob",
        due_date=None,
        status="open",
        source="manual",
        evidence="",
        created_at="2026-03-01T10:00:00",
        updated_at="2026-03-01T10:00:00",
    )

    assert item.transcript_id is None
    assert item.due_date is None


# ---------------------------------------------------------------------------
# ActionItem.from_row
# ---------------------------------------------------------------------------


def test_action_item_from_row():
    row = {
        "id": 3,
        "project_id": 42,
        "transcript_id": 15,
        "title": "Update risk register",
        "owner": "Charlie",
        "due_date": "2026-04-01",
        "status": "done",
        "source": "transcript",
        "evidence": "Risk was discussed",
        "created_at": "2026-03-01T08:00:00",
        "updated_at": "2026-03-02T12:00:00",
    }
    item = ActionItem.from_row(row)

    assert item.id == 3
    assert item.project_id == 42
    assert item.transcript_id == 15
    assert item.title == "Update risk register"
    assert item.owner == "Charlie"
    assert item.due_date == "2026-04-01"
    assert item.status == "done"
    assert item.updated_at == "2026-03-02T12:00:00"


# ---------------------------------------------------------------------------
# KnowledgeEntry: direct construction
# ---------------------------------------------------------------------------


def test_knowledge_entry_construction():
    entry = KnowledgeEntry(
        id=1,
        project_id=42,
        transcript_id=10,
        entry_type="note",
        title="Architecture decision",
        content="Decided to use microservices pattern",
        tags=["architecture", "decision"],
        source="transcript",
        published=False,
        approval_item_id=None,
        created_at="2026-03-01T10:00:00",
    )

    assert entry.id == 1
    assert entry.entry_type == "note"
    assert entry.tags == ["architecture", "decision"]
    assert entry.published is False
    assert entry.approval_item_id is None


def test_knowledge_entry_empty_tags():
    entry = KnowledgeEntry(
        id=2,
        project_id=42,
        transcript_id=None,
        entry_type="insight",
        title="Performance insight",
        content="Response times improved 20%",
        tags=[],
        source="manual",
        published=True,
        approval_item_id=5,
        created_at="2026-03-01T10:00:00",
    )

    assert entry.tags == []
    assert entry.published is True
    assert entry.approval_item_id == 5


# ---------------------------------------------------------------------------
# KnowledgeEntry.from_row
# ---------------------------------------------------------------------------


def test_knowledge_entry_from_row_string_tags():
    row = {
        "id": 3,
        "project_id": 42,
        "transcript_id": 20,
        "entry_type": "note",
        "title": "Test note",
        "content": "Some content",
        "tags": json.dumps(["risk", "compliance"]),
        "source": "transcript",
        "published": 1,
        "approval_item_id": None,
        "created_at": "2026-03-01T10:00:00",
    }
    entry = KnowledgeEntry.from_row(row)

    assert entry.tags == ["risk", "compliance"]
    assert entry.published is True


def test_knowledge_entry_from_row_already_parsed_tags():
    """When tags is already a list (not a JSON string), it is used directly."""
    row = {
        "id": 4,
        "project_id": 42,
        "transcript_id": None,
        "entry_type": "insight",
        "title": "Insight",
        "content": "Content",
        "tags": ["already", "parsed"],
        "source": "manual",
        "published": 0,
        "approval_item_id": None,
        "created_at": "2026-03-01T10:00:00",
    }
    entry = KnowledgeEntry.from_row(row)

    assert entry.tags == ["already", "parsed"]
    assert entry.published is False


def test_knowledge_entry_from_row_non_list_tags_fallback():
    """When tags is neither a list nor valid JSON list, defaults to empty list."""
    row = {
        "id": 5,
        "project_id": 42,
        "transcript_id": None,
        "entry_type": "note",
        "title": "Bad tags",
        "content": "Content",
        "tags": 42,  # not a string or list
        "source": "manual",
        "published": 0,
        "approval_item_id": None,
        "created_at": "2026-03-01T10:00:00",
    }
    entry = KnowledgeEntry.from_row(row)

    assert entry.tags == []
