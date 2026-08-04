"""Unit tests for the deterministic reference resolver (Plan 19 §4)."""

from __future__ import annotations

import asyncio

from persistence.domain import (
    ClarificationCandidate,
    GroundedFocus,
    HistoryContext,
    PendingClarification,
)
from persistence.enums import ClarificationMode, ResolutionStatus
from resolution.clarification import build_select_question, is_cancel, match_select
from resolution.models import (
    REASON_MULTIPLE_MATCHES,
    REASON_REFERENT_NOT_FOUND,
    REASON_SELECT_INPUT_INVALID,
    CancelResolution,
    ClarifyResolution,
    ExpectedUnitType,
    ResolvedCandidate,
    ResolvedResolution,
    StandaloneResolution,
)
from resolution.resolver import ReferenceResolver


class FakeLookup:
    """Returns preset candidates keyed by article or document number."""

    def __init__(self, mapping: dict[str, tuple[ResolvedCandidate, ...]]) -> None:
        self._mapping = mapping

    async def lookup(self, reference) -> tuple[ResolvedCandidate, ...]:
        key = reference.article_number or reference.document_number or ""
        return self._mapping.get(key, ())


def _candidate(
    node_id: str, *, article_number: str, document_id: str
) -> ResolvedCandidate:
    return ResolvedCandidate(
        node_id=node_id,
        node_type=ExpectedUnitType.ARTICLE,
        canonical_label=f"Điều {article_number} ({document_id})",
        document_id=document_id,
        document_number="59/2020/QH14",
        article_id=node_id,
        article_number=article_number,
    )


def _focus(
    node_id: str,
    *,
    node_type: ExpectedUnitType,
    label: str,
    turn: int = 1,
    order: int = 1,
    article_number: str | None = None,
) -> GroundedFocus:
    return GroundedFocus(
        node_id=node_id,
        node_type=node_type.value,
        canonical_label=label,
        document_id="doc-1",
        citation_order=order,
        last_grounded_user_turn_no=turn,
        document_metadata={"article_number": article_number} if article_number else {},
    )


def _context(
    *,
    focuses: tuple[GroundedFocus, ...] = (),
    pending: PendingClarification | None = None,
) -> HistoryContext:
    return HistoryContext(
        recent_messages=(),
        grounded_focuses=focuses,
        pending_clarification=pending,
    )


def _resolve(resolver: ReferenceResolver, message: str, context: HistoryContext):
    return asyncio.run(resolver.resolve(message=message, context=context))


# --------------------------------------------------------------------------- #
# Explicit resolution                                                          #
# --------------------------------------------------------------------------- #


def test_single_explicit_match_resolves() -> None:
    resolver = ReferenceResolver(
        FakeLookup(
            {"111": (_candidate("art-111", article_number="111", document_id="doc-1"),)}
        )
    )
    outcome = _resolve(resolver, "Điều 111 quy định gì", _context())
    assert isinstance(outcome, ResolvedResolution)
    assert outcome.is_anaphora is False
    assert outcome.candidate.node_id == "art-111"


def test_multiple_explicit_matches_are_ambiguous() -> None:
    resolver = ReferenceResolver(
        FakeLookup(
            {
                "5": (
                    _candidate("a-doc1", article_number="5", document_id="doc-1"),
                    _candidate("a-doc2", article_number="5", document_id="doc-2"),
                )
            }
        )
    )
    outcome = _resolve(resolver, "Điều 5 nói gì", _context())
    assert isinstance(outcome, ClarifyResolution)
    assert outcome.mode is ClarificationMode.SELECT
    assert outcome.resolution_status is ResolutionStatus.AMBIGUOUS
    assert outcome.reason_code == REASON_MULTIPLE_MATCHES
    assert len(outcome.candidates) == 2


def test_explicit_not_found_is_unresolved_restate() -> None:
    resolver = ReferenceResolver(FakeLookup({}))
    outcome = _resolve(resolver, "Điều 999 nói gì", _context())
    assert isinstance(outcome, ClarifyResolution)
    assert outcome.mode is ClarificationMode.RESTATE
    assert outcome.resolution_status is ResolutionStatus.UNRESOLVED
    assert outcome.reason_code == REASON_REFERENT_NOT_FOUND
    assert outcome.candidates == ()


def test_explicit_is_preferred_over_anaphora_focus() -> None:
    resolver = ReferenceResolver(
        FakeLookup(
            {"111": (_candidate("art-111", article_number="111", document_id="doc-1"),)}
        )
    )
    focuses = (_focus("art-7", node_type=ExpectedUnitType.ARTICLE, label="Điều 7"),)
    outcome = _resolve(resolver, "Điều 111 và điều đó", _context(focuses=focuses))
    assert isinstance(outcome, ResolvedResolution)
    assert outcome.candidate.node_id == "art-111"
    assert outcome.is_anaphora is False


# --------------------------------------------------------------------------- #
# Anaphora resolution                                                          #
# --------------------------------------------------------------------------- #


def test_single_focus_anaphora_resolves() -> None:
    resolver = ReferenceResolver(FakeLookup({}))
    focuses = (
        _focus(
            "art-111",
            node_type=ExpectedUnitType.ARTICLE,
            label="Điều 111",
            article_number="111",
        ),
    )
    outcome = _resolve(resolver, "điều này quy định gì", _context(focuses=focuses))
    assert isinstance(outcome, ResolvedResolution)
    assert outcome.is_anaphora is True
    assert outcome.candidate.node_id == "art-111"
    assert outcome.candidate.article_number == "111"


def test_multiple_focus_anaphora_is_ambiguous_without_recency_tiebreak() -> None:
    resolver = ReferenceResolver(FakeLookup({}))
    focuses = (
        _focus("art-1", node_type=ExpectedUnitType.ARTICLE, label="Điều 1", turn=2),
        _focus("art-2", node_type=ExpectedUnitType.ARTICLE, label="Điều 2", turn=1),
    )
    outcome = _resolve(resolver, "điều đó", _context(focuses=focuses))
    assert isinstance(outcome, ClarifyResolution)
    assert outcome.mode is ClarificationMode.SELECT
    assert {c.candidate_id for c in outcome.candidates} == {"art-1", "art-2"}


def test_anaphora_filters_focus_by_expected_type() -> None:
    resolver = ReferenceResolver(FakeLookup({}))
    focuses = (
        _focus("art-111", node_type=ExpectedUnitType.ARTICLE, label="Điều 111"),
        _focus("clause-1", node_type=ExpectedUnitType.CLAUSE, label="Khoản 1"),
    )
    outcome = _resolve(resolver, "khoản đó", _context(focuses=focuses))
    assert isinstance(outcome, ResolvedResolution)
    assert outcome.candidate.node_id == "clause-1"


def test_anaphora_without_matching_focus_is_unresolved() -> None:
    resolver = ReferenceResolver(FakeLookup({}))
    outcome = _resolve(resolver, "điều này", _context(focuses=()))
    assert isinstance(outcome, ClarifyResolution)
    assert outcome.resolution_status is ResolutionStatus.UNRESOLVED
    assert outcome.reason_code == REASON_REFERENT_NOT_FOUND


def test_no_reference_is_standalone() -> None:
    resolver = ReferenceResolver(FakeLookup({}))
    outcome = _resolve(resolver, "công ty cổ phần là gì", _context())
    assert isinstance(outcome, StandaloneResolution)


# --------------------------------------------------------------------------- #
# Pending clarification                                                        #
# --------------------------------------------------------------------------- #


def _pending_select() -> PendingClarification:
    import uuid

    return PendingClarification(
        mode=ClarificationMode.SELECT,
        question="Ý bạn là văn bản nào? 1. Luật A 2. Luật B",
        candidates=(
            ClarificationCandidate(
                candidate_id="art-doc1",
                label="Điều 5 Luật A",
                node_type="Article",
                document_id="doc-1",
                article_id="art-doc1",
                metadata={"article_number": "5", "document_number": "59/2020/QH14"},
            ),
            ClarificationCandidate(
                candidate_id="art-doc2",
                label="Điều 5 Luật B",
                node_type="Article",
                document_id="doc-2",
                article_id="art-doc2",
            ),
        ),
        source_turn_id=uuid.uuid4(),
        source_user_turn_no=1,
    )


def test_pending_select_resolves_by_ordinal() -> None:
    resolver = ReferenceResolver(FakeLookup({}))
    outcome = _resolve(resolver, "1", _context(pending=_pending_select()))
    assert isinstance(outcome, ResolvedResolution)
    assert outcome.candidate.node_id == "art-doc1"
    assert outcome.candidate.article_number == "5"


def test_pending_select_resolves_by_label() -> None:
    resolver = ReferenceResolver(FakeLookup({}))
    outcome = _resolve(resolver, "Điều 5 Luật B", _context(pending=_pending_select()))
    assert isinstance(outcome, ResolvedResolution)
    assert outcome.candidate.node_id == "art-doc2"


def test_pending_select_invalid_reasks_same_snapshot() -> None:
    resolver = ReferenceResolver(FakeLookup({}))
    pending = _pending_select()
    outcome = _resolve(resolver, "không rõ", _context(pending=pending))
    assert isinstance(outcome, ClarifyResolution)
    assert outcome.reason_code == REASON_SELECT_INPUT_INVALID
    assert outcome.candidates == pending.candidates


def test_pending_select_ignores_new_explicit_mention() -> None:
    # A pending SELECT universe is not expanded by a new explicit mention.
    resolver = ReferenceResolver(
        FakeLookup(
            {"999": (_candidate("art-999", article_number="999", document_id="doc-9"),)}
        )
    )
    outcome = _resolve(resolver, "Điều 999", _context(pending=_pending_select()))
    assert isinstance(outcome, ClarifyResolution)
    assert outcome.reason_code == REASON_SELECT_INPUT_INVALID


def test_pending_cancel_clears() -> None:
    resolver = ReferenceResolver(FakeLookup({}))
    outcome = _resolve(resolver, "hủy", _context(pending=_pending_select()))
    assert isinstance(outcome, CancelResolution)


def test_pending_restate_treats_followup_as_standalone() -> None:
    import uuid

    resolver = ReferenceResolver(FakeLookup({}))
    pending = PendingClarification(
        mode=ClarificationMode.RESTATE,
        question="Bạn nêu rõ hơn nhé?",
        candidates=(),
        source_turn_id=uuid.uuid4(),
        source_user_turn_no=1,
    )
    outcome = _resolve(resolver, "công ty cổ phần là gì", _context(pending=pending))
    assert isinstance(outcome, StandaloneResolution)


# --------------------------------------------------------------------------- #
# Clarification helpers                                                        #
# --------------------------------------------------------------------------- #


def test_build_select_question_lists_candidates() -> None:
    candidates = (
        ClarificationCandidate(candidate_id="c1", label="Luật A"),
        ClarificationCandidate(candidate_id="c2", label="Luật B"),
    )
    question = build_select_question(candidates)
    assert "1. Luật A" in question
    assert "2. Luật B" in question


def test_match_select_rejects_out_of_range_ordinal() -> None:
    pending = _pending_select()
    assert match_select(pending, "5") is None


def test_is_cancel_recognizes_variants() -> None:
    assert is_cancel("Hủy")
    assert is_cancel("bỏ qua")
    assert not is_cancel("có")
