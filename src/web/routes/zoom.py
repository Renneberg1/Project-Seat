"""Zoom OAuth routes and backward-compat redirects.

Inbox, triage, sync, dismiss, retry, and reanalyse routes have moved to ``meetings.py``.
"""

from __future__ import annotations

import logging
import secrets
import time
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse

import src.config
from src.repositories.zoom_repo import ZoomRepository
from src.web.deps import get_zoom_repo

logger = logging.getLogger(__name__)

router = APIRouter(tags=["zoom"])


# ------------------------------------------------------------------
# Backward-compat redirects
# ------------------------------------------------------------------

@router.get("/zoom/inbox")
async def zoom_inbox_redirect() -> RedirectResponse:
    """Redirect old Zoom Inbox URL to unified Meetings page."""
    return RedirectResponse(url="/meetings/", status_code=302)


@router.get("/zoom/triage")
async def zoom_triage_redirect() -> RedirectResponse:
    """Redirect old Zoom Triage URL to unified Meetings page."""
    return RedirectResponse(url="/meetings/?assigned=false", status_code=302)


# ------------------------------------------------------------------
# OAuth authorization code flow
# ------------------------------------------------------------------

_OAUTH_STATE_TTL = 600  # 10 minutes


@router.get("/zoom/authorize")
async def zoom_authorize(
    repo: ZoomRepository = Depends(get_zoom_repo),
) -> RedirectResponse:
    """Redirect the user to Zoom's consent screen."""
    state = secrets.token_hex(16)
    repo.set_config("zoom_oauth_state", f"{state}:{int(time.time())}")

    zoom = src.config.settings.zoom
    params = urlencode({
        "client_id": zoom.client_id,
        "redirect_uri": zoom.redirect_uri,
        "response_type": "code",
        "state": state,
    })
    return RedirectResponse(url=f"https://zoom.us/oauth/authorize?{params}", status_code=302)


@router.get("/zoom/callback")
async def zoom_callback(
    code: str = Query(...),
    state: str = Query(...),
    repo: ZoomRepository = Depends(get_zoom_repo),
) -> RedirectResponse:
    """Handle the OAuth callback — exchange code for tokens."""
    # Validate state
    stored = repo.get_config("zoom_oauth_state")
    if not stored:
        return RedirectResponse(url="/meetings/?error=missing_state", status_code=302)

    parts = stored.split(":", 1)
    if len(parts) != 2:
        repo.delete_config("zoom_oauth_state")
        return RedirectResponse(url="/meetings/?error=invalid_state", status_code=302)

    stored_state, stored_ts = parts[0], int(parts[1])
    if state != stored_state:
        repo.delete_config("zoom_oauth_state")
        return RedirectResponse(url="/meetings/?error=state_mismatch", status_code=302)

    if int(time.time()) - stored_ts > _OAUTH_STATE_TTL:
        repo.delete_config("zoom_oauth_state")
        return RedirectResponse(url="/meetings/?error=state_expired", status_code=302)

    # Exchange authorization code for tokens
    zoom = src.config.settings.zoom
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            "https://zoom.us/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": zoom.redirect_uri,
            },
            auth=(zoom.client_id, zoom.client_secret),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

    if resp.status_code != 200:
        logger.error("Zoom OAuth code exchange failed: %s", resp.text[:500])
        repo.delete_config("zoom_oauth_state")
        return RedirectResponse(url="/meetings/?error=token_exchange_failed", status_code=302)

    data = resp.json()
    refresh_token = data.get("refresh_token")
    if not refresh_token:
        logger.error("Zoom OAuth response missing refresh_token")
        repo.delete_config("zoom_oauth_state")
        return RedirectResponse(url="/meetings/?error=no_refresh_token", status_code=302)

    repo.set_config("zoom_refresh_token", refresh_token)
    repo.delete_config("zoom_oauth_state")

    logger.info("Zoom OAuth authorization complete — refresh token stored")
    return RedirectResponse(url="/meetings/?connected=1", status_code=302)
