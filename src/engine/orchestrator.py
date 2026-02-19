"""Task orchestrator — runs periodic background tasks."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)


@dataclass
class ScheduledTask:
    name: str
    fn: Callable[[], Awaitable[None]]
    interval_seconds: int
    enabled: bool = True


class Orchestrator:
    """Register and run periodic async tasks alongside the FastAPI server."""

    def __init__(self) -> None:
        self._tasks: list[ScheduledTask] = []
        self._running: list[asyncio.Task] = []

    def register(
        self,
        name: str,
        fn: Callable[[], Awaitable[None]],
        interval_seconds: int,
        enabled: bool = True,
    ) -> None:
        self._tasks.append(ScheduledTask(name, fn, interval_seconds, enabled))

    async def start(self) -> None:
        for task in self._tasks:
            if task.enabled:
                self._running.append(asyncio.create_task(self._run_loop(task)))
                logger.info(
                    "Orchestrator: started task '%s' (every %ds)",
                    task.name,
                    task.interval_seconds,
                )

    async def stop(self) -> None:
        for t in self._running:
            t.cancel()
        await asyncio.gather(*self._running, return_exceptions=True)
        self._running.clear()
        logger.info("Orchestrator: all tasks stopped")

    async def _run_loop(self, task: ScheduledTask) -> None:
        while True:
            await asyncio.sleep(task.interval_seconds)
            try:
                await task.fn()
            except Exception:
                logger.exception("Orchestrator: task '%s' failed", task.name)
