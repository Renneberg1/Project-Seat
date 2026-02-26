"""Tests for the task orchestrator — register, start, stop cycle."""

from __future__ import annotations

import asyncio

import pytest

from src.engine.orchestrator import Orchestrator


async def test_register_and_start_stop_completes_without_error():
    """An orchestrator with no tasks should start and stop cleanly."""
    orch = Orchestrator()
    await orch.start()
    await orch.stop()


async def test_registered_task_executes_at_least_once():
    """A task with a short interval should fire within the test window."""
    call_count = 0

    async def _task():
        nonlocal call_count
        call_count += 1

    orch = Orchestrator()
    orch.register("counter", _task, interval_seconds=0)  # 0 = immediate re-run
    await orch.start()
    await asyncio.sleep(0.05)  # Give it time to fire
    await orch.stop()

    assert call_count >= 1


async def test_disabled_task_does_not_execute():
    """A task with enabled=False should never run."""
    ran = False

    async def _task():
        nonlocal ran
        ran = True

    orch = Orchestrator()
    orch.register("noop", _task, interval_seconds=0, enabled=False)
    await orch.start()
    await asyncio.sleep(0.05)
    await orch.stop()

    assert ran is False


async def test_task_exception_does_not_crash_orchestrator():
    """A failing task should be logged but not stop the orchestrator loop."""
    good_count = 0

    async def _bad_task():
        raise RuntimeError("boom")

    async def _good_task():
        nonlocal good_count
        good_count += 1

    orch = Orchestrator()
    orch.register("bad", _bad_task, interval_seconds=0)
    orch.register("good", _good_task, interval_seconds=0)
    await orch.start()
    await asyncio.sleep(0.05)
    await orch.stop()

    assert good_count >= 1


async def test_stop_cancels_running_tasks():
    """After stop(), the internal task list should be cleared."""
    orch = Orchestrator()

    async def _noop():
        pass

    orch.register("noop", _noop, interval_seconds=1)
    await orch.start()
    assert len(orch._running) == 1

    await orch.stop()
    assert len(orch._running) == 0


async def test_run_immediately_fires_before_first_sleep():
    """A task with run_immediately=True should execute before the first sleep interval."""
    call_count = 0

    async def _task():
        nonlocal call_count
        call_count += 1

    orch = Orchestrator()
    # Large interval so only the immediate run fires within the test window
    orch.register("immediate", _task, interval_seconds=9999, run_immediately=True)
    await orch.start()
    await asyncio.sleep(0.05)
    await orch.stop()

    assert call_count == 1


async def test_run_immediately_false_does_not_fire_before_sleep():
    """A task with run_immediately=False should not fire before the first sleep."""
    call_count = 0

    async def _task():
        nonlocal call_count
        call_count += 1

    orch = Orchestrator()
    orch.register("delayed", _task, interval_seconds=9999, run_immediately=False)
    await orch.start()
    await asyncio.sleep(0.05)
    await orch.stop()

    assert call_count == 0


async def test_run_immediately_exception_does_not_crash_loop():
    """If run_immediately task raises, the loop should still continue."""
    call_count = 0

    async def _failing_then_ok():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("initial run failed")

    orch = Orchestrator()
    orch.register("retry", _failing_then_ok, interval_seconds=0, run_immediately=True)
    await orch.start()
    await asyncio.sleep(0.05)
    await orch.stop()

    # Should have run at least twice: immediate (failed) + at least one loop iteration
    assert call_count >= 2
