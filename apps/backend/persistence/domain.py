"""Immutable domain value objects for the conversation context store (Plan 19).

These are the repository's input/output contract. PostgreSQL is the source of
truth; the service layer never reconstructs context from anywhere else.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from persistence.enums import (
    ClarificationMode,
    MessageKind,
    MessageRole,
    OwnerKind,
    ResolutionStatus,
    TurnStatus,
)
from persistence.errors import InvalidClarificationCandidatesError

MAX_CLARIFICATION_CANDIDATES = 5


@dataclass(frozen=True)
class Owner:
    """The authenticated principal that owns a conversation."""

    owner_kind: OwnerKind
    owner_principal_id: uuid.UUID


@dataclass(frozen=True)
class HistoryMessage:
    """A completed transcript message used only for language understanding."""

    role: MessageRole
    kind: MessageKind
    content: str
    ordinal: int
    user_turn_no: int


@dataclass(frozen=True)
class GroundedFocus:
    """A citable node retained as an anaphora referent (Plan 19 §4 focus policy)."""

    node_id: str
    node_type: str
    canonical_label: str
    document_id: str
    citation_order: int
    last_grounded_user_turn_no: int
    document_type: str | None = None
    article_id: str | None = None
    clause_id: str | None = None
    document_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ClarificationCandidate:
    """One resolvable option offered in a pending clarification."""

    candidate_id: str
    label: str
    node_type: str | None = None
    document_id: str | None = None
    article_id: str | None = None
    clause_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "candidate_id": self.candidate_id,
            "label": self.label,
        }
        for key in ("node_type", "document_id", "article_id", "clause_id"):
            value = getattr(self, key)
            if value is not None:
                payload[key] = value
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload

    @classmethod
    def from_json(cls, raw: Any) -> "ClarificationCandidate":
        if not isinstance(raw, dict):
            raise InvalidClarificationCandidatesError(
                "Clarification candidate must be a JSON object"
            )
        candidate_id = raw.get("candidate_id")
        label = raw.get("label")
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            raise InvalidClarificationCandidatesError(
                "Clarification candidate requires a non-empty candidate_id"
            )
        if not isinstance(label, str) or not label.strip():
            raise InvalidClarificationCandidatesError(
                "Clarification candidate requires a non-empty label"
            )
        metadata = raw.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise InvalidClarificationCandidatesError(
                "Clarification candidate metadata must be a JSON object"
            )
        return cls(
            candidate_id=candidate_id,
            label=label,
            node_type=_optional_str(raw.get("node_type")),
            document_id=_optional_str(raw.get("document_id")),
            article_id=_optional_str(raw.get("article_id")),
            clause_id=_optional_str(raw.get("clause_id")),
            metadata=dict(metadata),
        )


def validate_candidates(
    candidates: tuple[ClarificationCandidate, ...],
) -> tuple[ClarificationCandidate, ...]:
    """Enforce the bounded, unique candidate universe (Plan 19 §3)."""
    if not candidates:
        raise InvalidClarificationCandidatesError(
            "A pending clarification requires at least one candidate"
        )
    if len(candidates) > MAX_CLARIFICATION_CANDIDATES:
        raise InvalidClarificationCandidatesError(
            f"At most {MAX_CLARIFICATION_CANDIDATES} clarification candidates allowed"
        )
    seen: set[str] = set()
    for candidate in candidates:
        if candidate.candidate_id in seen:
            raise InvalidClarificationCandidatesError(
                "Clarification candidate ids must be unique"
            )
        seen.add(candidate.candidate_id)
    return candidates


def candidates_to_json(
    candidates: tuple[ClarificationCandidate, ...],
) -> list[dict[str, Any]]:
    return [candidate.to_json() for candidate in validate_candidates(candidates)]


def candidates_from_json(raw: Any) -> tuple[ClarificationCandidate, ...]:
    if not isinstance(raw, list):
        raise InvalidClarificationCandidatesError(
            "Persisted candidates must be a JSON array"
        )
    return validate_candidates(
        tuple(ClarificationCandidate.from_json(item) for item in raw)
    )


@dataclass(frozen=True)
class PendingClarification:
    """An open clarification whose candidate snapshot bounds the next turn."""

    mode: ClarificationMode
    question: str
    candidates: tuple[ClarificationCandidate, ...]
    source_turn_id: uuid.UUID
    source_user_turn_no: int


@dataclass(frozen=True)
class HistoryContext:
    """Server-owned context loaded once per turn (Plan 19 §4)."""

    recent_messages: tuple[HistoryMessage, ...]
    grounded_focuses: tuple[GroundedFocus, ...]
    pending_clarification: PendingClarification | None


@dataclass(frozen=True)
class TurnRecord:
    """Persisted turn state used for idempotency and replay."""

    turn_id: uuid.UUID
    conversation_id: uuid.UUID
    client_turn_id: uuid.UUID
    user_turn_no: int
    status: TurnStatus
    resolution_status: ResolutionStatus | None
    resolution_reason_code: str | None
    standalone_query: str | None
    error_code: str | None
    response_snapshot: dict[str, Any] | None
    created_at: datetime


@dataclass(frozen=True)
class BegunTurn:
    """Result of opening a turn and loading server-owned context."""

    turn_id: uuid.UUID
    conversation_id: uuid.UUID
    user_turn_no: int
    user_message_ordinal: int
    context: HistoryContext


@dataclass(frozen=True)
class CitationSnapshot:
    """Canonical citation metadata persisted for replay and focus upsert."""

    unit_id: str
    citation_ordinal: int
    citation_label: str
    document_id: str
    deep_link: str
    article_id: str | None = None
    clause_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FocusUpsert:
    """A grounded focus to upsert from a successful answer's citations."""

    node_id: str
    node_type: str
    canonical_label: str
    document_id: str
    citation_order: int
    document_type: str | None = None
    article_id: str | None = None
    clause_id: str | None = None
    document_metadata: dict[str, Any] = field(default_factory=dict)


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidClarificationCandidatesError(
            "Clarification candidate fields must be strings"
        )
    stripped = value.strip()
    return stripped or None
