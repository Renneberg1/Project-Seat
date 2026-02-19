"""Approval queue data models."""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any


class ApprovalAction(str, enum.Enum):
    CREATE_JIRA_ISSUE = "create_jira_issue"
    CREATE_JIRA_VERSION = "create_jira_version"
    UPDATE_JIRA_ISSUE = "update_jira_issue"
    ADD_ISSUE_LINK = "add_issue_link"
    CREATE_CONFLUENCE_PAGE = "create_confluence_page"
    UPDATE_CONFLUENCE_PAGE = "update_confluence_page"


class ApprovalStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    FAILED = "failed"


@dataclass
class ApprovalItem:
    id: int
    project_id: int | None
    action_type: ApprovalAction
    payload: str  # JSON string
    preview: str
    context: str
    status: ApprovalStatus
    result: str | None  # JSON string
    created_at: str
    resolved_at: str | None

    @classmethod
    def from_row(cls, row: Any) -> ApprovalItem:
        return cls(
            id=row["id"],
            project_id=row["project_id"],
            action_type=ApprovalAction(row["action_type"]),
            payload=row["payload"],
            preview=row["preview"],
            context=row["context"],
            status=ApprovalStatus(row["status"]),
            result=row["result"],
            created_at=row["created_at"],
            resolved_at=row["resolved_at"],
        )
