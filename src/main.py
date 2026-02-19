"""FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from src.config import settings
from src.database import init_db
from src.web.deps import templates
from src.web.routes.approval import router as approval_router
from src.web.routes.spinup import router as spinup_router

_STATIC_DIR = Path(__file__).resolve().parent / "web" / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    # Startup: initialise the database
    init_db(settings.db_path)
    yield
    # Shutdown: nothing to clean up yet (connectors are created per-request)


app = FastAPI(title="Project Seat", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
app.include_router(spinup_router)
app.include_router(approval_router)


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "dashboard.html")
