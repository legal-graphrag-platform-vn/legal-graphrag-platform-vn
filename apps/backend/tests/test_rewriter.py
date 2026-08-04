"""Unit tests for the rule-assisted structured rewriter (Plan 19 §4)."""

from __future__ import annotations

import asyncio

import pytest

from resolution.models import (
    ExpectedUnitType,
    ResolvedCandidate,
    ResolvedResolution,
    StandaloneResolution,
)
from resolution.rewriter import (
    RewriteAnchorError,
    RewriteCandidate,
    RewriteDependencyError,
    RewriteLLMRequest,
    RewriteOutputError,
    RewriteTimeoutError,
    RewriteUnknownIdError,
    StructuredRewriter,
)


class FakeLLM:
    def __init__(self, handler) -> None:
        self._handler = handler
        self.calls: list[RewriteLLMRequest] = []

    async def rewrite(self, request: RewriteLLMRequest) -> RewriteCandidate:
        self.calls.append(request)
        return await self._handler(request)


def _article_candidate() -> ResolvedCandidate:
    return ResolvedCandidate(
        node_id="art-111",
        node_type=ExpectedUnitType.ARTICLE,
        canonical_label="Điều 111 59/2020/QH14",
        document_id="doc-1",
        document_number="59/2020/QH14",
        article_id="art-111",
        article_number="111",
    )


def _run(rewriter: StructuredRewriter, *, message, resolution, recent=()):
    return asyncio.run(
        rewriter.rewrite(
            message=message,
            recent_messages=recent,
            resolution=resolution,
        )
    )


# --------------------------------------------------------------------------- #
# Rule fast path (no model)                                                     #
# --------------------------------------------------------------------------- #


def test_standalone_query_is_used_verbatim() -> None:
    rewriter = StructuredRewriter(llm=None)
    result = _run(
        rewriter,
        message="công ty cổ phần là gì",
        resolution=StandaloneResolution(),
    )
    assert result == "công ty cổ phần là gì"


def test_explicit_reference_with_anchor_needs_no_model() -> None:
    llm = FakeLLM(None)
    rewriter = StructuredRewriter(llm=llm)
    result = _run(
        rewriter,
        message="Điều 111 59/2020/QH14 quy định gì",
        resolution=ResolvedResolution(
            candidate=_article_candidate(), is_anaphora=False
        ),
    )
    assert "Điều 111" in result
    assert "59/2020/QH14" in result
    assert llm.calls == []


def test_anaphora_rule_replaces_phrase_with_canonical_label() -> None:
    llm = FakeLLM(None)
    rewriter = StructuredRewriter(llm=llm)
    result = _run(
        rewriter,
        message="điều đó quy định gì",
        resolution=ResolvedResolution(candidate=_article_candidate(), is_anaphora=True),
    )
    assert result == "Điều 111 59/2020/QH14 quy định gì"
    assert llm.calls == []


# --------------------------------------------------------------------------- #
# Model fallback                                                                #
# --------------------------------------------------------------------------- #


def _label_missing_anchor_candidate() -> ResolvedCandidate:
    # Canonical label omits the document number, so the rule cannot satisfy the
    # anchor set and the model fallback must run.
    return ResolvedCandidate(
        node_id="art-111",
        node_type=ExpectedUnitType.ARTICLE,
        canonical_label="Điều 111",
        document_id="doc-1",
        document_number="59/2020/QH14",
        article_id="art-111",
        article_number="111",
    )


def test_model_fallback_used_when_rule_loses_anchor() -> None:
    async def handler(request: RewriteLLMRequest) -> RewriteCandidate:
        return RewriteCandidate(
            resolved_candidate_id=request.allowed_candidate_id,
            standalone_query="Điều 111 59/2020/QH14 quy định nội dung gì",
        )

    llm = FakeLLM(handler)
    rewriter = StructuredRewriter(llm=llm)
    result = _run(
        rewriter,
        message="điều đó quy định gì",
        resolution=ResolvedResolution(
            candidate=_label_missing_anchor_candidate(), is_anaphora=True
        ),
    )
    assert "59/2020/QH14" in result
    assert len(llm.calls) == 1
    # The model only receives the resolved candidate id in the allowlist.
    assert llm.calls[0].allowed_candidate_id == "art-111"


def test_missing_fallback_raises_anchor_error() -> None:
    rewriter = StructuredRewriter(llm=None)
    with pytest.raises(RewriteAnchorError):
        _run(
            rewriter,
            message="điều đó quy định gì",
            resolution=ResolvedResolution(
                candidate=_label_missing_anchor_candidate(), is_anaphora=True
            ),
        )


def test_model_output_with_unknown_id_is_rejected() -> None:
    async def handler(request: RewriteLLMRequest) -> RewriteCandidate:
        return RewriteCandidate(
            resolved_candidate_id="art-999",
            standalone_query="Điều 111 59/2020/QH14 quy định gì",
        )

    rewriter = StructuredRewriter(llm=FakeLLM(handler))
    with pytest.raises(RewriteUnknownIdError):
        _run(
            rewriter,
            message="điều đó quy định gì",
            resolution=ResolvedResolution(
                candidate=_label_missing_anchor_candidate(), is_anaphora=True
            ),
        )


def test_model_output_missing_anchor_is_rejected() -> None:
    async def handler(request: RewriteLLMRequest) -> RewriteCandidate:
        return RewriteCandidate(
            resolved_candidate_id=request.allowed_candidate_id,
            standalone_query="Điều 111 quy định gì",  # document number dropped
        )

    rewriter = StructuredRewriter(llm=FakeLLM(handler))
    with pytest.raises(RewriteAnchorError):
        _run(
            rewriter,
            message="điều đó quy định gì",
            resolution=ResolvedResolution(
                candidate=_label_missing_anchor_candidate(), is_anaphora=True
            ),
        )


def test_model_timeout_is_typed() -> None:
    async def handler(request: RewriteLLMRequest) -> RewriteCandidate:
        raise asyncio.TimeoutError()

    rewriter = StructuredRewriter(llm=FakeLLM(handler))
    with pytest.raises(RewriteTimeoutError):
        _run(
            rewriter,
            message="điều đó quy định gì",
            resolution=ResolvedResolution(
                candidate=_label_missing_anchor_candidate(), is_anaphora=True
            ),
        )


def test_model_dependency_failure_is_typed() -> None:
    async def handler(request: RewriteLLMRequest) -> RewriteCandidate:
        raise RuntimeError("provider down")

    rewriter = StructuredRewriter(llm=FakeLLM(handler))
    with pytest.raises(RewriteDependencyError):
        _run(
            rewriter,
            message="điều đó quy định gì",
            resolution=ResolvedResolution(
                candidate=_label_missing_anchor_candidate(), is_anaphora=True
            ),
        )


def test_empty_model_query_is_output_error() -> None:
    async def handler(request: RewriteLLMRequest) -> RewriteCandidate:
        return RewriteCandidate(
            resolved_candidate_id=request.allowed_candidate_id,
            standalone_query="   ",
        )

    rewriter = StructuredRewriter(llm=FakeLLM(handler))
    with pytest.raises(RewriteOutputError):
        _run(
            rewriter,
            message="điều đó quy định gì",
            resolution=ResolvedResolution(
                candidate=_label_missing_anchor_candidate(), is_anaphora=True
            ),
        )
