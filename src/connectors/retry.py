"""Shared retry/backoff constants and helpers for all connectors."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

MAX_RETRIES = 3
BACKOFF_BASE = 1.0  # seconds
RATE_LIMIT_STATUS = 429


async def backoff_sleep(attempt: int, base: float = BACKOFF_BASE) -> None:
    """Sleep with exponential backoff: base * 2^attempt seconds."""
    await asyncio.sleep(base * (2 ** attempt))


def retry_after_or_backoff(
    headers: "Mapping[str, str]",
    attempt: int,
    base: float = BACKOFF_BASE,
) -> float:
    """Parse Retry-After header, falling back to exponential backoff.

    Accepts any Mapping (including httpx.Headers which lowercases keys).
    """
    # httpx.Headers lowercases keys; try both forms
    val = headers.get("Retry-After") or headers.get("retry-after")
    if val is not None:
        return float(val)
    return base * (2 ** attempt)
