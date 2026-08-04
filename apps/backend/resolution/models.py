"""Value objects for deterministic reference resolution (Plan 19 §4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from persistence.domain import ClarificationCandidate, GroundedFocus
from persistence.enums import ClarificationMode, ResolutionStatus


class ExpectedUnitType(str, Enum):
    DOCUMENT = "Document"
    ARTICLE = "Article"
    CLAUSE = "Clause"
    POINT = "Point"


# Resolution reason codes persisted on the turn (Plan 19 §4).
REASON_NO_REFERENCE_REQUIRED = "NO_REFERENCE_REQUIRED"
REASON_REFERENT_NOT_FOUND = "REFERENT_NOT_FOUND"
REASON_MULTIPLE_MATCHES = "MULTIPLE_MATCHES"
REASON_USER_CANCELLED = "USER_CANCELLED"
REASON_SELECT_INPUT_INVALID = "SELECT_INPUT_INVALID"


@dataclass(frozen=True)
class ExplicitReference:
    """Structural reference parsed deterministically from the current message."""

    document_number: str | None = None
    law_name: str | None = None
    law_year: int | None = None
    article_number: str | None = None
    clause_number: str | None = None
    point_label: str | None = None

    @property
    def has_document_identity(self) -> bool:
        return bool(self.document_number or self.law_name)

    @property
    def has_structural_unit(self) -> bool:
        return bool(self.article_number or self.clause_number or self.point_label)

    @property
    def is_present(self) -> bool:
        return self.has_document_identity or self.has_structural_unit

    @property
    def deepest_unit_type(self) -> ExpectedUnitType:
        if self.point_label:
            return ExpectedUnitType.POINT
        if self.clause_number:
            return ExpectedUnitType.CLAUSE
        if self.article_number:
            return ExpectedUnitType.ARTICLE
        return ExpectedUnitType.DOCUMENT


@dataclass(frozen=True)
class ResolvedCandidate:
    """A canonical unit confirmed by the read-only lookup (Plan 19 §4)."""

    node_id: str
    node_type: ExpectedUnitType
    canonical_label: str
    document_id: str
    document_number: str | None = None
    article_id: str | None = None
    article_number: str | None = None
    clause_id: str | None = None
    clause_number: str | None = None
    point_id: str | None = None
    point_label: str | None = None
    document_metadata: dict[str, Any] = field(default_factory=dict)

    def required_anchors(self) -> tuple[str, ...]:
        """Canonical anchors a rewritten query must preserve (Plan 19 §4)."""
        anchors: list[str] = []
        if self.document_number:
            anchors.append(self.document_number)
        if self.article_number:
            anchors.append(f"Điều {self.article_number}")
        if self.clause_number:
            anchors.append(f"Khoản {self.clause_number}")
        if self.point_label:
            anchors.append(f"Điểm {self.point_label}")
        return tuple(anchors)

    def to_clarification_candidate(self) -> ClarificationCandidate:
        return ClarificationCandidate(
            candidate_id=self.node_id,
            label=self.canonical_label,
            node_type=self.node_type.value,
            document_id=self.document_id,
            article_id=self.article_id,
            clause_id=self.clause_id,
            metadata={
                "document_number": self.document_number,
                "article_number": self.article_number,
                "clause_number": self.clause_number,
                "point_id": self.point_id,
                "point_label": self.point_label,
                "document_metadata": self.document_metadata or {},
            },
        )

    @classmethod
    def from_grounded_focus(cls, focus: GroundedFocus) -> "ResolvedCandidate":
        metadata = focus.document_metadata or {}
        node_type = ExpectedUnitType(focus.node_type)
        return cls(
            node_id=focus.node_id,
            node_type=node_type,
            canonical_label=focus.canonical_label,
            document_id=focus.document_id,
            document_number=metadata.get("document_number"),
            article_id=focus.article_id,
            article_number=metadata.get("article_number"),
            clause_id=focus.clause_id,
            clause_number=metadata.get("clause_number"),
            point_id=metadata.get("point_id"),
            point_label=metadata.get("point_label"),
            document_metadata=metadata,
        )

    @classmethod
    def from_clarification_candidate(
        cls, candidate: ClarificationCandidate
    ) -> "ResolvedCandidate":
        metadata = candidate.metadata or {}
        node_type = ExpectedUnitType(candidate.node_type or ExpectedUnitType.DOCUMENT)
        return cls(
            node_id=candidate.candidate_id,
            node_type=node_type,
            canonical_label=candidate.label,
            document_id=candidate.document_id or "",
            document_number=metadata.get("document_number"),
            article_id=candidate.article_id,
            article_number=metadata.get("article_number"),
            clause_id=candidate.clause_id,
            clause_number=metadata.get("clause_number"),
            point_id=metadata.get("point_id"),
            point_label=metadata.get("point_label"),
            document_metadata=metadata.get("document_metadata") or {},
        )


@dataclass(frozen=True)
class StandaloneResolution:
    """No context-dependent reference; retrieve the message verbatim."""

    reason_code: str = REASON_NO_REFERENCE_REQUIRED


@dataclass(frozen=True)
class ResolvedResolution:
    """A single canonical referent was resolved."""

    candidate: ResolvedCandidate
    is_anaphora: bool
    resolution_status: ResolutionStatus = ResolutionStatus.RESOLVED


@dataclass(frozen=True)
class ClarifyResolution:
    """The turn needs clarification (ambiguous or unresolved referent)."""

    mode: ClarificationMode
    resolution_status: ResolutionStatus
    reason_code: str
    question: str
    candidates: tuple[ClarificationCandidate, ...] = ()


@dataclass(frozen=True)
class CancelResolution:
    """The user cancelled an open clarification."""

    reason_code: str = REASON_USER_CANCELLED


ResolutionOutcome = (
    StandaloneResolution | ResolvedResolution | ClarifyResolution | CancelResolution
)
