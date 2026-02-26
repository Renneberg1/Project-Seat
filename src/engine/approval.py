"""Approval engine — gates every write action behind explicit user approval."""

from __future__ import annotations

import json
import logging

from src.config import settings
from src.connectors.confluence import ConfluenceConnector
from src.connectors.jira import JiraConnector
from src.models.approval import ApprovalAction, ApprovalItem, ApprovalStatus

logger = logging.getLogger(__name__)


class ApprovalEngine:
    """Manages the approval queue: propose, review, execute, audit."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or settings.db_path

        from src.repositories.approval_repo import ApprovalRepository
        self._repo = ApprovalRepository(self._db_path)

    # ------------------------------------------------------------------
    # Queue operations (synchronous — SQLite is fast)
    # ------------------------------------------------------------------

    def propose(
        self,
        action_type: ApprovalAction,
        payload: dict,
        preview: str,
        context: str = "",
        project_id: int | None = None,
    ) -> int:
        """Add a proposed action to the approval queue. Returns the item ID."""
        return self._repo.propose(action_type, payload, preview, context, project_id)

    def list_pending(self, project_id: int | None = None) -> list[ApprovalItem]:
        """Return all pending approval items, optionally filtered by project."""
        return self._repo.list_by_status(ApprovalStatus.PENDING, project_id)

    def list_all(self, project_id: int | None = None) -> list[ApprovalItem]:
        """Return all approval items, optionally filtered by project."""
        return self._repo.list_all(project_id)

    def get(self, item_id: int) -> ApprovalItem | None:
        """Fetch a single approval item by ID."""
        return self._repo.get(item_id)

    def reject(self, item_id: int) -> ApprovalItem | None:
        """Mark an item as rejected."""
        self._repo.update_status(item_id, ApprovalStatus.REJECTED)
        return self.get(item_id)

    def retry(self, item_id: int) -> ApprovalItem | None:
        """Reset a failed item back to pending so it can be re-approved."""
        item = self.get(item_id)
        if item is None:
            return None
        if item.status != ApprovalStatus.FAILED:
            raise ValueError(f"Item {item_id} is {item.status.value}, not failed")
        self._repo.reset_to_pending(item_id)
        return self.get(item_id)

    # ------------------------------------------------------------------
    # Execution (async — makes HTTP calls)
    # ------------------------------------------------------------------

    async def approve_and_execute(self, item_id: int) -> ApprovalItem:
        """Approve an item, execute the action, and log the result."""
        item = self.get(item_id)
        if item is None:
            raise ValueError(f"Approval item {item_id} not found")
        if item.status != ApprovalStatus.PENDING:
            raise ValueError(f"Item {item_id} is {item.status.value}, not pending")

        # Mark approved
        self._repo.mark_approved(item_id)

        # Execute
        payload = json.loads(item.payload)
        try:
            result = await self._execute(item.action_type, payload)
            result_json = json.dumps(result)
            final_status = ApprovalStatus.EXECUTED
            logger.info(
                "Approval item %d executed: %s — result: %s",
                item_id, item.action_type.value, result_json,
            )
        except Exception as exc:
            logger.exception("Failed to execute approval item %d", item_id)
            result_json = json.dumps({"error": str(exc)})
            final_status = ApprovalStatus.FAILED

        # Update queue row
        self._repo.set_result(item_id, final_status, result_json)

        # Audit trail
        updated = self.get(item_id)
        self._log_to_audit(updated, result_json)
        return updated

    async def _execute(self, action_type: ApprovalAction, payload: dict) -> dict:
        """Dispatch an approved action to the appropriate connector."""
        if action_type == ApprovalAction.CREATE_JIRA_ISSUE:
            jira = JiraConnector()
            try:
                result = await jira.create_issue(
                    project_key=payload["project_key"],
                    issue_type_id=payload["issue_type_id"],
                    summary=payload["summary"],
                    fields=payload.get("fields"),
                )
                return result
            finally:
                await jira.close()

        elif action_type == ApprovalAction.CREATE_JIRA_VERSION:
            jira = JiraConnector()
            try:
                result = await jira.create_version(
                    project_key=payload["project_key"],
                    name=payload["name"],
                    release_date=payload.get("release_date"),
                    description=payload.get("description"),
                )
                return result
            finally:
                await jira.close()

        elif action_type == ApprovalAction.UPDATE_JIRA_ISSUE:
            jira = JiraConnector()
            try:
                await jira.update_issue(
                    key=payload["key"],
                    fields=payload["fields"],
                )
                return {"key": payload["key"], "updated": True}
            finally:
                await jira.close()

        elif action_type == ApprovalAction.ADD_ISSUE_LINK:
            jira = JiraConnector()
            try:
                await jira.add_issue_link(
                    outward_key=payload["outward_key"],
                    inward_key=payload["inward_key"],
                    link_type=payload.get("link_type", "Relates"),
                )
                return {"linked": True}
            finally:
                await jira.close()

        elif action_type == ApprovalAction.CREATE_CONFLUENCE_PAGE:
            confluence = ConfluenceConnector()
            try:
                result = await confluence.create_page(
                    space_key=payload["space_key"],
                    title=payload["title"],
                    body_storage=payload["body_storage"],
                    parent_id=payload.get("parent_id"),
                )
                return result
            finally:
                await confluence.close()

        elif action_type == ApprovalAction.UPDATE_CONFLUENCE_PAGE:
            confluence = ConfluenceConnector()
            try:
                page = await confluence.get_page(
                    payload["page_id"], expand=["version", "body.storage"]
                )
                current_version = page["version"]["number"]
                title = payload.get("title") or page.get("title", "Untitled")
                current_body = (
                    page.get("body", {}).get("storage", {}).get("value", "")
                )

                if payload.get("section_replace_mode"):
                    # Section replace mode: swap one section's content in-place
                    from src.engine.charter_storage_utils import replace_section_content

                    new_body = replace_section_content(
                        current_body,
                        payload["section_name"],
                        payload["new_content"],
                        raw_xhtml=payload.get("raw_xhtml", False),
                    )
                elif payload.get("append_mode"):
                    # Append mode: fetch current body and append new content
                    new_body = current_body + payload["append_content"]
                else:
                    new_body = payload["body_storage"]

                update_body = {
                    "version": {"number": current_version + 1},
                    "title": title,
                    "type": "page",
                    "body": {
                        "storage": {
                            "value": new_body,
                            "representation": "storage",
                        }
                    },
                }
                result = await confluence.put(
                    f"/content/{payload['page_id']}", json_body=update_body
                )
                return result
            finally:
                await confluence.close()

        else:
            raise ValueError(f"Unknown action type: {action_type}")

    # ------------------------------------------------------------------
    # Audit trail
    # ------------------------------------------------------------------

    def _log_to_audit(self, item: ApprovalItem, result_json: str) -> None:
        """Write an entry to the immutable approval_log table."""
        self._repo.log_audit(item, result_json)
