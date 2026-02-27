"""Closure Report models."""

from __future__ import annotations

import enum
import json
from dataclasses import dataclass
from typing import Any


class ClosureReportStatus(str, enum.Enum):
    DRAFT = "draft"
    QUEUED = "queued"
    PUBLISHED = "published"
    REJECTED = "rejected"


@dataclass
class ClosureReport:
    id: int
    project_id: int
    report_json: dict[str, Any]
    confluence_body: str
    approval_item_id: int | None
    status: ClosureReportStatus
    created_at: str

    @classmethod
    def from_row(cls, row: Any) -> ClosureReport:
        return cls(
            id=row["id"],
            project_id=row["project_id"],
            report_json=json.loads(row["report_json"]) if row["report_json"] else {},
            confluence_body=row["confluence_body"],
            approval_item_id=row["approval_item_id"],
            status=ClosureReportStatus(row["status"]),
            created_at=row["created_at"],
        )
