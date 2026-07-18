"""Shared ontology contract — single source of truth for all constants.

All validators (write-time and extraction-time) import from here.
No constants should be duplicated outside this file.
"""

from __future__ import annotations

from typing import Any


ONTOLOGY_VERSION = "1.6.0"


DOCUMENT_TYPES: set[str] = {
    "Constitution",
    "Law",
    "Ordinance",
    "Resolution",
    "Decree",
    "Decision",
    "Circular",
    "JointCircular",
}

DOCUMENT_LEGAL_STATUSES: set[str] = {
    "ACTIVE",
    "NOT_YET_EFFECTIVE",
    "PARTIALLY_EFFECTIVE",
    "REPLACED",
    "REPEALED",
    "EXPIRED",
}

CONTENT_LEGAL_STATUSES: set[str] = {
    "ACTIVE",
    "AMENDED",
    "REPEALED",
}

ISSUER_BRANCHES: set[str] = {
    "LEGISLATIVE",
    "EXECUTIVE",
    "JUDICIAL",
    "OTHER",
}

CITATION_TYPES: set[str] = {
    "DIRECT",
    "INDIRECT",
    "RANGE",
}

REFERENCE_EXTRACTION_METHODS: set[str] = {
    "RULE",
    "ENTITY_LINKING",
    "LLM",
}

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
    "HAS_CONDITION",
    "HAS_EXCEPTION",
}

PHASE1_RELATION_ENUM: set[str] = RELATION_ENUM - {"HAS_CONDITION", "HAS_EXCEPTION"}

CONSTRAINTS: dict[str, dict[str, Any]] = {
    "ISSUED_BY": {
        "valid_pairs": [("Document", "Issuer")],
        "no_self_loop": True,
    },
    "CONTAINS": {
        "valid_pairs": [
            ("Document", "Chapter"),
            ("Document", "Article"),
            ("Chapter", "Article"),
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
        "allowed_head": ["Article", "Clause", "Point"],
        "allowed_tail": ["Article", "Clause", "Point", "Document"],
        "no_self_loop": False,
        "required_properties": [
            "citation_text",
            "citation_type",
            "extraction_method",
            "created_at",
            "reference_bundle_id",
            "reference_target_count",
        ],
        "required_properties_by_extraction_method": {
            "RULE": [
                "resolver_name",
                "resolver_version",
                "source_unit_id",
                "source_char_start",
                "source_char_end",
            ],
            "ENTITY_LINKING": [
                "linker_name",
                "linker_version",
                "source_unit_id",
                "source_char_start",
                "source_char_end",
            ],
            "LLM": ["confidence", "llm_model", "checkpoint_id"],
        },
        "property_types": {
            "confidence": "float",
            "llm_model": "string",
            "created_at": "datetime",
            "citation_text": "string",
            "citation_type": "string",
            "extraction_method": "string",
            "reference_bundle_id": "string",
            "reference_target_count": "integer",
            "resolver_name": "string",
            "resolver_version": "string",
            "linker_name": "string",
            "linker_version": "string",
            "source_unit_id": "string",
            "source_char_start": "integer",
            "source_char_end": "integer",
            "checkpoint_id": "string",
        },
        "property_enums": {
            "citation_type": CITATION_TYPES,
            "extraction_method": REFERENCE_EXTRACTION_METHODS,
        },
    },
    "DEFINES": {
        "allowed_head": ["Article", "Clause"],
        "allowed_tail": ["LegalConcept"],
        "required_properties": ["confidence", "llm_model", "created_at"],
    },
    "REGULATES": {
        "allowed_head": ["Article", "Clause"],
        "allowed_tail": ["LegalSubject", "LegalAction"],
        "required_properties": ["confidence", "llm_model", "created_at"],
    },
    "REQUIRES": {
        "allowed_head": ["LegalSubject"],
        "allowed_tail": ["LegalConcept"],
        "no_self_loop": True,
        "required_properties": ["confidence", "llm_model", "created_at"],
    },
    "HAS_CONDITION": {
        "allowed_head": ["LegalAction", "Obligation", "Right"],
        "allowed_tail": ["Condition"],
        "no_self_loop": True,
        "required_properties": ["confidence", "llm_model", "created_at"],
    },
    "HAS_EXCEPTION": {
        "allowed_head": ["Article", "Clause", "LegalAction"],
        "allowed_tail": ["Exception"],
        "no_self_loop": True,
        "required_properties": ["confidence", "llm_model", "created_at"],
    },
}

# Node required fields per type (for application-layer enforcement on Neo4j Community)
NODE_REQUIRED_FIELDS: dict[str, list[str]] = {
    "Document": [
        "id",
        "doc_type",
        "number",
        "normative",
        "legal_status",
        "effective_from",
        "issuer_name",
    ],
    "Issuer": ["id", "name", "branch"],
    "Chapter": ["id", "number", "title"],
    "Article": [
        "id",
        "number",
        "title",
        "content_raw",
        "effective_from",
        "legal_status",
    ],
    "Clause": ["id", "number", "content_raw", "effective_from", "legal_status"],
    "Point": ["id", "label", "content_raw"],
    "LegalConcept": ["id", "name"],
    "LegalSubject": ["id", "name"],
    "LegalAction": ["id", "name"],
}

# Node field enum constraints
NODE_ENUMS: dict[str, dict[str, set[str]]] = {
    "Document": {
        "doc_type": DOCUMENT_TYPES,
        "legal_status": DOCUMENT_LEGAL_STATUSES,
    },
    "Issuer": {
        "branch": ISSUER_BRANCHES,
    },
    "Article": {
        "legal_status": CONTENT_LEGAL_STATUSES,
    },
    "Clause": {
        "legal_status": CONTENT_LEGAL_STATUSES,
    },
}
