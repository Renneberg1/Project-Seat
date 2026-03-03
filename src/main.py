"""FastAPI application entry point."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from src.config import settings
from src.database import init_db
from src.engine.orchestrator import Orchestrator
from src.web.routes.approval import router as approval_router
from src.web.routes.phases import router as phases_router
from src.web.routes.project import router as project_router
from src.web.routes.import_project import router as import_router
from src.web.routes.spinup import router as spinup_router
from src.web.routes.transcript import router as transcript_router
from src.web.routes.charter import router as charter_router
from src.web.routes.health_review import router as health_review_router
from src.web.routes.ceo_review import router as ceo_review_router
from src.web.routes.closure import router as closure_router
from src.web.routes.settings import router as settings_router
from src.web.routes.health import router as health_router
from src.web.routes.typeahead import router as typeahead_router
from src.web.routes.zoom import router as zoom_router
from src.web.routes.meetings import router as meetings_router
from src.web.routes.knowledge import router as knowledge_router
from src.services.team_snapshot import snapshot_all_projects

logger = logging.getLogger(__name__)

_STATIC_DIR = Path(__file__).resolve().parent / "web" / "static"

orchestrator = Orchestrator()
orchestrator.register("team_progress_snapshot", snapshot_all_projects, interval_seconds=86400, run_immediately=True)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Startup: initialise the database and start background tasks
    init_db(settings.db_path)
    await orchestrator.start()

    # Fire-and-forget Zoom sync if enabled and authorized
    if settings.zoom.enabled:
        from src.repositories.zoom_repo import ZoomRepository
        _zoom_repo = ZoomRepository(settings.db_path)
        if _zoom_repo.get_config("zoom_refresh_token"):
            async def _zoom_startup() -> None:
                try:
                    from src.services.zoom_ingestion import run_zoom_sync
                    await run_zoom_sync()
                except Exception as exc:
                    logger.warning("Zoom startup sync failed: %s", exc)

            asyncio.create_task(_zoom_startup())
        else:
            logger.info("Zoom enabled but not authorized. Visit /meetings/ to connect.")

    yield
    # Shutdown: stop background tasks
    await orchestrator.stop()


app = FastAPI(title="Project Seat", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
app.include_router(phases_router)
app.include_router(project_router)
app.include_router(spinup_router)
app.include_router(approval_router)
app.include_router(import_router)
app.include_router(transcript_router)
app.include_router(charter_router)
app.include_router(health_review_router)
app.include_router(ceo_review_router)
app.include_router(closure_router)
app.include_router(settings_router)
app.include_router(typeahead_router)
app.include_router(zoom_router)
app.include_router(meetings_router)
app.include_router(knowledge_router)
app.include_router(health_router)


@app.get("/")
async def root() -> RedirectResponse:
    """Redirect root to pipeline view."""
    return RedirectResponse(url="/phases/", status_code=302)
