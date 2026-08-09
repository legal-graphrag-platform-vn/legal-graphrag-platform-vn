"""Observability: structured trace logging for the chat pipeline (Plan 21)."""

from __future__ import annotations

from observability.llm import TracedTextGenerator
from observability.rag import (
    TracedAnswerGenerator,
    TracedAnswerProvider,
    log_retrieval_failure,
    log_retrieval_result,
)
from observability.trace import (
    TraceConfig,
    bind_trace,
    clear_trace,
    configure_logging,
    configure_trace,
    get_turn_trace,
    log_event,
    overall_status,
    redact,
    should_persist_turn,
    truncate,
)

__all__ = [
    "TraceConfig",
    "TracedAnswerGenerator",
    "TracedAnswerProvider",
    "TracedTextGenerator",
    "bind_trace",
    "clear_trace",
    "configure_logging",
    "configure_trace",
    "get_turn_trace",
    "log_event",
    "log_retrieval_failure",
    "log_retrieval_result",
    "overall_status",
    "redact",
    "should_persist_turn",
    "truncate",
]
