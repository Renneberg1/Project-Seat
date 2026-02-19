"""DHF (Design History File) document tracking models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class DocumentStatus(str, Enum):
    RELEASED = "released"
    DRAFT_UPDATE = "draft_update"
    IN_DRAFT = "in_draft"


@dataclass
class DHFDocument:
    title: str
    area: str
    released_version: str | None
    draft_version: str | None
    status: DocumentStatus
    last_modified: str
    author: str
    page_url: str


@dataclass
class DHFSummary:
    total_count: int
    released_count: int
    draft_update_count: int
    in_draft_count: int
    error: str | None = None
