"""Deterministic reference resolver (Plan 19 §4).

Candidate universe rules:
  * A pending SELECT is answered only by an ordinal/label selection or a cancel;
    its candidate list is never expanded in place by history or a new mention.
    A genuinely new question does not extend the list — it abandons the stale
    clarification and is resolved fresh (see break-out below).
  * Without pending, explicit canonical candidates come from the current message
    and grounded focuses serve anaphora only.

Pending SELECT break-out: a reply that is neither a valid selection nor a cancel
is re-resolved as a fresh message. If that yields a committing outcome (resolved
or standalone) or a new explicit-based SELECT, the user has asked a genuinely new
question and the stale clarification is abandoned. A merely ambiguous reply
(RESTATE) keeps the original numbered list.

The resolver is deterministic; it never rewrites text or calls a model.
"""

from __future__ import annotations

from persistence.domain import (
    ClarificationCandidate,
    HistoryContext,
    PendingClarification,
)
from persistence.enums import ClarificationMode, ResolutionStatus
from resolution.anaphora import detect_anaphora
from resolution.canonical_lookup import CanonicalLookupPort
from resolution.clarification import (
    build_restate_question,
    build_select_question,
    is_cancel,
    match_select,
)
from resolution.explicit_parser import parse_explicit_references
from resolution.models import (
    REASON_ANAPHORA_AMBIGUOUS,
    REASON_REFERENT_NOT_FOUND,
    REASON_SELECT_INPUT_INVALID,
    CancelResolution,
    ClarifyResolution,
    ExpectedUnitType,
    ResolutionOutcome,
    ResolvedCandidate,
    ResolvedResolution,
    StandaloneResolution,
)

_MAX_CLARIFICATION_CANDIDATES = 5


def _breaks_out_of_pending_select(outcome: ResolutionOutcome) -> bool:
    """A fresh outcome that supersedes a stale pending SELECT clarification.

    Committing outcomes (resolved) and a new explicit-based SELECT
    count as a new question; a generic statement or RESTATE does not.
    """
    if isinstance(outcome, ResolvedResolution):
        return True
    if isinstance(outcome, ClarifyResolution) and outcome.mode is ClarificationMode.SELECT:
        return True
    return False


class ReferenceResolver:
    def __init__(self, lookup: CanonicalLookupPort) -> None:
        self._lookup = lookup

    async def resolve(
        self, *, message: str, context: HistoryContext
    ) -> ResolutionOutcome:
        # Pending always takes precedence, even over small-talk bypass.
        if context.pending_clarification is not None:
            return await self._resolve_pending(
                message, context.pending_clarification, context
            )
        return await self._resolve_fresh(message, context)

    # -- pending clarification --------------------------------------------- #

    async def _resolve_pending(
        self,
        message: str,
        pending: PendingClarification,
        context: HistoryContext,
    ) -> ResolutionOutcome:
        if is_cancel(message):
            return CancelResolution()
        if pending.mode is ClarificationMode.SELECT:
            candidate = match_select(pending, message)
            if candidate is not None:
                return ResolvedResolution(
                    candidate=ResolvedCandidate.from_clarification_candidate(candidate),
                    is_anaphora=True,
                )
            return ClarifyResolution(
                mode=ClarificationMode.SELECT,
                resolution_status=ResolutionStatus.AMBIGUOUS,
                reason_code=REASON_SELECT_INPUT_INVALID,
                question=build_select_question(pending.candidates),
                candidates=pending.candidates,
            )
        # RESTATE: the follow-up must be a standalone question.
        return await self._resolve_fresh(message, context)

    # -- fresh resolution --------------------------------------------------- #

    async def _resolve_fresh(
        self, message: str, context: HistoryContext
    ) -> ResolutionOutcome:
        explicit_references = parse_explicit_references(message)
        if explicit_references:
            return await self._resolve_explicit(explicit_references)
        anaphora = detect_anaphora(message)
        if anaphora is not None:
            return self._resolve_anaphora(anaphora.expected_type, context)
        return StandaloneResolution()

    async def _resolve_explicit(self, references) -> ResolutionOutcome:
        candidates: list[ResolvedCandidate] = []
        seen: set[str] = set()
        for reference in references:
            for candidate in await self._lookup.lookup(reference):
                if candidate.node_id not in seen:
                    seen.add(candidate.node_id)
                    candidates.append(candidate)
        if len(candidates) == 1:
            return ResolvedResolution(candidate=candidates[0], is_anaphora=False)
        if len(candidates) > 1:
            return self._clarify_from_candidates(
                tuple(c.to_clarification_candidate() for c in candidates)
            )
        # Explicit structural mention that does not exist.
        return ClarifyResolution(
            mode=ClarificationMode.RESTATE,
            resolution_status=ResolutionStatus.UNRESOLVED,
            reason_code=REASON_REFERENT_NOT_FOUND,
            question=build_restate_question(references[0].deepest_unit_type),
            candidates=(),
        )

    def _resolve_anaphora(
        self, expected_type: ExpectedUnitType | None, context: HistoryContext
    ) -> ResolutionOutcome:
        matches = [
            focus
            for focus in context.grounded_focuses
            if expected_type is None or focus.node_type == expected_type.value
        ]
        if len(matches) == 1:
            return ResolvedResolution(
                candidate=ResolvedCandidate.from_grounded_focus(matches[0]),
                is_anaphora=True,
            )
        if len(matches) > 1:
            # Recency never auto-breaks ambiguity (Plan 19 §4).
            return self._clarify_from_candidates(
                tuple(
                    ResolvedCandidate.from_grounded_focus(
                        focus
                    ).to_clarification_candidate()
                    for focus in matches
                )
            )
        return ClarifyResolution(
            mode=ClarificationMode.RESTATE,
            resolution_status=ResolutionStatus.UNRESOLVED,
            reason_code=REASON_REFERENT_NOT_FOUND,
            question=build_restate_question(expected_type),
            candidates=(),
        )

    def _clarify_from_candidates(
        self, candidates: tuple[ClarificationCandidate, ...]
    ) -> ClarifyResolution:
        bounded = candidates[:_MAX_CLARIFICATION_CANDIDATES]
        return ClarifyResolution(
            mode=ClarificationMode.SELECT,
            resolution_status=ResolutionStatus.AMBIGUOUS,
            reason_code=REASON_ANAPHORA_AMBIGUOUS,
            question=build_select_question(bounded),
            candidates=bounded,
        )
