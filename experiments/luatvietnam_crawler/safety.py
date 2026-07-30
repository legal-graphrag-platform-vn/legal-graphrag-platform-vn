"""Persistent request budgets, cooldowns, and single-process locking."""

from __future__ import annotations

try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore

try:
    import msvcrt
except ImportError:
    msvcrt = None  # type: ignore

import json
import os
import random
import tempfile
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any, TextIO

from .errors import SafetyPolicyError

STATE_VERSION = 1


class RunLock:
    """Prevent concurrent crawlers from sharing one IP/profile state."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle: TextIO | None = None

    def __enter__(self) -> RunLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+", encoding="utf-8")
        if fcntl is not None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                handle.close()
                raise SafetyPolicyError(
                    f"Another LuatVietnam crawler is already running: {self.path}"
                ) from exc
        elif msvcrt is not None:
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                handle.close()
                raise SafetyPolicyError(
                    f"Another LuatVietnam crawler is already running: {self.path}"
                ) from exc
        self._handle = handle
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._handle is not None:
            if fcntl is not None:
                try:
                    fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
            elif msvcrt is not None:
                try:
                    self._handle.seek(0)
                    msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            self._handle.close()
            self._handle = None


class RequestSafetyPolicy:
    """Fail closed when pacing, quota, or cooldown rules would be violated."""

    def __init__(
        self,
        *,
        state_path: Path,
        min_delay_seconds: float = 10.0,
        max_delay_seconds: float = 20.0,
        per_run_budget: int = 25,
        daily_budget: int = 100,
        block_cooldown_seconds: int = 86_400,
        clock: Callable[[], float] = time.time,
        sleeper: Callable[[float], None] = time.sleep,
        jitter: Callable[[float, float], float] | None = None,
    ) -> None:
        if min_delay_seconds < 0 or max_delay_seconds < min_delay_seconds:
            raise ValueError("Request delay range is invalid")
        if per_run_budget < 1 or daily_budget < per_run_budget:
            raise ValueError("Request budgets are invalid")
        if block_cooldown_seconds < 1:
            raise ValueError("Block cooldown must be positive")
        self.state_path = state_path
        self.min_delay_seconds = min_delay_seconds
        self.max_delay_seconds = max_delay_seconds
        self.per_run_budget = per_run_budget
        self.daily_budget = daily_budget
        self.block_cooldown_seconds = block_cooldown_seconds
        self.clock = clock
        self.sleeper = sleeper
        self.jitter = jitter or random.SystemRandom().uniform
        self.requests_this_run = 0

    def before_request(self) -> None:
        state = self._load_state()
        now = self.clock()
        self._reset_daily_counter(state, now)
        self._assert_not_cooling_down(state, now)
        if self.requests_this_run >= self.per_run_budget:
            raise SafetyPolicyError(
                f"Per-run request budget exhausted ({self.per_run_budget})"
            )
        if int(state["requests_today"]) >= self.daily_budget:
            raise SafetyPolicyError(
                f"Daily request budget exhausted ({self.daily_budget})"
            )

        last_request_at = _parse_timestamp(state.get("last_request_at"))
        if last_request_at is not None:
            requested_delay = self.jitter(
                self.min_delay_seconds, self.max_delay_seconds
            )
            remaining = last_request_at + requested_delay - now
            if remaining > 0:
                self.sleeper(remaining)
                now = self.clock()

        state["last_request_at"] = _format_timestamp(now)
        state["requests_today"] = int(state["requests_today"]) + 1
        self.requests_this_run += 1
        self._write_state(state)

    def block(self, reason: str, *, retry_after_seconds: int | None = None) -> None:
        state = self._load_state()
        now = self.clock()
        self._reset_daily_counter(state, now)
        requested_cooldown = max(self.block_cooldown_seconds, retry_after_seconds or 0)
        current_blocked_until = _parse_timestamp(state.get("blocked_until")) or 0
        state["blocked_until"] = _format_timestamp(
            max(current_blocked_until, now + requested_cooldown)
        )
        state["block_reason"] = reason
        self._write_state(state)

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return self._new_state(self.clock())
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SafetyPolicyError(
                f"Cannot safely read crawler state: {self.state_path}"
            ) from exc
        if not isinstance(state, dict) or state.get("version") != STATE_VERSION:
            raise SafetyPolicyError(
                f"Unsupported or malformed crawler state: {self.state_path}"
            )
        if not isinstance(state.get("requests_today"), int):
            raise SafetyPolicyError(
                f"Malformed request counter in crawler state: {self.state_path}"
            )
        return state

    def _write_state(self, state: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(
            dir=self.state_path.parent,
            prefix=f".{self.state_path.name}.",
            suffix=".tmp",
            text=True,
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(state, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.state_path)
        except BaseException:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
            raise

    def _reset_daily_counter(self, state: dict[str, Any], now: float) -> None:
        current_day = datetime.fromtimestamp(now, tz=UTC).date().isoformat()
        if state.get("day_utc") != current_day:
            state["day_utc"] = current_day
            state["requests_today"] = 0

    @staticmethod
    def _assert_not_cooling_down(state: dict[str, Any], now: float) -> None:
        blocked_until = _parse_timestamp(state.get("blocked_until"))
        if blocked_until is not None and blocked_until > now:
            reason = state.get("block_reason") or "remote block signal"
            raise SafetyPolicyError(
                "Crawler cooldown is active until "
                f"{_format_timestamp(blocked_until)} ({reason})"
            )

    @staticmethod
    def _new_state(now: float) -> dict[str, Any]:
        return {
            "version": STATE_VERSION,
            "day_utc": datetime.fromtimestamp(now, tz=UTC).date().isoformat(),
            "requests_today": 0,
            "last_request_at": None,
            "blocked_until": None,
            "block_reason": None,
        }


def _format_timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, tz=UTC).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: object) -> float | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise SafetyPolicyError(f"Malformed crawler timestamp: {value!r}")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError as exc:
        raise SafetyPolicyError(f"Malformed crawler timestamp: {value!r}") from exc
