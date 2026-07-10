"""Ontology Validator — Step 4 of the extraction pipeline.

This validator accepts canonical ontology labels only. The orchestrator maps
pre-writer extraction labels (`Entity`, `Concept`, `Action`) to
`LegalSubject`, `LegalConcept`, and `LegalAction` before Step 4 validation.
"""

from __future__ import annotations

GUIDES_WHITELIST: set[tuple[str, str]] = {
    ("Constitution", "Law"),
    ("Constitution", "Ordinance"),
    ("Law", "Decree"),
    ("Law", "Decision"),
    ("Law", "Circular"),
    ("Ordinance", "Decree"),
    ("Resolution", "Decree"),
    ("Decree", "Circular"),
    ("Decree", "Decision"),
    ("Decree", "JointCircular"),
    ("Decision", "Circular"),
}

LEGACY_RELATION_ALIASES: dict[str, str] = {
    "AMENDED_BY": "AMENDS",
    "REPEALED_BY": "REPEALS",
    "REPLACED_BY": "REPLACES",
    "IMPLEMENTED_BY": "GUIDES",
    "GUIDED_BY": "GUIDES",
    "REFERENCES": "REFERS_TO",
}

ONTOLOGY_LABEL_MAP: dict[str, str] = {
    "Entity": "LegalSubject",
    "Concept": "LegalConcept",
    "Action": "LegalAction",
}

PHASE1_PERSISTED_LABELS: set[str] = {
    "Document",
    "Issuer",
    "Chapter",
    "Article",
    "Clause",
    "Point",
    "LegalConcept",
    "LegalSubject",
    "LegalAction",
}

RUNTIME_ONLY_LABELS: set[str] = {"Obligation", "Right", "Condition", "Exception"}

RELATION_ENUM: set[str] = {
    "ISSUED_BY",
    "CONTAINS",
    "AMENDS",
    "REPEALS",
    "REPLACES",
    "GUIDES",
    "REFERS_TO",
    "DEFINES",
    "REGULATES",
    "REQUIRES",
}

CONSTRAINTS: dict[str, dict] = {
    "ISSUED_BY": {
        "valid_pairs": [("Document", "Issuer")],
        "no_self_loop": True,
    },
    "CONTAINS": {
        "valid_pairs": [
            ("Document", "Chapter"),
            ("Chapter", "Article"),
            ("Document", "Article"),
            ("Article", "Clause"),
            ("Clause", "Point"),
        ],
        "no_self_loop": True,
    },
    "AMENDS": {
        "valid_pairs": [
            ("Document", "Document"),
            ("Document", "Article"),
            ("Document", "Clause"),
            ("Article", "Document"),
            ("Article", "Article"),
            ("Article", "Clause"),
            ("Clause", "Document"),
            ("Clause", "Clause"),
            ("Clause", "Article"),
        ],
        "no_self_loop": True,
        "required_properties": ["effective_from"],
    },
    "REPEALS": {
        "valid_pairs": [
            ("Document", "Document"),
            ("Document", "Article"),
            ("Document", "Clause"),
        ],
        "no_self_loop": True,
        "required_properties": ["effective_from"],
    },
    "REPLACES": {
        "valid_pairs": [("Document", "Document")],
        "no_self_loop": True,
        "required_properties": ["effective_from"],
    },
    "GUIDES": {
        "valid_pairs": [("Document", "Document")],
        "rule": "guides_whitelist",
    },
    "REFERS_TO": {
        "valid_pairs": [
            ("Article", "Article"),
            ("Article", "Clause"),
            ("Article", "Point"),
            ("Article", "Document"),
            ("Clause", "Article"),
            ("Clause", "Clause"),
            ("Clause", "Point"),
            ("Clause", "Document"),
            ("Point", "Article"),
            ("Point", "Clause"),
            ("Point", "Point"),
            ("Point", "Document"),
        ],
        "required_properties": ["citation_text", "citation_type"],
    },
    "DEFINES": {
        "valid_pairs": [
            ("Article", "LegalConcept"),
            ("Clause", "LegalConcept"),
        ],
        "required_properties": ["confidence", "llm_model", "created_at"],
    },
    "REGULATES": {
        "valid_pairs": [
            ("Article", "LegalSubject"),
            ("Article", "LegalAction"),
            ("Clause", "LegalSubject"),
            ("Clause", "LegalAction"),
        ],
        "required_properties": ["confidence", "llm_model", "created_at"],
    },
    "REQUIRES": {
        "valid_pairs": [("LegalSubject", "LegalConcept")],
        "required_properties": ["confidence", "llm_model", "created_at"],
    },
}


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
