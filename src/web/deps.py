"""Shared web dependencies — extracted to avoid circular imports."""

from __future__ import annotations

from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from src.services.dashboard import DashboardService

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


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
