"""Knowledge database models — action items and knowledge entries."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ActionItem:
    id: int
    project_id: int
    transcript_id: int | None
    title: str
    owner: str
    due_date: str | None
    status: str
    source: str
    evidence: str
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: Any) -> ActionItem:
        return cls(
            id=row["id"],
            project_id=row["project_id"],
            transcript_id=row["transcript_id"],
            title=row["title"],
            owner=row["owner"],
            due_date=row["due_date"],
            status=row["status"],
            source=row["source"],
            evidence=row["evidence"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass
class KnowledgeEntry:
    id: int
    project_id: int
    transcript_id: int | None
    entry_type: str
    title: str
    content: str
    tags: list[str]
    source: str
    published: bool
    approval_item_id: int | None
    created_at: str

    @classmethod
    def from_row(cls, row: Any) -> KnowledgeEntry:
        raw_tags = row["tags"]
        tags = json.loads(raw_tags) if isinstance(raw_tags, str) else raw_tags
        return cls(
            id=row["id"],
            project_id=row["project_id"],
            transcript_id=row["transcript_id"],
            entry_type=row["entry_type"],
            title=row["title"],
            content=row["content"],
            tags=tags if isinstance(tags, list) else [],
            source=row["source"],
            published=bool(row["published"]),
            approval_item_id=row["approval_item_id"],
            created_at=row["created_at"],
        )
