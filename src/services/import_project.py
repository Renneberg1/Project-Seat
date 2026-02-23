"""Import existing project service — fetch from Jira, save to local DB."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from src.config import settings
from src.connectors.jira import JiraConnector
from src.database import get_db

logger = logging.getLogger(__name__)

# Regex to extract page IDs from Confluence URLs
_CONFLUENCE_PAGE_URL_RE = re.compile(
    r"https?://[^/]+/wiki/spaces/[^/]+/pages/(\d+)"
)


@dataclass
class DetectedPage:
    """A Confluence page detected from a Jira issue description."""

    page_id: str
    url: str
    slug: str  # URL-decoded last path segment (e.g. "V2+Drop+2+-+FPL" -> "V2 Drop 2 - FPL")


@dataclass
class ImportPreview:
    """Preview data for an import confirmation form."""

    goal_key: str
    goal_summary: str
    detected_pages: list[DetectedPage] = field(default_factory=list)
    charter_id: str | None = None
    xft_id: str | None = None
    detected_teams: dict[str, str] = field(default_factory=dict)


def extract_confluence_page_ids(adf: dict | None) -> list[DetectedPage]:
    """Recursively walk ADF content and extract Confluence page IDs from inlineCard nodes."""
    if adf is None:
        return []

    pages: list[DetectedPage] = []

    def _walk(node: dict | list) -> None:
        if isinstance(node, list):
            for item in node:
                _walk(item)
            return

        if not isinstance(node, dict):
            return

        # Check for inlineCard with Confluence URL
        if node.get("type") == "inlineCard":
            url = node.get("attrs", {}).get("url", "")
            match = _CONFLUENCE_PAGE_URL_RE.search(url)
            if match:
                page_id = match.group(1)
                # Extract slug from URL (last path segment)
                slug_raw = url.rsplit("/", 1)[-1] if "/" in url else ""
                slug = slug_raw.replace("+", " ")
                pages.append(DetectedPage(page_id=page_id, url=url, slug=slug))

        # Recurse into child content
        for key in ("content", "value"):
            if key in node:
                _walk(node[key])

    _walk(adf)
    return pages


def guess_charter_xft(pages: list[DetectedPage]) -> tuple[str | None, str | None]:
    """Guess which detected page is the Charter and which is the XFT.

    Heuristic:
    - Slug containing "FPL" or "Charter" -> Charter
    - Slug containing "Scope" or "XFT" -> XFT
    - Fallback: if exactly 2 pages, first=Charter, second=XFT
    """
    charter_id: str | None = None
    xft_id: str | None = None

    charter_patterns = re.compile(r"(?i)\b(FPL|Charter)\b")
    xft_patterns = re.compile(r"(?i)\b(Scope|XFT)\b")

    for page in pages:
        if charter_id is None and charter_patterns.search(page.slug):
            charter_id = page.page_id
        elif xft_id is None and xft_patterns.search(page.slug):
            xft_id = page.page_id

    # Fallback: 2 pages, first = Charter, second = XFT
    if charter_id is None and xft_id is None and len(pages) == 2:
        charter_id = pages[0].page_id
        xft_id = pages[1].page_id

    return charter_id, xft_id


def _detect_team_projects(
    initiatives: list[dict],
    exclude: set[str] | None = None,
) -> dict[str, str]:
    """Extract unique team project keys and their fix version names from child initiatives.

    Returns ``{project_key: version_name}`` where *version_name* is the first
    fixVersion found on any initiative in that project, or an empty string if none.
    """
    if exclude is None:
        exclude = {"PROG", "RISK"}

    teams: dict[str, str] = {}
    for issue in initiatives:
        fields = issue.get("fields", {})
        proj_key = fields.get("project", {}).get("key", "")
        if not proj_key or proj_key in exclude:
            continue
        if proj_key in teams:
            continue  # keep first-seen version
        fix_versions = fields.get("fixVersions") or []
        version_name = fix_versions[0]["name"] if fix_versions else ""
        teams[proj_key] = version_name
    return teams


class ImportService:
    """Fetch an existing Jira Goal and import it into the local DB."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or settings.db_path

    async def fetch_preview(self, goal_key: str) -> ImportPreview:
        """Fetch a PROG Goal from Jira and build an import preview."""
        jira = JiraConnector()
        try:
            issue = await jira.get_issue(
                goal_key,
                fields=["summary", "description"],
            )
            # Fetch child initiatives to detect team projects
            child_issues = await jira.search(
                f'parent = {goal_key} AND project not in (PROG, RISK)',
                fields=["project", "fixVersions"],
            )
        finally:
            await jira.close()

        summary = issue.get("fields", {}).get("summary", goal_key)
        description_adf = issue.get("fields", {}).get("description")

        pages = extract_confluence_page_ids(description_adf)
        charter_id, xft_id = guess_charter_xft(pages)
        detected_teams = _detect_team_projects(child_issues)

        return ImportPreview(
            goal_key=goal_key,
            goal_summary=summary,
            detected_pages=pages,
            charter_id=charter_id,
            xft_id=xft_id,
            detected_teams=detected_teams,
        )

    def save_project(
        self,
        goal_key: str,
        name: str,
        charter_id: str | None = None,
        xft_id: str | None = None,
        pi_version: str | None = None,
        team_projects: dict[str, str] | None = None,
    ) -> int:
        """Insert the imported project into the local DB. Returns the project ID.

        Raises ValueError if a project with the same goal_key already exists.
        """
        import json

        with get_db(self._db_path) as conn:
            existing = conn.execute(
                "SELECT id FROM projects WHERE jira_goal_key = ?",
                (goal_key,),
            ).fetchone()
            if existing:
                raise ValueError(f"Project with goal key '{goal_key}' already exists (id={existing['id']})")

            cursor = conn.execute(
                "INSERT INTO projects (jira_goal_key, name, confluence_charter_id, confluence_xft_id, status, phase, pi_version, team_projects) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (goal_key, name, charter_id or None, xft_id or None, "active", "planning", pi_version, json.dumps(team_projects) if team_projects else None),
            )
            conn.commit()
            return cursor.lastrowid

    def delete_project(self, project_id: int) -> None:
        """Remove a project and all related data from the local DB.

        Cascades to: approval_queue, approval_log, transcript_cache.
        Does NOT touch Jira or Confluence.
        """
        with get_db(self._db_path) as conn:
            conn.execute("DELETE FROM approval_queue WHERE project_id = ?", (project_id,))
            conn.execute("DELETE FROM approval_log WHERE project_id = ?", (project_id,))
            conn.execute("DELETE FROM transcript_cache WHERE project_id = ?", (project_id,))
            conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            conn.commit()
