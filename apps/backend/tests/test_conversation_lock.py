"""Unit tests for advisory-lock deadline polling (Plan 19 §3).

The DB-backed acquire/release behaviour is covered by conversation_db tests.
"""

from __future__ import annotations

import asyncio

from persistence.lock import acquire_with_deadline


class _FakeResult:
    def __init__(self, value: bool) -> None:
        self._value = value

    def scalar(self) -> bool:
        return self._value


class _FakeConnection:
    """Returns a scripted sequence of pg_try_advisory_lock outcomes."""

    def __init__(self, outcomes: list[bool]) -> None:
        self._outcomes = list(outcomes)
        self.execute_calls = 0
        self.commit_calls = 0

    async def execute(self, _statement, _params) -> _FakeResult:
        self.execute_calls += 1
        value = self._outcomes.pop(0) if self._outcomes else False
        return _FakeResult(value)

    async def commit(self) -> None:
        self.commit_calls += 1


class _FakeClock:
    def __init__(self, step: float = 0.05) -> None:
        self._now = 0.0
        self._step = step

    def time(self) -> float:
        return self._now

    def advance(self, amount: float) -> None:
        self._now += amount


def test_acquires_on_first_attempt_without_sleeping() -> None:
    conn = _FakeConnection([True])
    slept: list[float] = []

    async def _sleep(seconds: float) -> None:
        slept.append(seconds)

    async def _run() -> bool:
        return await acquire_with_deadline(
            conn,
            key=1,
            timeout_seconds=1.0,
            poll_interval_seconds=0.05,
            sleep=_sleep,
            monotonic=_FakeClock().time,
        )

    assert asyncio.run(_run()) is True
    assert conn.execute_calls == 1
    assert slept == []


def test_acquires_after_retries() -> None:
    conn = _FakeConnection([False, False, True])
    clock = _FakeClock()

    async def _sleep(seconds: float) -> None:
        clock.advance(seconds)

    async def _run() -> bool:
        return await acquire_with_deadline(
            conn,
            key=1,
            timeout_seconds=1.0,
            poll_interval_seconds=0.05,
            sleep=_sleep,
            monotonic=clock.time,
        )

    assert asyncio.run(_run()) is True
    assert conn.execute_calls == 3


def test_times_out_after_deadline_returns_false() -> None:
    conn = _FakeConnection([False] * 100)
    clock = _FakeClock()

    async def _sleep(seconds: float) -> None:
        clock.advance(seconds)

    async def _run() -> bool:
        return await acquire_with_deadline(
            conn,
            key=1,
            timeout_seconds=0.2,
            poll_interval_seconds=0.05,
            sleep=_sleep,
            monotonic=clock.time,
        )

    assert asyncio.run(_run()) is False
    # Finite polling: stops once the fake clock passes the deadline.
    assert conn.execute_calls >= 2
