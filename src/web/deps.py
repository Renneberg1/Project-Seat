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
