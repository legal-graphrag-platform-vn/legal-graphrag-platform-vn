"""Trace wrapper over ``TextGenerationPort`` — captures LLM I/O (Plan 21 §3).

Wrapping at the port keeps the trace concern out of the query processor and the
provider adapters: whatever prompt goes in and whatever raw text comes back is
logged in one place, provider-agnostically.
"""

from __future__ import annotations

import time
from typing import Any

from observability.trace import log_event, redact
from src.shared.llm_ports import TextGenerationPort


class TracedTextGenerator:
    """Decorate a text generator to emit ``<stage>.llm`` trace events."""

    def __init__(self, inner: TextGenerationPort, *, stage: str) -> None:
        self._inner = inner
        self._stage = stage

    def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
        response_format: str | None = None,
    ) -> str:
        started = time.perf_counter()
        event = f"{self._stage}.llm"
        try:
            raw = self._inner.generate_text(
                system_prompt,
                user_prompt,
                temperature,
                response_format,
            )
        except Exception as exc:
            log_event(
                event,
                "error",
                latency_ms=_ms(started),
                error_type=type(exc).__name__,
                provider=_attr(self._inner, "provider"),
                model=_attr(self._inner, "model"),
                user_prompt=redact(user_prompt),
            )
            raise
        log_event(
            event,
            "ok",
            latency_ms=_ms(started),
            provider=_attr(self._inner, "provider"),
            model=_attr(self._inner, "model"),
            user_prompt=redact(user_prompt),
            raw_output=redact(raw),
        )
        return raw


def _ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


def _attr(obj: object, name: str) -> Any | None:
    return getattr(obj, name, None)
