"""Release scope-freeze and publish-tracking models."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ReleaseStatus(str, Enum):
    PUBLISHED = "published"
    PENDING = "pending"


@dataclass
class Release:
    id: int
    project_id: int
    name: str
    locked: bool
    created_at: str
    version_snapshot: dict[str, str | None] | None = None

    @classmethod
    def from_row(cls, row: Any) -> Release:
        snapshot_raw = row["version_snapshot"]
        snapshot = json.loads(snapshot_raw) if snapshot_raw else None
        return cls(
            id=row["id"],
            project_id=row["project_id"],
            name=row["name"],
            locked=bool(row["locked"]),
            created_at=row["created_at"],
            version_snapshot=snapshot,
        )


@dataclass
class ReleaseDocument:
    release_id: int
    doc_title: str
