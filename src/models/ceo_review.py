"""CEO Review models."""

from __future__ import annotations

import enum
import json
from dataclasses import dataclass
from typing import Any


class CeoReviewStatus(str, enum.Enum):
    DRAFT = "draft"
    QUEUED = "queued"
    PUBLISHED = "published"
    REJECTED = "rejected"


@dataclass
class CeoReview:
    id: int
    project_id: int
    review_json: dict[str, Any]
    confluence_body: str
    approval_item_id: int | None
    status: CeoReviewStatus
    created_at: str

    @classmethod
    def from_row(cls, row: Any) -> CeoReview:
        return cls(
            id=row["id"],
            project_id=row["project_id"],
            review_json=json.loads(row["review_json"]) if row["review_json"] else {},
            confluence_body=row["confluence_body"],
            approval_item_id=row["approval_item_id"],
            status=CeoReviewStatus(row["status"]),
            created_at=row["created_at"],
        )
