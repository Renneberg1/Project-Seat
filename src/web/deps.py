"""Shared web dependencies — extracted to avoid circular imports."""

from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from src.connectors.confluence import ConfluenceConnector
from src.connectors.jira import JiraConnector
from src.engine.approval import ApprovalEngine
from src.services.ceo_review import CeoReviewService
from src.services.charter import CharterService
from src.services.dashboard import DashboardService
from src.services.dhf import DHFService
from src.services.health_review import HealthReviewService
from src.services.import_project import ImportService
from src.services.release import ReleaseService
from src.services.spinup import SpinUpService
from src.services.team_progress import TeamProgressService
from src.services.team_snapshot import TeamSnapshotService
from src.services.project_context import ProjectContextService
from src.services.risk_refinement import RiskRefinementService
from src.services.transcript import TranscriptService
from src.services.transcript_parser import TranscriptParser

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
_STATIC_DIR = Path(__file__).resolve().parent / "static"

# ---------------------------------------------------------------------------
# Static file cache-busting — compute MD5[:8] of each file at import time
# ---------------------------------------------------------------------------


def _compute_static_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    if _STATIC_DIR.is_dir():
        for p in _STATIC_DIR.rglob("*"):
            if p.is_file():
                digest = hashlib.md5(p.read_bytes()).hexdigest()[:8]  # noqa: S324
                rel = p.relative_to(_STATIC_DIR).as_posix()
                versions[rel] = digest
    return versions


static_versions: dict[str, str] = _compute_static_versions()

templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
templates.env.globals["static_versions"] = static_versions


def get_nav_context(request: Request) -> dict:
    """Build template context for the two-tier nav bar.

    Returns a dict with:
    - nav_projects: all tracked projects (for the dropdown)
    - selected_project_id: currently selected project ID (from URL or cookie), or None
    """
    service = DashboardService()
    nav_projects = service.list_projects()

    # Try URL path param first, then cookie
    selected_project_id: int | None = None
    path_id = request.path_params.get("id")
    if path_id is not None:
        try:
            selected_project_id = int(path_id)
        except (ValueError, TypeError):
            pass

    if selected_project_id is None:
        cookie_val = request.cookies.get("seat_selected_project")
        if cookie_val:
            try:
                selected_project_id = int(cookie_val)
            except (ValueError, TypeError):
                pass

    return {
        "nav_projects": nav_projects,
        "selected_project_id": selected_project_id,
    }


def render_project_page(
    request: Request, template: str, context: dict, project_id: int,
) -> "HTMLResponse":
    """Render a template with nav context and set the project cookie."""
    from fastapi.responses import HTMLResponse

    nav = get_nav_context(request)
    nav["selected_project_id"] = project_id
    response = templates.TemplateResponse(request, template, {**context, **nav})
    response.set_cookie("seat_selected_project", str(project_id), max_age=60 * 60 * 24 * 30)
    return response


def collect_qa_pairs(form: dict) -> list[dict[str, str]]:
    """Extract numbered question/answer pairs from a form dict.

    Looks for ``question_0``, ``answer_0``, ``question_1``, ``answer_1``, etc.
    """
    pairs: list[dict[str, str]] = []
    i = 0
    while True:
        q = form.get(f"question_{i}")
        if q is None:
            break
        pairs.append({"question": str(q), "answer": str(form.get(f"answer_{i}") or "")})
        i += 1
    return pairs


# ---------------------------------------------------------------------------
# FastAPI dependency injection factories
# ---------------------------------------------------------------------------


def get_dashboard_service() -> DashboardService:
    return DashboardService()


def get_approval_engine() -> ApprovalEngine:
    return ApprovalEngine()


def get_spinup_service() -> SpinUpService:
    return SpinUpService()


def get_import_service() -> ImportService:
    return ImportService()


def get_dhf_service() -> DHFService:
    return DHFService()


def get_release_service() -> ReleaseService:
    return ReleaseService()


def get_transcript_service() -> TranscriptService:
    return TranscriptService()


def get_transcript_parser() -> TranscriptParser:
    return TranscriptParser()


def get_charter_service() -> CharterService:
    return CharterService()


def get_health_review_service() -> HealthReviewService:
    return HealthReviewService()


def get_ceo_review_service() -> CeoReviewService:
    return CeoReviewService()


def get_team_progress_service() -> TeamProgressService:
    return TeamProgressService()


def get_team_snapshot_service() -> TeamSnapshotService:
    return TeamSnapshotService()


def get_jira_connector() -> JiraConnector:
    return JiraConnector()


def get_project_context_service() -> ProjectContextService:
    return ProjectContextService()


def get_risk_refinement_service() -> RiskRefinementService:
    return RiskRefinementService()


def get_confluence_connector() -> ConfluenceConnector:
    return ConfluenceConnector()
