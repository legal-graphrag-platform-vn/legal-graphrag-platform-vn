from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable

import pytest

from services.errors import BackendRetrievalClosedError, BackendRetrievalTimeoutError
from services.retrieval_runner import BoundedRetrievalRunner


def test_runner_executes_sync_work_off_the_event_loop_thread() -> None:
    async def scenario() -> None:
        event_loop_thread = threading.get_ident()
        runner = _runner()
        try:
            worker_thread = await runner.run(threading.get_ident)
        finally:
            await runner.aclose()
        assert worker_thread != event_loop_thread

    asyncio.run(scenario())


def test_runner_enforces_application_concurrency_limit() -> None:
    async def scenario() -> None:
        release = threading.Event()
        lock = threading.Lock()
        active = 0
        peak = 0

        def work() -> int:
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            release.wait(timeout=2)
            with lock:
                active -= 1
            return 1

        runner = _runner(max_concurrency=2, timeout_seconds=2)
        tasks = [asyncio.create_task(runner.run(work)) for _ in range(4)]
        try:
            await _wait_until(lambda: runner.active_count == 2)
            assert peak == 2
            release.set()
            assert await asyncio.gather(*tasks) == [1, 1, 1, 1]
            assert peak == 2
        finally:
            release.set()
            await runner.aclose()

    asyncio.run(scenario())


def test_timeout_stops_waiting_but_running_worker_continues() -> None:
    async def scenario() -> None:
        release = threading.Event()
        finished = threading.Event()

        def work() -> None:
            release.wait(timeout=2)
            finished.set()

        runner = _runner(timeout_seconds=0.05)
        try:
            with pytest.raises(BackendRetrievalTimeoutError):
                await runner.run(work)
            assert runner.active_count == 1
            assert not finished.is_set()
            release.set()
            await _wait_until(lambda: runner.active_count == 0)
            assert finished.is_set()
        finally:
            release.set()
            await runner.aclose()

    asyncio.run(scenario())


def test_queued_timeout_never_starts_second_job() -> None:
    async def scenario() -> None:
        release = threading.Event()
        first_started = threading.Event()
        second_started = threading.Event()

        def first() -> None:
            first_started.set()
            release.wait(timeout=2)

        runner = _runner(max_concurrency=1, timeout_seconds=0.1)
        first_task = asyncio.create_task(runner.run(first))
        await _wait_until(first_started.is_set)
        try:
            with pytest.raises(BackendRetrievalTimeoutError):
                await runner.run(second_started.set)
            assert not second_started.is_set()
        finally:
            release.set()
            with pytest.raises(BackendRetrievalTimeoutError):
                await first_task
            await _wait_until(lambda: runner.active_count == 0)
            await runner.aclose()

    asyncio.run(scenario())


def test_client_cancellation_does_not_retry_running_work() -> None:
    async def scenario() -> None:
        release = threading.Event()
        started = threading.Event()
        calls = 0

        def work() -> None:
            nonlocal calls
            calls += 1
            started.set()
            release.wait(timeout=2)

        runner = _runner(timeout_seconds=2)
        task = asyncio.create_task(runner.run(work))
        await _wait_until(started.is_set)
        task.cancel()
        try:
            with pytest.raises(asyncio.CancelledError):
                await task
            assert calls == 1
            assert runner.active_count == 1
        finally:
            release.set()
            await _wait_until(lambda: runner.active_count == 0)
            await runner.aclose()

    asyncio.run(scenario())


def test_closed_runner_rejects_new_work_and_close_is_idempotent() -> None:
    async def scenario() -> None:
        runner = _runner()
        assert await runner.aclose() == 0
        assert await runner.aclose() == 0
        with pytest.raises(BackendRetrievalClosedError):
            await runner.run(lambda: None)

    asyncio.run(scenario())


def _runner(
    *,
    max_concurrency: int = 1,
    timeout_seconds: float = 1,
) -> BoundedRetrievalRunner:
    return BoundedRetrievalRunner(
        max_concurrency=max_concurrency,
        timeout_seconds=timeout_seconds,
        shutdown_grace_seconds=0.1,
    )


async def _wait_until(
    predicate: Callable[[], bool],
    *,
    timeout: float = 1,
) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("Condition was not satisfied before timeout")
        await asyncio.sleep(0.005)
