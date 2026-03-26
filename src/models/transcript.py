"""Transcript data models."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TranscriptSegment:
    speaker: str
    text: str
    timestamp_start: str | None = None
    timestamp_end: str | None = None


@dataclass
class ParsedTranscript:
    filename: str
    segments: list[TranscriptSegment]
    raw_text: str
    speaker_list: list[str]
    duration_hint: str | None = None


@dataclass
class TranscriptRecord:
    id: int
    project_id: int | None
    filename: str
    raw_text: str
    processed_json: str | None
    meeting_summary: str | None
    source: str = "manual"
    created_at: str = ""

    @classmethod
    def from_row(cls, row: Any) -> TranscriptRecord:
        return cls(
            id=row["id"],
            project_id=row["project_id"],
            filename=row["filename"],
            raw_text=row["raw_text"],
            processed_json=row["processed_json"],
            meeting_summary=row["meeting_summary"] if "meeting_summary" in row.keys() else None,
            source=row["source"] if "source" in row.keys() else "manual",
            created_at=row["created_at"],
        )


# ------------------------------------------------------------------
# Suggestion models (used in Stage 3+)
# ------------------------------------------------------------------

class SuggestionType(str, enum.Enum):
    RISK = "risk"
    DECISION = "decision"
    UPDATE_EXISTING = "update_existing"
    XFT_UPDATE = "xft_update"
    CHARTER_UPDATE = "charter_update"
    ACTION_ITEM = "action_item"
    NOTE = "note"
    INSIGHT = "insight"


class SuggestionStatus(str, enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    QUEUED = "queued"


@dataclass
class TranscriptSuggestion:
    id: int
    transcript_id: int
    project_id: int
    suggestion_type: SuggestionType
    title: str
    detail: str
    evidence: str
    proposed_payload: str  # JSON string
    proposed_action: str
    proposed_preview: str
    confidence: float
    status: SuggestionStatus
    approval_item_id: int | None
    created_at: str

    @classmethod
    def from_row(cls, row: Any) -> TranscriptSuggestion:
        return cls(
            id=row["id"],
            transcript_id=row["transcript_id"],
            project_id=row["project_id"],
            suggestion_type=SuggestionType(row["suggestion_type"]),
            title=row["title"],
            detail=row["detail"],
            evidence=row["evidence"],
            proposed_payload=row["proposed_payload"],
            proposed_action=row["proposed_action"],
            proposed_preview=row["proposed_preview"],
            confidence=row["confidence"],
            status=SuggestionStatus(row["status"]),
            approval_item_id=row["approval_item_id"],
            created_at=row["created_at"],
        )


@dataclass
class ProjectContext:
    """Assembled context about a project for LLM prompt building."""

    project_name: str
    jira_goal_key: str
    existing_risks: list[dict[str, str]]  # [{key, summary, status}]
    existing_decisions: list[dict[str, str]]
    charter_content: str | None = None
    xft_content: str | None = None
    default_component: str | None = None
    default_label: str | None = None
    open_action_items: list[dict[str, str]] = field(default_factory=list)
    knowledge_entries: list[dict[str, str]] = field(default_factory=list)
