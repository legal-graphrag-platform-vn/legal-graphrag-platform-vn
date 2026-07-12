"""Ontology Validator — Step 4 of the extraction pipeline.

All constants are imported from shared.ontology.contract (single source of truth).
This validator accepts canonical ontology labels only. The orchestrator maps
pre-writer extraction labels (`Entity`, `Concept`, `Action`) to
`LegalSubject`, `LegalConcept`, and `LegalAction` before Step 4 validation.
"""

from __future__ import annotations

from datetime import datetime

from src.shared.ontology.contract import (
    CONSTRAINTS,
    GUIDES_WHITELIST,
    LEGACY_RELATION_ALIASES,
    ONTOLOGY_LABEL_MAP as ONTOLOGY_LABEL_MAP,
    PHASE1_PERSISTED_LABELS as PHASE1_PERSISTED_LABELS,
    RELATION_ENUM as RELATION_ENUM,
    RUNTIME_ONLY_LABELS as RUNTIME_ONLY_LABELS,
)


def validate_relation(
    head_type: str,
    relation: str,
    tail_type: str,
    *,
    head_id: str | None = None,
    tail_id: str | None = None,
    properties: dict | None = None,
    head_doc_type: str | None = None,
    tail_doc_type: str | None = None,
) -> tuple[bool, str | None]:
    constraint = CONSTRAINTS.get(relation)
    if not constraint:
        canonical = LEGACY_RELATION_ALIASES.get(relation)
        if canonical:
            return False, f"Legacy relation type {relation}; use canonical {canonical}"
        return False, (
            f"Unknown relation type: {relation}. "
            "Check RELATION_ENUM == set(CONSTRAINTS.keys())"
        )

    valid_pairs = constraint.get("valid_pairs")
    if valid_pairs and (head_type, tail_type) not in valid_pairs:
        return False, f"Invalid pair: {head_type}-[{relation}]->{tail_type}"

    allowed_tail = constraint.get("allowed_tail")
    if allowed_tail and tail_type not in allowed_tail:
        return False, f"Invalid tail type for {relation}: {tail_type} not in {allowed_tail}"

    if constraint.get("no_self_loop") and head_id is not None and tail_id is not None:
        if head_id == tail_id:
            return False, f"Self-loop not allowed for {relation}"

    required_props = constraint.get("required_properties", [])
    if required_props:
        props = properties or {}
        missing = [p for p in required_props if p not in props or props[p] is None or props[p] == ""]
        if missing:
            return False, f"Missing required properties for {relation}: {missing}"

    for key, expected in constraint.get("property_types", {}).items():
        value = (properties or {}).get(key)
        if value is None:
            continue
        if expected == "float" and (isinstance(value, bool) or not isinstance(value, (int, float))):
            return False, f"Invalid property type for {relation}.{key}: expected float"
        if expected == "string" and not isinstance(value, str):
            return False, f"Invalid property type for {relation}.{key}: expected string"
        if expected == "datetime":
            if not isinstance(value, str):
                return False, f"Invalid property type for {relation}.{key}: expected datetime"
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                return False, f"Invalid property type for {relation}.{key}: expected datetime"
            if parsed.tzinfo is None:
                return False, f"Invalid property type for {relation}.{key}: timezone required"

    if relation == "REFERS_TO":
        citation_type = (properties or {}).get("citation_type")
        if citation_type not in {"DIRECT", "INDIRECT", "RANGE"}:
            return False, f"Invalid citation_type for REFERS_TO: {citation_type}"

    if relation == "GUIDES":
        if head_doc_type is None or tail_doc_type is None:
            return False, "GUIDES requires head_doc_type and tail_doc_type"
        if (head_doc_type, tail_doc_type) not in GUIDES_WHITELIST:
            return False, f"GUIDES does not allow {head_doc_type} -> {tail_doc_type}"

    return True, None
