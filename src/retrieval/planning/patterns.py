"""Query-planning allowlists and provenance-free ontology pattern checks."""

from __future__ import annotations

from enum import Enum
from typing import TypeAlias

from src.shared.ontology.contract import (
    CONSTRAINTS,
    LEGACY_RELATION_ALIASES,
    PHASE1_PERSISTED_LABELS,
    PHASE1_RELATION_ENUM,
    RUNTIME_ONLY_LABELS,
)


MIN_PLAN_DEPTH = 2
MAX_PLAN_DEPTH = 3

QUERY_ANCHOR_LABELS = frozenset({"Article", "Clause"})
QUERY_TRAVERSAL_LABELS = frozenset(PHASE1_PERSISTED_LABELS)
DIRECT_CITABLE_TARGETS = frozenset({"Article", "Clause", "Point"})
SEMANTIC_LIFTABLE_TARGETS = frozenset({"LegalConcept", "LegalSubject", "LegalAction"})
QUERY_TARGET_LABELS = DIRECT_CITABLE_TARGETS | SEMANTIC_LIFTABLE_TARGETS
QUERY_PLANNABLE_RELATIONS = frozenset(PHASE1_RELATION_ENUM)


class QueryDirection(str, Enum):
    OUTGOING = "outgoing"
    INCOMING = "incoming"


def _closed_string_enum(name: str, values: frozenset[str]) -> type[Enum]:
    return Enum(name, {value: value for value in sorted(values)}, type=str)


QueryAnchorLabel: TypeAlias = _closed_string_enum(
    "QueryAnchorLabel", QUERY_ANCHOR_LABELS
)
QueryTraversalLabel: TypeAlias = _closed_string_enum(
    "QueryTraversalLabel", QUERY_TRAVERSAL_LABELS
)
QueryPlannableRelation: TypeAlias = _closed_string_enum(
    "QueryPlannableRelation", QUERY_PLANNABLE_RELATIONS
)


def validate_directed_step(
    *,
    current_label: str,
    relation: str,
    direction: str | QueryDirection,
    next_label: str,
) -> bool:
    """Validate only relation topology, without write-time provenance fields."""

    _validate_query_label(current_label)
    _validate_query_label(next_label)
    if relation in LEGACY_RELATION_ALIASES:
        raise ValueError(f"{relation} is a legacy relation alias")
    if relation not in QUERY_PLANNABLE_RELATIONS:
        raise ValueError(f"{relation} is not query-plannable")
    try:
        normalized_direction = QueryDirection(direction)
    except ValueError as exc:
        raise ValueError(f"Unsupported query-plan direction: {direction}") from exc

    if normalized_direction is QueryDirection.OUTGOING:
        canonical_head, canonical_tail = current_label, next_label
    else:
        canonical_head, canonical_tail = next_label, current_label

    if not _relation_allows(relation, canonical_head, canonical_tail):
        raise ValueError(
            f"{relation} does not allow canonical direction "
            f"{canonical_head} -> {canonical_tail}"
        )
    return True


def _validate_query_label(label: str) -> None:
    if label in RUNTIME_ONLY_LABELS:
        raise ValueError(f"Runtime-only label is not query-plannable: {label}")
    if label not in QUERY_TRAVERSAL_LABELS:
        raise ValueError(f"Unknown query traversal label: {label}")


def _relation_allows(relation: str, head_label: str, tail_label: str) -> bool:
    constraint = CONSTRAINTS[relation]
    valid_pairs = constraint.get("valid_pairs")
    if valid_pairs is not None:
        return (head_label, tail_label) in valid_pairs
    return head_label in constraint.get(
        "allowed_head", ()
    ) and tail_label in constraint.get("allowed_tail", ())
