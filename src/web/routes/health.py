"""API health check endpoint."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from src.config import settings
from src.connectors.confluence import ConfluenceConnector
from src.connectors.jira import JiraConnector
from src.database import get_db
from src.web.deps import get_confluence_connector, get_jira_connector

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/api/health")
async def health_check(
    jira: JiraConnector = Depends(get_jira_connector),
    confluence: ConfluenceConnector = Depends(get_confluence_connector),
) -> JSONResponse:
    """Return connectivity status for DB, Jira, and Confluence.

    200 if all pass, 503 if any fail.
    """
    results: dict[str, bool] = {"db": False, "jira": False, "confluence": False}

    # DB check (direct get_db call — pragmatic exception for raw SELECT 1 ping)
    try:
        with get_db(settings.db_path) as conn:
            conn.execute("SELECT 1")
        results["db"] = True
    except Exception:
        logger.warning("Health check: DB unreachable", exc_info=True)

    # Jira check
    try:
        await jira.get_myself()
        results["jira"] = True
    except Exception:
        logger.warning("Health check: Jira unreachable", exc_info=True)
    finally:
        await jira.close()

    # Confluence check
    try:
        await confluence.get_current_user()
        results["confluence"] = True
    except Exception:
        logger.warning("Health check: Confluence unreachable", exc_info=True)
    finally:
        await confluence.close()

    all_ok = all(results.values())
    status = "ok" if all_ok else "degraded"
    status_code = 200 if all_ok else 503

    return JSONResponse(
        content={"status": status, **results},
        status_code=status_code,
    )
