"""Record-level consistency checks before confidence scoring and decision gate."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


TEMPORAL_RELATIONS = {"AMENDS", "REPEALS", "REPLACES"}
DOCUMENT_RELATIONS = {"GUIDES"}


@dataclass(frozen=True, slots=True)
class RecordConsistencyResult:
    valid: bool
    review_reason: str | None = None
    blocking: bool = False
    hard_fail: bool = False
    error: str | None = None


def validate_record_relation(
    *,
    relation_type: str,
    head_id: str,
    tail_id: str,
    properties: dict | None,
    known_entity_ids: Iterable[str],
    ontology_valid: bool,
    head_type: str | None = None,
    tail_type: str | None = None,
) -> RecordConsistencyResult:
    """Validate consistency that can be checked before graph payload assembly."""
    if not ontology_valid:
        return RecordConsistencyResult(valid=False, hard_fail=True, error="ontology_invalid")

    known_ids = set(known_entity_ids)
    props = properties or {}

    if relation_type in TEMPORAL_RELATIONS:
        if head_id == tail_id:
            return RecordConsistencyResult(
                valid=False,
                hard_fail=True,
                error=f"{relation_type} self-loop is not allowed",
            )
        if not props.get("effective_from"):
            return RecordConsistencyResult(
                valid=False,
                review_reason="temporal_metadata_incomplete",
                blocking=True,
                error=f"{relation_type} missing effective_from",
            )

    if relation_type in DOCUMENT_RELATIONS and (head_type != "Document" or tail_type != "Document"):
        return RecordConsistencyResult(
            valid=False,
            review_reason="guides_doc_type_unknown",
            blocking=True,
            error="GUIDES requires resolvable document endpoints",
        )

    missing = [entity_id for entity_id in (head_id, tail_id) if entity_id not in known_ids]
    if missing:
        if relation_type in {"REFERS_TO", *TEMPORAL_RELATIONS, *DOCUMENT_RELATIONS}:
            return RecordConsistencyResult(
                valid=False,
                review_reason="missing_external_document_registry",
                blocking=True,
                error=f"Unresolved external endpoint(s): {missing}",
            )
        return RecordConsistencyResult(
            valid=False,
            hard_fail=True,
            error=f"Unresolved local endpoint(s): {missing}",
        )

    return RecordConsistencyResult(valid=True)
