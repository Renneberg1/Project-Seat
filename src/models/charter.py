"""Charter update suggestion models."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any


class CharterSuggestionStatus(str, enum.Enum):
    PENDING = "pending"
    QUEUED = "queued"
    REJECTED = "rejected"


@dataclass
class CharterSuggestion:
    id: int
    project_id: int
    section_name: str
    current_text: str
    proposed_text: str
    rationale: str
    confidence: float
    proposed_payload: str  # JSON string
    proposed_preview: str
    analysis_summary: str
    status: CharterSuggestionStatus
    approval_item_id: int | None
    created_at: str

    @classmethod
    def from_row(cls, row: Any) -> CharterSuggestion:
        return cls(
            id=row["id"],
            project_id=row["project_id"],
            section_name=row["section_name"],
            current_text=row["current_text"],
            proposed_text=row["proposed_text"],
            rationale=row["rationale"],
            confidence=row["confidence"],
            proposed_payload=row["proposed_payload"],
            proposed_preview=row["proposed_preview"],
            analysis_summary=row["analysis_summary"],
            status=CharterSuggestionStatus(row["status"]),
            approval_item_id=row["approval_item_id"],
            created_at=row["created_at"],
        )
