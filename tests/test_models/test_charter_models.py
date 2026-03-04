"""Tests for Charter suggestion domain models."""

from __future__ import annotations

from src.models.charter import CharterSuggestion, CharterSuggestionStatus


# ---------------------------------------------------------------------------
# CharterSuggestionStatus enum
# ---------------------------------------------------------------------------


def test_charter_suggestion_status_values():
    assert CharterSuggestionStatus.PENDING.value == "pending"
    assert CharterSuggestionStatus.QUEUED.value == "queued"
    assert CharterSuggestionStatus.REJECTED.value == "rejected"


def test_charter_suggestion_status_is_str_enum():
    """CharterSuggestionStatus members are also plain strings."""
    assert isinstance(CharterSuggestionStatus.PENDING, str)
    assert CharterSuggestionStatus.QUEUED == "queued"


def test_charter_suggestion_status_all_members():
    members = {s.value for s in CharterSuggestionStatus}
    assert members == {"pending", "queued", "rejected"}


# ---------------------------------------------------------------------------
# CharterSuggestion.from_row
# ---------------------------------------------------------------------------


def _make_charter_row(
    *,
    id: int = 1,
    project_id: int = 42,
    section_name: str = "Scope",
    current_text: str = "Old scope text",
    proposed_text: str = "New scope text",
    rationale: str = "Updated based on meeting notes",
    confidence: float = 0.85,
    proposed_payload: str = '{"section": "Scope", "html": "<p>New</p>"}',
    proposed_preview: str = "<p>New scope text</p>",
    analysis_summary: str = "Charter scope section updated",
    status: str = "pending",
    approval_item_id: int | None = None,
    created_at: str = "2026-02-15T09:30:00",
) -> dict:
    return {
        "id": id,
        "project_id": project_id,
        "section_name": section_name,
        "current_text": current_text,
        "proposed_text": proposed_text,
        "rationale": rationale,
        "confidence": confidence,
        "proposed_payload": proposed_payload,
        "proposed_preview": proposed_preview,
        "analysis_summary": analysis_summary,
        "status": status,
        "approval_item_id": approval_item_id,
        "created_at": created_at,
    }


def test_charter_suggestion_from_row_all_fields():
    row = _make_charter_row()
    sug = CharterSuggestion.from_row(row)

    assert sug.id == 1
    assert sug.project_id == 42
    assert sug.section_name == "Scope"
    assert sug.current_text == "Old scope text"
    assert sug.proposed_text == "New scope text"
    assert sug.rationale == "Updated based on meeting notes"
    assert sug.confidence == 0.85
    assert sug.proposed_payload == '{"section": "Scope", "html": "<p>New</p>"}'
    assert sug.proposed_preview == "<p>New scope text</p>"
    assert sug.analysis_summary == "Charter scope section updated"
    assert sug.status == CharterSuggestionStatus.PENDING
    assert sug.approval_item_id is None
    assert sug.created_at == "2026-02-15T09:30:00"


def test_charter_suggestion_from_row_queued_with_approval():
    row = _make_charter_row(status="queued", approval_item_id=7)
    sug = CharterSuggestion.from_row(row)

    assert sug.status == CharterSuggestionStatus.QUEUED
    assert sug.approval_item_id == 7


def test_charter_suggestion_from_row_rejected_status():
    row = _make_charter_row(status="rejected")
    sug = CharterSuggestion.from_row(row)

    assert sug.status == CharterSuggestionStatus.REJECTED


def test_charter_suggestion_from_row_high_confidence():
    row = _make_charter_row(confidence=0.99)
    sug = CharterSuggestion.from_row(row)

    assert sug.confidence == 0.99


def test_charter_suggestion_from_row_zero_confidence():
    row = _make_charter_row(confidence=0.0)
    sug = CharterSuggestion.from_row(row)

    assert sug.confidence == 0.0
