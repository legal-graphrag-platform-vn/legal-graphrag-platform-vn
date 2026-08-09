"""Structured, trace-correlated logging for the chat pipeline (Plan 21).

Every event of one request is bound to a ``trace_id`` (the client turn id) via a
``ContextVar`` so it propagates automatically across ``await`` boundaries and the
concurrent subquery fan-out. Events are emitted as one JSON line each on the
dedicated ``chat.trace`` logger, ready to ship to Loki.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
import logging
import logging.handlers
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

_TRACE_LOGGER = "chat.trace"
_PREVIEW_CHARS = 500

# --------------------------------------------------------------------------- #
# Trace context (auto-propagated across asyncio await points)                 #
# --------------------------------------------------------------------------- #

_trace_ctx: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "chat_trace_ctx", default=None
)


def bind_trace(
    *,
    turn_id: Any,
    conversation_id: Any | None = None,
    owner_id: Any | None = None,
) -> None:
    """Bind identifiers for the current request; all later events carry them."""
    _trace_ctx.set(
        {
            "trace_id": str(turn_id),
            "conversation_id": str(conversation_id) if conversation_id else None,
            "owner_id": str(owner_id) if owner_id else None,
        }
    )


def clear_trace() -> None:
    _trace_ctx.set(None)


# --------------------------------------------------------------------------- #
# Redaction config                                                            #
# --------------------------------------------------------------------------- #


@dataclass
class TraceConfig:
    """How much of an LLM prompt/response to capture. See Plan 21 §5."""

    llm_io: str = "redacted"  # off | redacted | full
    max_raw: int = 2000


_config = TraceConfig()


def configure_trace(config: TraceConfig) -> None:
    global _config
    _config = config


def redact(text: str | None) -> dict[str, Any]:
    """Return a size/hash-capped view of ``text`` per the active TraceConfig."""
    if text is None:
        return {"chars": 0}
    info: dict[str, Any] = {
        "chars": len(text),
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
    }
    mode = _config.llm_io
    if mode == "full":
        info["text"] = text[: _config.max_raw]
    elif mode == "redacted":
        info["preview"] = text[:_PREVIEW_CHARS]
    # mode == "off": only chars + hash
    return info


def truncate(text: str | None, *, max_len: int | None = None) -> str | None:
    """Hard cap a raw string for diagnostic fields (independent of llm_io)."""
    if text is None:
        return None
    limit = max_len or _config.max_raw
    return text[:limit]


# --------------------------------------------------------------------------- #
# JSON logging                                                                #
# --------------------------------------------------------------------------- #


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = getattr(record, "trace_payload", None)
        if payload is not None:
            return json.dumps(payload, ensure_ascii=False, default=str)
        base: dict[str, Any] = {
            "ts": _now_iso(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            base["exc"] = self.formatException(record.exc_info)
        return json.dumps(base, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO", *, log_file: str | None = None) -> None:
    """Set root level and route ``chat.trace`` events through JSON handlers.

    Always writes JSON to stdout. When ``log_file`` is set, additionally writes
    the same JSON to a rotating file — the bridge Promtail tails to ship the
    events to Loki (Plan 21 §5b). Idempotent: safe to call again on app reload.
    """
    numeric = getattr(logging, level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(numeric)
    if not root.handlers:
        root.addHandler(logging.StreamHandler())

    trace_logger = logging.getLogger(_TRACE_LOGGER)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(_JsonFormatter())
    handlers: list[logging.Handler] = [stream_handler]
    if log_file:
        os.makedirs(os.path.dirname(log_file) or ".", exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(_JsonFormatter())
        handlers.append(file_handler)
    trace_logger.handlers = handlers
    trace_logger.setLevel(numeric)
    trace_logger.propagate = False


def log_event(stage: str, status: str = "ok", **fields: Any) -> None:
    """Emit one structured trace event bound to the current request."""
    ctx = _trace_ctx.get() or {}
    payload: dict[str, Any] = {"ts": _now_iso(), "stage": stage, "status": status}
    payload.update({k: v for k, v in ctx.items() if v is not None})
    payload.update({k: v for k, v in fields.items() if v is not None})
    level = logging.WARNING if status in {"error", "failed"} else logging.INFO
    logging.getLogger(_TRACE_LOGGER).log(
        level, stage, extra={"trace_payload": payload}
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
