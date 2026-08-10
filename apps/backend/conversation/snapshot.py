"""Response snapshots and buffered SSE reconstruction (Plan 19 §4).

A turn is persisted before any bytes stream to the client. The same
``stream_from_snapshot`` reconstruction is used for the live response and for
idempotent replay, which guarantees replay parity.
"""

from __future__ import annotations

from typing import Any

from api.models import (
    ChatClarificationData,
    ChatCitationData,
    ChatDoneData,
    ChatExplanationData,
    ChatMetadataData,
    ChatStreamEvent,
    ChatTokenData,
)

KIND_ANSWER = "answer"
KIND_CANNOT_ANSWER = "cannot_answer"
KIND_SMALL_TALK = "small_talk"
KIND_CLARIFICATION = "clarification"
KIND_ERROR = "error"
KIND_PROCESSING = "processing"

_ANSWER_KINDS = frozenset({KIND_ANSWER, KIND_CANNOT_ANSWER, KIND_SMALL_TALK})


def answer_snapshot(
    *,
    kind: str,
    metadata: ChatMetadataData,
    answer_text: str,
    citations: list[ChatCitationData],
    done: ChatDoneData,
    answer_structure: dict[str, Any] | None = None,
    explanation: ChatExplanationData | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    snapshot = {
        "kind": kind,
        "metadata": metadata.model_dump(mode="json"),
        "answer_text": answer_text,
        "answer": {
            "markdown": answer_text,
            **(answer_structure or {}),
        },
        "citations": [citation.model_dump(mode="json") for citation in citations],
        "explanation": (explanation or ChatExplanationData()).model_dump(mode="json"),
        "done": done.model_dump(mode="json"),
    }
    if diagnostics:
        snapshot["diagnostics"] = diagnostics
    return snapshot


def clarification_snapshot(
    *,
    metadata: ChatMetadataData,
    clarification: ChatClarificationData,
    done: ChatDoneData,
) -> dict[str, Any]:
    return {
        "kind": KIND_CLARIFICATION,
        "metadata": metadata.model_dump(mode="json"),
        "clarification": clarification.model_dump(mode="json"),
        "done": done.model_dump(mode="json"),
    }


def error_snapshot(*, code: str, message: str) -> dict[str, Any]:
    return {
        "kind": KIND_ERROR,
        "error": {"code": code, "message": message},
        "done": ChatDoneData(status="error", citation_count=0).model_dump(mode="json"),
    }


def processing_snapshot(*, retry_after_ms: int) -> dict[str, Any]:
    return {
        "kind": KIND_PROCESSING,
        "done": ChatDoneData(
            status="processing",
            citation_count=0,
            retry_after_ms=retry_after_ms,
        ).model_dump(mode="json"),
    }


def _chunks(value: str, chunk_size: int) -> list[str]:
    return [value[i : i + chunk_size] for i in range(0, len(value), chunk_size)]


def stream_from_snapshot(
    snapshot: dict[str, Any], *, chunk_chars: int
) -> list[ChatStreamEvent]:
    """Reconstruct the SSE event sequence from a persisted snapshot."""
    if chunk_chars < 1:
        raise ValueError("chunk_chars must be positive")
    kind = snapshot.get("kind")
    events: list[ChatStreamEvent] = []

    metadata = snapshot.get("metadata")
    if metadata is not None:
        events.append(ChatStreamEvent(event="metadata", data=metadata))

    if kind == KIND_ERROR:
        events.append(ChatStreamEvent(event="error", data=snapshot["error"]))
        events.append(ChatStreamEvent(event="done", data=snapshot["done"]))
        return events

    if kind == KIND_PROCESSING:
        events.append(ChatStreamEvent(event="done", data=snapshot["done"]))
        return events

    if kind == KIND_CLARIFICATION:
        clarification = snapshot["clarification"]
        events.append(ChatStreamEvent(event="clarification", data=clarification))
        for chunk in _chunks(clarification["question"], chunk_chars):
            events.append(
                ChatStreamEvent(
                    event="token",
                    data=ChatTokenData(content=chunk).model_dump(mode="json"),
                )
            )
        events.append(ChatStreamEvent(event="done", data=snapshot["done"]))
        return events

    if kind in _ANSWER_KINDS:
        answer = snapshot.get("answer") or {}
        markdown = answer.get("markdown", snapshot.get("answer_text", ""))
        for chunk in _chunks(markdown, chunk_chars):
            events.append(
                ChatStreamEvent(
                    event="token",
                    data=ChatTokenData(content=chunk).model_dump(mode="json"),
                )
            )
        explanation = snapshot.get("explanation")
        if explanation and (
            explanation.get("temporal_notes") or explanation.get("reasoning_paths")
        ):
            events.append(ChatStreamEvent(event="explanation", data=explanation))
        for citation in snapshot.get("citations", []):
            events.append(ChatStreamEvent(event="citation", data=citation))
        events.append(ChatStreamEvent(event="done", data=snapshot["done"]))
        return events

    raise ValueError(f"Unknown snapshot kind: {kind!r}")
