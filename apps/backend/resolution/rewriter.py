"""Rule-assisted structured rewriter (Plan 19 §4).

A standalone query is never rewritten by a model. A simple referential rewrite
uses a rule template that inserts the canonical citation/document label. Only when
natural Vietnamese phrasing is needed does the Gemini structured-output fallback
run — and its output is validated against the allowlisted candidate id and the
canonical anchors before retrieval. Every failure is typed and raised before any
retrieval call.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from resolution.anaphora import replace_first_anaphora
from resolution.models import (
    ResolvedCandidate,
    ResolvedResolution,
    StandaloneResolution,
)

MAX_QUERY_CHARS = 4000


class RewriteError(Exception):
    """Base class for typed rewrite failures raised before retrieval."""

    error_code = "REWRITE_FAILED"


class RewriteUnknownIdError(RewriteError):
    error_code = "REWRITE_UNKNOWN_ID"


class RewriteAnchorError(RewriteError):
    error_code = "REWRITE_ANCHOR_MISSING"


class RewriteOutputError(RewriteError):
    error_code = "REWRITE_OUTPUT_INVALID"


class RewriteTimeoutError(RewriteError):
    error_code = "REWRITE_TIMEOUT"


class RewriteDependencyError(RewriteError):
    error_code = "REWRITE_DEPENDENCY_FAILED"


class RewriteCandidate(BaseModel):
    """Structured rewriter output (Plan 19 §4)."""

    model_config = ConfigDict(extra="forbid")

    resolved_candidate_id: str = Field(min_length=1)
    standalone_query: str = Field(min_length=1)


@dataclass(frozen=True)
class RewriteLLMRequest:
    """Bounded input passed to the fallback model — nothing else."""

    message: str
    recent_messages: tuple[str, ...]
    allowed_candidate_id: str
    canonical_label: str
    required_anchors: tuple[str, ...]


class RewriterLLMPort(Protocol):
    async def rewrite(self, request: RewriteLLMRequest) -> RewriteCandidate: ...


def _contains_all(query: str, anchors: tuple[str, ...]) -> bool:
    lowered = query.casefold()
    return all(anchor.casefold() in lowered for anchor in anchors)


class StructuredRewriter:
    def __init__(
        self,
        llm: RewriterLLMPort | None = None,
        *,
        max_query_chars: int = MAX_QUERY_CHARS,
    ) -> None:
        self._llm = llm
        self._max_query_chars = max_query_chars

    async def rewrite(
        self,
        *,
        message: str,
        recent_messages: tuple[str, ...],
        resolution: StandaloneResolution | ResolvedResolution,
    ) -> str:
        if isinstance(resolution, StandaloneResolution):
            # A standalone query is used verbatim; no model, no anchors.
            return self._finalize(message, anchors=())

        candidate = resolution.candidate
        anchors = candidate.required_anchors()
        ruled = self._rule_rewrite(message, resolution)
        if ruled is not None and _contains_all(ruled, anchors):
            return self._finalize(ruled, anchors=anchors)
        return await self._model_rewrite(
            message=message,
            recent_messages=recent_messages,
            candidate=candidate,
            anchors=anchors,
        )

    def _rule_rewrite(self, message: str, resolution: ResolvedResolution) -> str | None:
        candidate = resolution.candidate
        anchors = candidate.required_anchors()
        if resolution.is_anaphora:
            replaced = replace_first_anaphora(message, candidate.canonical_label)
            return replaced if replaced is not None else message
        # Explicit reference: keep the message if it already carries the anchors,
        # otherwise enrich it with the canonical label.
        if _contains_all(message, anchors):
            return message
        return f"{message} ({candidate.canonical_label})"

    async def _model_rewrite(
        self,
        *,
        message: str,
        recent_messages: tuple[str, ...],
        candidate: ResolvedCandidate,
        anchors: tuple[str, ...],
    ) -> str:
        if self._llm is None:
            raise RewriteAnchorError(
                "Rule rewrite lost a canonical anchor and no fallback is configured"
            )
        request = RewriteLLMRequest(
            message=message,
            recent_messages=recent_messages,
            allowed_candidate_id=candidate.node_id,
            canonical_label=candidate.canonical_label,
            required_anchors=anchors,
        )
        try:
            output = await self._llm.rewrite(request)
        except asyncio.TimeoutError as exc:
            raise RewriteTimeoutError("Rewrite model timed out") from exc
        except RewriteError:
            raise
        except Exception as exc:
            raise RewriteDependencyError("Rewrite model failed") from exc

        if not isinstance(output, RewriteCandidate):
            raise RewriteOutputError("Rewrite model returned a malformed payload")
        if output.resolved_candidate_id != candidate.node_id:
            raise RewriteUnknownIdError(
                "Rewrite model chose an id outside the allowlist"
            )
        return self._finalize(output.standalone_query, anchors=anchors)

    def _finalize(self, query: str, *, anchors: tuple[str, ...]) -> str:
        cleaned = query.strip()
        if not cleaned:
            raise RewriteOutputError("Rewritten query must not be empty")
        if len(cleaned) > self._max_query_chars:
            raise RewriteOutputError("Rewritten query exceeds the maximum length")
        missing = tuple(a for a in anchors if a.casefold() not in cleaned.casefold())
        if missing:
            raise RewriteAnchorError(
                f"Rewritten query is missing canonical anchors: {missing}"
            )
        return cleaned
