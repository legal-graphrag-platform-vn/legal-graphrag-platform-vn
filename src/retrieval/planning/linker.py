"""Deterministic structural mention parsing and endpoint binding."""

from __future__ import annotations

import re
import unicodedata
from enum import Enum
from typing import Any, Literal, Mapping, Self, TypeAlias

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from src.retrieval.errors import RetrievalOutputError
from src.retrieval.config import EndpointLinkerConfig
from src.retrieval.models import RetrievalFilters, RetrievedUnit
from src.retrieval.planning.models import BoundEndpoint, PlanReasonCode
from src.retrieval.planning.patterns import QUERY_TRAVERSAL_LABELS
from src.retrieval.ports import (
    FullTextChannelPort,
    StructuralEndpointLookupPort,
    VectorChannelPort,
)


_NUMBER = r"[0-9]+[A-Za-z]?"
_POINT = r"[A-Za-zĐđ]"
_DOCUMENT_NUMBER = r"[0-9A-Za-zĐđ./-]+"
_POINT_PATTERN = re.compile(
    rf"^điểm\s+(?P<point>{_POINT})\s+khoản\s+(?P<clause>{_NUMBER})"
    rf"\s+điều\s+(?P<article>{_NUMBER})$",
    re.IGNORECASE,
)
_CLAUSE_PATTERN = re.compile(
    rf"^khoản\s+(?P<clause>{_NUMBER})\s+điều\s+(?P<article>{_NUMBER})$",
    re.IGNORECASE,
)
_ARTICLE_PATTERN = re.compile(
    rf"^điều\s+(?P<article>{_NUMBER})$",
    re.IGNORECASE,
)
_DOCUMENT_PATTERN = re.compile(
    rf"^(?:luật|nghị\s+định|thông\s+tư|quyết\s+định|nghị\s+quyết|"
    rf"pháp\s+lệnh|hiến\s+pháp|văn\s+bản)(?:\s+số)?\s+"
    rf"(?P<document>{_DOCUMENT_NUMBER})$",
    re.IGNORECASE,
)
_LOOKUP_LIMIT = 20

StructuralLabel: TypeAlias = Literal["Document", "Article", "Clause", "Point"]


class EndpointRole(str, Enum):
    ANCHOR = "anchor"
    TARGET = "target"


class EndpointResolutionStatus(str, Enum):
    RESOLVED = "resolved"
    UNBOUND = "unbound"
    AMBIGUOUS = "ambiguous"


class _ImmutableContract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class StructuralReference(_ImmutableContract):
    label: StructuralLabel
    document_number: str | None = None
    article_number: str | None = None
    clause_number: str | None = None
    point_label: str | None = None

    @model_validator(mode="after")
    def validate_hierarchy_shape(self) -> Self:
        required = {
            "Document": (self.document_number,),
            "Article": (self.article_number,),
            "Clause": (self.article_number, self.clause_number),
            "Point": (self.article_number, self.clause_number, self.point_label),
        }
        if self.label not in required or any(
            value is None for value in required[self.label]
        ):
            raise ValueError("Structural reference hierarchy fields are inconsistent")
        return self


class StructuralEndpointCandidate(_ImmutableContract):
    node_id: str
    label: StructuralLabel
    document_id: str

    _node_id_not_blank = field_validator("node_id")(
        lambda value: _non_blank(value, "candidate node ID")
    )
    _document_id_not_blank = field_validator("document_id")(
        lambda value: _non_blank(value, "candidate document ID")
    )


class StructuralEndpointResolution(_ImmutableContract):
    role: EndpointRole
    status: EndpointResolutionStatus
    mention_text: str
    reference: StructuralReference | None = None
    candidates: tuple[StructuralEndpointCandidate, ...] = ()
    bound_endpoint: BoundEndpoint | None = None
    reason_code: PlanReasonCode | None = None
    message: str

    @model_validator(mode="after")
    def validate_resolution_state(self) -> Self:
        if self.status is EndpointResolutionStatus.RESOLVED:
            if (
                len(self.candidates) != 1
                or self.bound_endpoint is None
                or self.reason_code is not None
            ):
                raise ValueError("Resolved endpoint requires one bound candidate")
        elif self.bound_endpoint is not None or self.reason_code is None:
            raise ValueError("Unresolved endpoint requires a reason and no binding")
        return self


class SemanticEndpointCandidate(_ImmutableContract):
    node_id: str
    label: Literal["Article", "Clause", "Point"]
    document_id: str
    score: float
    retrieval_sources: tuple[Literal["vector", "fulltext"], ...]


class SemanticEndpointResolution(_ImmutableContract):
    role: EndpointRole
    status: EndpointResolutionStatus
    mention_text: str
    candidates: tuple[SemanticEndpointCandidate, ...] = ()
    bound_endpoint: BoundEndpoint | None = None
    reason_code: PlanReasonCode | None = None
    message: str

    @model_validator(mode="after")
    def validate_resolution_state(self) -> Self:
        if self.status is EndpointResolutionStatus.RESOLVED:
            if not self.candidates or self.bound_endpoint is None or self.reason_code:
                raise ValueError("Resolved semantic endpoint requires a binding")
        elif self.bound_endpoint is not None or self.reason_code is None:
            raise ValueError("Unresolved semantic endpoint requires a reason")
        return self


EndpointResolution: TypeAlias = (
    StructuralEndpointResolution | SemanticEndpointResolution
)


class StructuralEndpointResolver:
    def __init__(self, lookup: StructuralEndpointLookupPort) -> None:
        self._lookup = lookup

    def resolve(
        self,
        *,
        mention_text: str,
        role: EndpointRole | str,
        expected_label: str | None,
        filters: RetrievalFilters,
    ) -> StructuralEndpointResolution:
        normalized_role = EndpointRole(role)
        normalized_mention = _normalize_mention(mention_text)
        reference = parse_structural_reference(normalized_mention)
        if reference is None:
            return self._unbound(
                normalized_role,
                normalized_mention,
                None,
                "Unsupported structural mention",
            )
        if expected_label is not None:
            if expected_label not in QUERY_TRAVERSAL_LABELS:
                return self._unbound(
                    normalized_role,
                    normalized_mention,
                    reference,
                    "Expected label is not query-plannable",
                )
            if expected_label != reference.label:
                return self._unbound(
                    normalized_role,
                    normalized_mention,
                    reference,
                    "Mention label differs from expected label",
                )
        if not filters.document_ids:
            return self._ambiguous(
                normalized_role,
                normalized_mention,
                reference,
                (),
                "Document scope is required for structural binding",
            )

        rows = self._lookup.lookup_structural_endpoints(
            label=reference.label,
            document_number=reference.document_number,
            article_number=reference.article_number,
            clause_number=reference.clause_number,
            point_label=reference.point_label,
            filters=filters,
            limit=_LOOKUP_LIMIT,
        )
        candidates = self._validated_candidates(rows, reference, filters)
        if not candidates:
            return self._unbound(
                normalized_role,
                normalized_mention,
                reference,
                "No structural match",
            )
        if len(candidates) > 1:
            return self._ambiguous(
                normalized_role,
                normalized_mention,
                reference,
                candidates,
                "Structural mention matched multiple canonical nodes",
            )
        candidate = candidates[0]
        return StructuralEndpointResolution(
            role=normalized_role,
            status=EndpointResolutionStatus.RESOLVED,
            mention_text=normalized_mention,
            reference=reference,
            candidates=candidates,
            bound_endpoint=BoundEndpoint(
                mention_text=normalized_mention,
                node_id=candidate.node_id,
                label=candidate.label,
                resolution_method="STRUCTURAL",
            ),
            reason_code=None,
            message="Structural endpoint resolved uniquely",
        )

    @staticmethod
    def _validated_candidates(
        rows: list[Mapping[str, Any]],
        reference: StructuralReference,
        filters: RetrievalFilters,
    ) -> tuple[StructuralEndpointCandidate, ...]:
        candidates_by_id: dict[str, StructuralEndpointCandidate] = {}
        for row in rows:
            try:
                candidate = StructuralEndpointCandidate.model_validate(row)
            except (TypeError, ValueError) as exc:
                raise RetrievalOutputError(
                    f"Malformed structural endpoint candidate: {exc}"
                ) from exc
            if candidate.label != reference.label:
                raise RetrievalOutputError(
                    "Structural endpoint candidate label does not match reference"
                )
            if candidate.document_id not in filters.document_ids:
                raise RetrievalOutputError(
                    "Structural endpoint candidate is outside document scope"
                )
            existing = candidates_by_id.get(candidate.node_id)
            if existing is not None and existing != candidate:
                raise RetrievalOutputError(
                    "Conflicting structural endpoint rows share one node ID"
                )
            candidates_by_id[candidate.node_id] = candidate
        return tuple(candidates_by_id[node_id] for node_id in sorted(candidates_by_id))

    @staticmethod
    def _unbound(
        role: EndpointRole,
        mention_text: str,
        reference: StructuralReference | None,
        message: str,
    ) -> StructuralEndpointResolution:
        reason = (
            PlanReasonCode.UNBOUND_ANCHOR
            if role is EndpointRole.ANCHOR
            else PlanReasonCode.UNBOUND_TARGET
        )
        return StructuralEndpointResolution(
            role=role,
            status=EndpointResolutionStatus.UNBOUND,
            mention_text=mention_text,
            reference=reference,
            reason_code=reason,
            message=message,
        )

    @staticmethod
    def _ambiguous(
        role: EndpointRole,
        mention_text: str,
        reference: StructuralReference,
        candidates: tuple[StructuralEndpointCandidate, ...],
        message: str,
    ) -> StructuralEndpointResolution:
        reason = (
            PlanReasonCode.AMBIGUOUS_ANCHOR
            if role is EndpointRole.ANCHOR
            else PlanReasonCode.AMBIGUOUS_TARGET
        )
        return StructuralEndpointResolution(
            role=role,
            status=EndpointResolutionStatus.AMBIGUOUS,
            mention_text=mention_text,
            reference=reference,
            candidates=candidates,
            reason_code=reason,
            message=message,
        )


class SemanticEndpointResolver:
    def __init__(
        self,
        *,
        vector: VectorChannelPort,
        fulltext: FullTextChannelPort,
        config: EndpointLinkerConfig,
    ) -> None:
        self._vector = vector
        self._fulltext = fulltext
        self._config = config

    def resolve(
        self,
        *,
        mention_text: str,
        role: EndpointRole | str,
        expected_label: str | None,
        filters: RetrievalFilters,
    ) -> SemanticEndpointResolution:
        normalized_role = EndpointRole(role)
        normalized_mention = _normalize_mention(mention_text)
        if expected_label not in {"Article", "Clause", "Point"}:
            return self._unbound(
                normalized_role,
                normalized_mention,
                (),
                "Expected label is not supported by legal-unit retrieval channels",
            )
        candidate_k = self._candidate_k(normalized_role)
        channels = {
            "vector": self._vector.retrieve(
                normalized_mention,
                filters=filters,
                top_k=candidate_k,
            ),
            "fulltext": self._fulltext.retrieve(
                normalized_mention,
                filters=filters,
                top_k=candidate_k,
            ),
        }
        self._validate_channel_scope(channels, filters)
        candidates = _fuse_semantic_candidates(
            channels,
            expected_label=expected_label,
            rrf_k=self._config.rrf_k,
            top_n=candidate_k,
        )
        if not candidates or candidates[0].score < self._min_score(normalized_role):
            return self._unbound(
                normalized_role,
                normalized_mention,
                candidates,
                "Semantic candidates are below the calibrated score threshold",
            )
        if len(candidates) > 1 and candidates[0].score - candidates[
            1
        ].score < self._min_margin(normalized_role):
            return self._ambiguous(
                normalized_role,
                normalized_mention,
                candidates,
                "Semantic candidates do not meet the calibrated score margin",
            )
        top = candidates[0]
        method = "VECTOR_RRF" if "vector" in top.retrieval_sources else "FULLTEXT"
        return SemanticEndpointResolution(
            role=normalized_role,
            status=EndpointResolutionStatus.RESOLVED,
            mention_text=normalized_mention,
            candidates=candidates,
            bound_endpoint=BoundEndpoint(
                mention_text=normalized_mention,
                node_id=top.node_id,
                label=top.label,
                resolution_method=method,
                score=top.score,
            ),
            message="Semantic endpoint resolved above calibrated thresholds",
        )

    @staticmethod
    def _validate_channel_scope(
        channels: Mapping[str, list[RetrievedUnit]],
        filters: RetrievalFilters,
    ) -> None:
        for units in channels.values():
            for unit in units:
                if (
                    filters.document_ids
                    and unit.document_id not in filters.document_ids
                ):
                    raise RetrievalOutputError(
                        "Semantic endpoint candidate is outside document scope"
                    )

    def _candidate_k(self, role: EndpointRole) -> int:
        return (
            self._config.anchor_candidate_k
            if role is EndpointRole.ANCHOR
            else self._config.target_candidate_k
        )

    def _min_score(self, role: EndpointRole) -> float:
        return (
            self._config.anchor_min_score
            if role is EndpointRole.ANCHOR
            else self._config.target_min_score
        )

    def _min_margin(self, role: EndpointRole) -> float:
        return (
            self._config.anchor_min_margin
            if role is EndpointRole.ANCHOR
            else self._config.target_min_margin
        )

    @staticmethod
    def _unbound(
        role: EndpointRole,
        mention_text: str,
        candidates: tuple[SemanticEndpointCandidate, ...],
        message: str,
    ) -> SemanticEndpointResolution:
        return SemanticEndpointResolution(
            role=role,
            status=EndpointResolutionStatus.UNBOUND,
            mention_text=mention_text,
            candidates=candidates,
            reason_code=(
                PlanReasonCode.UNBOUND_ANCHOR
                if role is EndpointRole.ANCHOR
                else PlanReasonCode.UNBOUND_TARGET
            ),
            message=message,
        )

    @staticmethod
    def _ambiguous(
        role: EndpointRole,
        mention_text: str,
        candidates: tuple[SemanticEndpointCandidate, ...],
        message: str,
    ) -> SemanticEndpointResolution:
        return SemanticEndpointResolution(
            role=role,
            status=EndpointResolutionStatus.AMBIGUOUS,
            mention_text=mention_text,
            candidates=candidates,
            reason_code=(
                PlanReasonCode.AMBIGUOUS_ANCHOR
                if role is EndpointRole.ANCHOR
                else PlanReasonCode.AMBIGUOUS_TARGET
            ),
            message=message,
        )


class EndpointLinker:
    def __init__(
        self,
        *,
        structural: StructuralEndpointResolver,
        semantic: SemanticEndpointResolver,
    ) -> None:
        self._structural = structural
        self._semantic = semantic

    def resolve(
        self,
        *,
        mention_text: str,
        role: EndpointRole | str,
        expected_label: str | None,
        filters: RetrievalFilters,
    ) -> EndpointResolution:
        if parse_structural_reference(mention_text) is not None:
            return self._structural.resolve(
                mention_text=mention_text,
                role=role,
                expected_label=expected_label,
                filters=filters,
            )
        return self._semantic.resolve(
            mention_text=mention_text,
            role=role,
            expected_label=expected_label,
            filters=filters,
        )


def _fuse_semantic_candidates(
    channels: Mapping[str, list[RetrievedUnit]],
    *,
    expected_label: str,
    rrf_k: int,
    top_n: int,
) -> tuple[SemanticEndpointCandidate, ...]:
    direct_units: dict[str, RetrievedUnit] = {}
    for units in channels.values():
        for unit in units:
            if unit.label == expected_label:
                direct_units.setdefault(unit.id, unit)

    scores = {unit_id: 0.0 for unit_id in direct_units}
    sources: dict[str, set[str]] = {unit_id: set() for unit_id in direct_units}
    for source, units in sorted(channels.items()):
        for rank, unit in enumerate(units, start=1):
            recipients = _semantic_score_recipients(
                unit,
                expected_label=expected_label,
                direct_units=direct_units,
            )
            for unit_id in recipients:
                scores[unit_id] += 1.0 / (rrf_k + rank)
                sources[unit_id].add(source)

    ordered_ids = sorted(scores, key=lambda unit_id: (-scores[unit_id], unit_id))
    return tuple(
        SemanticEndpointCandidate(
            node_id=unit_id,
            label=direct_units[unit_id].label,
            document_id=direct_units[unit_id].document_id,
            score=scores[unit_id],
            retrieval_sources=tuple(sorted(sources[unit_id])),
        )
        for unit_id in ordered_ids[:top_n]
    )


def _semantic_score_recipients(
    unit: RetrievedUnit,
    *,
    expected_label: str,
    direct_units: Mapping[str, RetrievedUnit],
) -> tuple[str, ...]:
    if unit.id in direct_units:
        return (unit.id,)
    if expected_label == "Clause" and unit.label == "Article":
        return tuple(
            candidate.id
            for candidate in direct_units.values()
            if candidate.article_id == unit.id
        )
    if expected_label == "Article" and unit.label == "Clause":
        return (unit.article_id,) if unit.article_id in direct_units else ()
    return ()


def parse_structural_reference(mention_text: str) -> StructuralReference | None:
    normalized = _normalize_mention(mention_text)
    patterns: tuple[tuple[StructuralLabel, re.Pattern[str]], ...] = (
        ("Point", _POINT_PATTERN),
        ("Clause", _CLAUSE_PATTERN),
        ("Article", _ARTICLE_PATTERN),
        ("Document", _DOCUMENT_PATTERN),
    )
    for label, pattern in patterns:
        match = pattern.fullmatch(normalized)
        if match is None:
            continue
        values = match.groupdict()
        return StructuralReference(
            label=label,
            document_number=_uppercase(values.get("document")),
            article_number=_casefold(values.get("article")),
            clause_number=_casefold(values.get("clause")),
            point_label=_casefold(values.get("point")),
        )
    return None


def _normalize_mention(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).strip().split())


def _casefold(value: str | None) -> str | None:
    return value.casefold() if value is not None else None


def _uppercase(value: str | None) -> str | None:
    return value.upper() if value is not None else None


def _non_blank(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be blank")
    return normalized
