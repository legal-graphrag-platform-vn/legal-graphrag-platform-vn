from __future__ import annotations

import json
from pathlib import Path

import pytest

from experiments.luatvietnam_crawler.errors import SafetyPolicyError
from experiments.luatvietnam_crawler.safety import RequestSafetyPolicy, RunLock


class MutableClock:
    def __init__(self, value: float = 1_800_000_000.0) -> None:
        self.value = value
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.value += seconds


def _policy(
    tmp_path: Path,
    clock: MutableClock,
    *,
    per_run_budget: int = 3,
    daily_budget: int = 5,
) -> RequestSafetyPolicy:
    return RequestSafetyPolicy(
        state_path=tmp_path / "safety-state.json",
        min_delay_seconds=10,
        max_delay_seconds=10,
        per_run_budget=per_run_budget,
        daily_budget=daily_budget,
        block_cooldown_seconds=3600,
        clock=clock.now,
        sleeper=clock.sleep,
        jitter=lambda _minimum, _maximum: 10,
    )


def test_request_spacing_persists_across_process_restarts(tmp_path: Path) -> None:
    clock = MutableClock()
    _policy(tmp_path, clock).before_request()

    _policy(tmp_path, clock).before_request()

    assert clock.sleeps == [10]
    state = json.loads((tmp_path / "safety-state.json").read_text(encoding="utf-8"))
    assert state["requests_today"] == 2


def test_per_run_and_daily_budgets_fail_closed(tmp_path: Path) -> None:
    clock = MutableClock()
    policy = _policy(tmp_path, clock, per_run_budget=2, daily_budget=2)
    policy.before_request()
    policy.before_request()

    with pytest.raises(SafetyPolicyError, match="Per-run request budget"):
        policy.before_request()
    with pytest.raises(SafetyPolicyError, match="Daily request budget"):
        _policy(tmp_path, clock, per_run_budget=1, daily_budget=2).before_request()


def test_block_cooldown_survives_restart_and_honors_longer_retry_after(
    tmp_path: Path,
) -> None:
    clock = MutableClock()
    policy = _policy(tmp_path, clock)
    policy.block("HTTP 429", retry_after_seconds=7200)

    with pytest.raises(SafetyPolicyError, match="HTTP 429"):
        _policy(tmp_path, clock).before_request()

    clock.value += 7201
    _policy(tmp_path, clock).before_request()


def test_corrupt_state_is_not_silently_reset(tmp_path: Path) -> None:
    state_path = tmp_path / "safety-state.json"
    state_path.write_text("not-json", encoding="utf-8")
    clock = MutableClock()

    with pytest.raises(SafetyPolicyError, match="Cannot safely read"):
        _policy(tmp_path, clock).before_request()


def test_run_lock_rejects_concurrent_crawler(tmp_path: Path) -> None:
    lock_path = tmp_path / "crawler.lock"

    with RunLock(lock_path):
        with pytest.raises(SafetyPolicyError, match="already running"):
            with RunLock(lock_path):
                pass

    with RunLock(lock_path):
        pass
