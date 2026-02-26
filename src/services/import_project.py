"""Import existing project service — fetch from Jira, save to local DB."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from src.config import settings
from src.connectors.jira import JiraConnector

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
    detected_teams: list[list[str]] = field(default_factory=list)
    ceo_review_id: str | None = None


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
) -> list[list[str]]:
    """Extract unique (project_key, version_name) pairs from child initiatives.

    Returns ``[[project_key, version_name], ...]``.  A project key may appear
    multiple times with different versions.  Duplicates are suppressed.
    """
    if exclude is None:
        exclude = {"PROG", "RISK"}

    seen: set[tuple[str, str]] = set()
    teams: list[list[str]] = []
    for issue in initiatives:
        fields = issue.get("fields", {})
        proj_key = fields.get("project", {}).get("key", "")
        if not proj_key or proj_key in exclude:
            continue
        fix_versions = fields.get("fixVersions") or []
        version_name = fix_versions[0]["name"] if fix_versions else ""
        pair = (proj_key, version_name)
        if pair not in seen:
            seen.add(pair)
            teams.append([proj_key, version_name])
    return teams


class ImportService:
    """Fetch an existing Jira Goal and import it into the local DB."""

    def __init__(
        self,
        db_path: str | None = None,
        project_repo: "ProjectRepository | None" = None,
    ) -> None:
        self._db_path = db_path or settings.db_path

        from src.repositories.project_repo import ProjectRepository
        self._repo = project_repo or ProjectRepository(self._db_path)

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

        # Try to discover CEO Review page from Charter ancestors
        ceo_review_id = None
        if charter_id:
            ceo_review_id = await self._discover_ceo_review_page(charter_id)

        return ImportPreview(
            goal_key=goal_key,
            goal_summary=summary,
            detected_pages=pages,
            charter_id=charter_id,
            xft_id=xft_id,
            detected_teams=detected_teams,
            ceo_review_id=ceo_review_id,
        )

    async def _discover_ceo_review_page(self, charter_id: str) -> str | None:
        """Walk Charter ancestors to find sibling 'CEO Review' page."""
        from src.connectors.confluence import ConfluenceConnector

        confluence = ConfluenceConnector()
        try:
            page = await confluence.get_page(charter_id, expand=["ancestors"])
            ancestors = page.get("ancestors", [])
            if not ancestors:
                return None

            # Program page is typically the grandparent of Charter
            program_id = None
            if len(ancestors) >= 2:
                program_id = str(ancestors[-2]["id"])
            elif len(ancestors) >= 1:
                program_id = str(ancestors[-1]["id"])

            if not program_id:
                return None

            children = await confluence.get_child_pages_v2(program_id)
            for child in children:
                if "CEO Review" in child.get("title", ""):
                    return str(child["id"])
            return None
        except Exception as exc:
            logger.warning("Import: failed to discover CEO Review page: %s", exc)
            return None
        finally:
            await confluence.close()

    def save_project(
        self,
        goal_key: str,
        name: str,
        charter_id: str | None = None,
        xft_id: str | None = None,
        pi_version: str | None = None,
        team_projects: list[list[str]] | None = None,
        jira_plan_url: str | None = None,
        ceo_review_id: str | None = None,
    ) -> int:
        """Insert the imported project into the local DB. Returns the project ID.

        Raises ValueError if a project with the same goal_key already exists.
        """
        existing_id = self._repo.exists_by_goal_key(goal_key)
        if existing_id is not None:
            raise ValueError(f"Project with goal key '{goal_key}' already exists (id={existing_id})")

        return self._repo.create(
            jira_goal_key=goal_key,
            name=name,
            confluence_charter_id=charter_id or None,
            confluence_xft_id=xft_id or None,
            status="active",
            phase="planning",
            pi_version=pi_version,
            team_projects=team_projects or None,
            jira_plan_url=jira_plan_url or None,
            confluence_ceo_review_id=ceo_review_id or None,
        )

    def delete_project(self, project_id: int) -> None:
        """Remove a project and all related data from the local DB.

        All child rows are removed automatically via ON DELETE CASCADE.
        Does NOT touch Jira or Confluence.
        """
        self._repo.delete(project_id)
