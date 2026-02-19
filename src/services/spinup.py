"""Project spin-up service — orchestrates creation of Jira and Confluence artifacts."""

from __future__ import annotations

import json
import logging
import re

from src.config import settings
from src.connectors.confluence import ConfluenceConnector
from src.database import get_db
from src.engine.approval import ApprovalEngine
from src.models.approval import ApprovalAction, ApprovalItem, ApprovalStatus

logger = logging.getLogger(__name__)

# Jira constants (from samples)
PROG_PROJECT_KEY = "PROG"
RISK_PROJECT_KEY = "RISK"
GOAL_ISSUE_TYPE_ID = "10423"

# Confluence template page IDs
CHARTER_TEMPLATE_ID = "3559363918"
XFT_TEMPLATE_ID = "3559363934"

# Sentinel values replaced at execution time with real IDs
_SENTINEL_CHARTER_PAGE_ID = "__CHARTER_PAGE_ID__"
_SENTINEL_GOAL_KEY = "__GOAL_KEY__"


class SpinUpService:
    """Queues all approval items for a project spin-up; executes them on approval."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or settings.db_path
        self._engine = ApprovalEngine(db_path=self._db_path)

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    async def prepare_spinup(self, request) -> list[int]:
        """Queue all spin-up actions for approval. Returns list of item IDs."""
        from src.models.project import SpinUpRequest

        req: SpinUpRequest = request
        project_id = self._create_local_project(req)
        item_ids: list[int] = []

        # 1) Create Goal ticket in PROG
        goal_payload = {
            "project_key": PROG_PROJECT_KEY,
            "issue_type_id": GOAL_ISSUE_TYPE_ID,
            "summary": f"{req.project_name}",
            "fields": {},
        }
        if req.goal_summary:
            goal_payload["fields"]["description"] = {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": req.goal_summary}],
                    }
                ],
            }
        if req.labels:
            goal_payload["fields"]["labels"] = req.labels
        if req.target_date:
            goal_payload["fields"]["duedate"] = req.target_date

        item_ids.append(
            self._engine.propose(
                ApprovalAction.CREATE_JIRA_ISSUE,
                goal_payload,
                preview=f"Create Goal '{req.project_name}' in {PROG_PROJECT_KEY}",
                context="Spin-up step 1: Goal ticket",
                project_id=project_id,
            )
        )

        # 2) Create fix version in RISK
        version_name = req.project_name
        item_ids.append(
            self._engine.propose(
                ApprovalAction.CREATE_JIRA_VERSION,
                {
                    "project_key": RISK_PROJECT_KEY,
                    "name": version_name,
                    "release_date": req.target_date or None,
                },
                preview=f"Create version '{version_name}' in {RISK_PROJECT_KEY}",
                context="Spin-up step 2: RISK fix version",
                project_id=project_id,
            )
        )

        # 3) Create fix version in each team project
        for proj_key in req.team_projects:
            item_ids.append(
                self._engine.propose(
                    ApprovalAction.CREATE_JIRA_VERSION,
                    {
                        "project_key": proj_key,
                        "name": version_name,
                        "release_date": req.target_date or None,
                    },
                    preview=f"Create version '{version_name}' in {proj_key}",
                    context=f"Spin-up step 3: {proj_key} fix version",
                    project_id=project_id,
                )
            )

        # 4) Create Charter page
        charter_body = await self._fetch_template_body(CHARTER_TEMPLATE_ID)
        charter_body = self._replace_placeholders(charter_body, req)
        parent_id = await self._find_projects_releases_page(req)

        item_ids.append(
            self._engine.propose(
                ApprovalAction.CREATE_CONFLUENCE_PAGE,
                {
                    "space_key": req.confluence_space_key,
                    "title": f"{req.project_name} Charter",
                    "body_storage": charter_body,
                    "parent_id": parent_id,
                },
                preview=f"Create Charter page '{req.project_name} Charter'",
                context="Spin-up step 4: Confluence Charter page",
                project_id=project_id,
            )
        )

        # 5) Create XFT page (child of Charter — uses sentinel)
        xft_body = await self._fetch_template_body(XFT_TEMPLATE_ID)
        xft_body = self._replace_placeholders(xft_body, req)

        item_ids.append(
            self._engine.propose(
                ApprovalAction.CREATE_CONFLUENCE_PAGE,
                {
                    "space_key": req.confluence_space_key,
                    "title": f"{req.project_name} XFT",
                    "body_storage": xft_body,
                    "parent_id": _SENTINEL_CHARTER_PAGE_ID,
                },
                preview=f"Create XFT page '{req.project_name} XFT' (child of Charter)",
                context="Spin-up step 5: Confluence XFT page (parent resolved at execution)",
                project_id=project_id,
            )
        )

        # 6) Update Goal description with Confluence links (uses sentinels)
        item_ids.append(
            self._engine.propose(
                ApprovalAction.UPDATE_JIRA_ISSUE,
                {
                    "key": _SENTINEL_GOAL_KEY,
                    "fields": {
                        "description": "__GOAL_DESCRIPTION_PLACEHOLDER__",
                    },
                },
                preview="Update Goal description with Confluence page links",
                context="Spin-up step 6: link Confluence pages in Goal (resolved at execution)",
                project_id=project_id,
            )
        )

        return item_ids

    async def execute_approved_item(self, item_id: int) -> ApprovalItem:
        """Resolve sentinels and execute a single approved item."""
        item = self._engine.get(item_id)
        if item is None:
            raise ValueError(f"Item {item_id} not found")

        # Resolve sentinels before execution
        payload = json.loads(item.payload)
        resolved_payload = self._resolve_sentinels(payload, item.project_id)

        if resolved_payload != payload:
            # Update the payload in the queue before executing
            with get_db(self._db_path) as conn:
                conn.execute(
                    "UPDATE approval_queue SET payload = ? WHERE id = ?",
                    (json.dumps(resolved_payload), item_id),
                )
                conn.commit()

        return await self._engine.approve_and_execute(item_id)

    # ------------------------------------------------------------------
    # Sentinel resolution
    # ------------------------------------------------------------------

    def _resolve_sentinels(self, payload: dict, project_id: int | None) -> dict:
        """Replace sentinel values with actual IDs from earlier executed items."""
        if project_id is None:
            return payload

        payload_str = json.dumps(payload)
        if _SENTINEL_CHARTER_PAGE_ID not in payload_str and _SENTINEL_GOAL_KEY not in payload_str:
            return payload

        # Look up executed items for this project
        executed_items = self._engine.list_all(project_id)

        charter_page_id = None
        xft_page_id = None
        goal_key = None

        for ex_item in executed_items:
            if ex_item.status != ApprovalStatus.EXECUTED or not ex_item.result:
                continue
            result = json.loads(ex_item.result)

            if ex_item.action_type == ApprovalAction.CREATE_JIRA_ISSUE:
                if result.get("key", "").startswith(PROG_PROJECT_KEY):
                    goal_key = result["key"]

            elif ex_item.action_type == ApprovalAction.CREATE_CONFLUENCE_PAGE:
                page_id = str(result.get("id", ""))
                title = result.get("title", "")
                if "Charter" in title and "XFT" not in title:
                    charter_page_id = page_id
                elif "XFT" in title:
                    xft_page_id = page_id

        # Replace sentinels
        if charter_page_id and _SENTINEL_CHARTER_PAGE_ID in payload_str:
            payload_str = payload_str.replace(_SENTINEL_CHARTER_PAGE_ID, charter_page_id)

        if goal_key and _SENTINEL_GOAL_KEY in payload_str:
            payload_str = payload_str.replace(_SENTINEL_GOAL_KEY, goal_key)

        resolved = json.loads(payload_str)

        # Build the real Goal description if this is the update step
        if (
            resolved.get("fields", {}).get("description") == "__GOAL_DESCRIPTION_PLACEHOLDER__"
            and charter_page_id
        ):
            resolved["fields"]["description"] = self._build_goal_description(
                charter_page_id, xft_page_id
            )

        return resolved

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _create_local_project(self, req) -> int:
        """Insert a placeholder project row. Returns the project ID."""
        with get_db(self._db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO projects (jira_goal_key, name, status, pi_version) VALUES (?, ?, ?, ?)",
                ("pending", req.project_name, "spinning_up", req.pi_version or None),
            )
            conn.commit()
            return cursor.lastrowid

    async def _fetch_template_body(self, page_id: str) -> str:
        """Fetch the storage-format body of a Confluence template page."""
        confluence = ConfluenceConnector()
        try:
            page = await confluence.get_page(page_id, expand=["body.storage"])
            return page["body"]["storage"]["value"]
        finally:
            await confluence.close()

    def _replace_placeholders(self, body: str, req) -> str:
        """Replace known template placeholders with project details."""
        replacements = {
            "[Insert project name & release]": req.project_name,
            "[Insert project name]": req.project_name,
            "[Project Name]": req.project_name,
            "[Target Date]": req.target_date or "TBD",
            "[Program]": req.program,
        }
        for placeholder, value in replacements.items():
            body = body.replace(placeholder, value)
        return body

    async def _find_projects_releases_page(self, req) -> str | None:
        """Find the 'Projects/Releases' page under the program page."""
        confluence = ConfluenceConnector()
        try:
            # Search for the program page (e.g. "HOP Program")
            program_pages = await confluence.search_pages(
                req.confluence_space_key, f"{req.program} Program"
            )
            if not program_pages:
                logger.warning("Program page '%s Program' not found", req.program)
                return None

            program_page_id = program_pages[0]["id"]

            # Find "Projects/Releases" child
            children = await confluence.get_page_children(program_page_id)
            for child in children:
                if "Projects" in child.get("title", "") and "Releases" in child.get("title", ""):
                    return child["id"]
                if child.get("title", "").strip() == "Projects/Releases":
                    return child["id"]

            logger.warning("'Projects/Releases' child not found under program page")
            return program_page_id  # Fall back to program page
        finally:
            await confluence.close()

    def _build_goal_description(
        self, charter_id: str, xft_id: str | None
    ) -> dict:
        """Build an ADF document with inlineCard links to Confluence pages."""
        domain = settings.atlassian.domain
        base = f"https://{domain}.atlassian.net/wiki/spaces"

        content = [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Project pages: "},
                    {
                        "type": "inlineCard",
                        "attrs": {
                            "url": f"{base}/HPP/pages/{charter_id}",
                        },
                    },
                ],
            },
        ]

        if xft_id:
            content.append(
                {
                    "type": "paragraph",
                    "content": [
                        {"type": "text", "text": "XFT page: "},
                        {
                            "type": "inlineCard",
                            "attrs": {
                                "url": f"{base}/HPP/pages/{xft_id}",
                            },
                        },
                    ],
                }
            )

        return {
            "type": "doc",
            "version": 1,
            "content": content,
        }
