"""Central ontology validation for write-time enforcement.

This module is intentionally dependency-free so it can be used in tests and
early pipeline scaffolding without requiring the full application stack.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Mapping, Sequence


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
        "required_properties": ["citation_text", "citation_type"],
        "property_enums": {"citation_type": CITATION_TYPES},
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

_VALIDATION_TOKEN = object()


class GraphValidationError(ValueError):
    """Raised when one or more nodes or relations violate the ontology."""

    def __init__(self, errors: Sequence[str]) -> None:
        self.errors = list(errors)
        super().__init__("; ".join(self.errors))


@dataclass(frozen=True, slots=True)
class ValidatedNode:
    node_type: str
    id: str
    properties: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ValidatedRelation:
    head_id: str
    relation_type: str
    tail_id: str
    head_type: str
    tail_type: str
    properties: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ValidatedGraphPayload:
    nodes: tuple[ValidatedNode, ...]
    relations: tuple[ValidatedRelation, ...]
    validation_token: object

    @property
    def node_index(self) -> dict[str, ValidatedNode]:
        return {node.id: node for node in self.nodes}


class OntologyValidator:
    """Validate graph payloads against the frozen ontology."""

    def validate_document(self, document: Mapping[str, Any]) -> ValidatedNode:
        return self._validate_node(
            document,
            node_type="Document",
            required_fields=("id", "doc_type", "number", "normative", "legal_status", "effective_from", "issuer_name"),
            enum_fields={"doc_type": DOCUMENT_TYPES, "legal_status": DOCUMENT_LEGAL_STATUSES},
        )

    def validate_issuer(self, issuer: Mapping[str, Any]) -> ValidatedNode:
        return self._validate_node(
            issuer,
            node_type="Issuer",
            required_fields=("id", "name", "branch"),
            enum_fields={"branch": ISSUER_BRANCHES},
        )

    def validate_chapter(self, chapter: Mapping[str, Any]) -> ValidatedNode:
        return self._validate_node(
            chapter,
            node_type="Chapter",
            required_fields=("id", "number", "title"),
        )

    def validate_article(self, article: Mapping[str, Any]) -> ValidatedNode:
        return self._validate_node(
            article,
            node_type="Article",
            required_fields=("id", "number", "content_raw", "effective_from", "legal_status"),
            enum_fields={"legal_status": CONTENT_LEGAL_STATUSES},
        )

    def validate_clause(self, clause: Mapping[str, Any]) -> ValidatedNode:
        return self._validate_node(
            clause,
            node_type="Clause",
            required_fields=("id", "number", "content_raw", "effective_from", "legal_status"),
            enum_fields={"legal_status": CONTENT_LEGAL_STATUSES},
        )

    def validate_point(self, point: Mapping[str, Any]) -> ValidatedNode:
        return self._validate_node(
            point,
            node_type="Point",
            required_fields=("id", "label", "content_raw"),
        )

    def validate_semantic_node(self, node: Mapping[str, Any], node_type: str) -> ValidatedNode:
        return self._validate_node(
            node,
            node_type=node_type,
            required_fields=("id", "name"),
        )

    def validate_relation(
        self,
        head_type: str,
        relation_type: str,
        tail_type: str,
        *,
        properties: Mapping[str, Any] | None = None,
        head_doc_type: str | None = None,
        tail_doc_type: str | None = None,
        head_id: str | None = None,
        tail_id: str | None = None,
    ) -> tuple[bool, str | None]:
        if relation_type not in RELATION_ENUM:
            canonical = LEGACY_RELATION_ALIASES.get(relation_type)
            if canonical:
                return False, f"Legacy relation type {relation_type}; use canonical {canonical}"
            return False, f"Unknown relation type: {relation_type}"

        constraint = CONSTRAINTS[relation_type]
        properties = dict(properties or {})

        if constraint.get("no_self_loop") and head_id is not None and tail_id is not None and head_id == tail_id:
            return False, f"{relation_type} does not allow self-loops"

        required_properties = constraint.get("required_properties", [])
        missing_properties = [key for key in required_properties if key not in properties or properties[key] in (None, "")]
        if missing_properties:
            return False, f"{relation_type} requires properties: {', '.join(missing_properties)}"

        for key, allowed_values in constraint.get("property_enums", {}).items():
            value = properties.get(key)
            if value is not None and value not in allowed_values:
                return False, f"{relation_type}.{key} must be one of: {', '.join(sorted(allowed_values))}"

        valid_pairs = constraint.get("valid_pairs")
        if valid_pairs is not None and (head_type, tail_type) not in valid_pairs:
            return False, f"{relation_type} does not allow {head_type} -> {tail_type}"

        allowed_head = constraint.get("allowed_head")
        if allowed_head is not None and head_type not in allowed_head:
            return False, f"{relation_type} does not allow head type {head_type}"

        allowed_tail = constraint.get("allowed_tail")
        if allowed_tail is not None and tail_type not in allowed_tail:
            return False, f"{relation_type} does not allow tail type {tail_type}"

        if relation_type == "GUIDES":
            if head_type != "Document" or tail_type != "Document":
                return False, "GUIDES only supports Document -> Document"
            if not head_doc_type or not tail_doc_type:
                return False, "GUIDES requires head_doc_type and tail_doc_type"
            if (head_doc_type, tail_doc_type) not in GUIDES_WHITELIST:
                return False, f"GUIDES does not allow {head_doc_type} -> {tail_doc_type}"

        return True, None

    def validate_graph_payload(self, payload: Mapping[str, Any]) -> ValidatedGraphPayload:
        errors: list[str] = []
        nodes: list[ValidatedNode] = []
        node_index: dict[str, ValidatedNode] = {}

        for raw_node in payload.get("nodes", []):
            node_type = raw_node.get("type")
            try:
                if node_type == "Document":
                    node = self.validate_document(raw_node)
                elif node_type == "Issuer":
                    node = self.validate_issuer(raw_node)
                elif node_type == "Chapter":
                    node = self.validate_chapter(raw_node)
                elif node_type == "Article":
                    node = self.validate_article(raw_node)
                elif node_type == "Clause":
                    node = self.validate_clause(raw_node)
                elif node_type == "Point":
                    node = self.validate_point(raw_node)
                elif node_type in RUNTIME_ONLY_LABELS:
                    raise GraphValidationError([f"Runtime-only node type is not Phase 1 persistent: {node_type}"])
                elif node_type in {"LegalConcept", "LegalSubject", "LegalAction"}:
                    node = self.validate_semantic_node(raw_node, node_type)
                else:
                    raise GraphValidationError([f"Unsupported node type: {node_type}"])
            except GraphValidationError as exc:
                errors.extend(exc.errors)
                continue

            if node.id in node_index:
                errors.append(f"Duplicate node id: {node.id}")
                continue

            nodes.append(node)
            node_index[node.id] = node

        relations: list[ValidatedRelation] = []
        for raw_relation in payload.get("relations", []):
            head_id = raw_relation.get("head_id")
            tail_id = raw_relation.get("tail_id")
            relation_type = raw_relation.get("type")
            properties = dict(raw_relation.get("properties") or {})

            if head_id not in node_index:
                errors.append(f"Unknown relation head_id: {head_id}")
                continue
            if tail_id not in node_index:
                errors.append(f"Unknown relation tail_id: {tail_id}")
                continue

            head_node = node_index[head_id]
            tail_node = node_index[tail_id]
            ok, error = self.validate_relation(
                head_node.node_type,
                relation_type,
                tail_node.node_type,
                properties=properties,
                head_doc_type=head_node.properties.get("doc_type"),
                tail_doc_type=tail_node.properties.get("doc_type"),
                head_id=head_id,
                tail_id=tail_id,
            )
            if not ok:
                errors.append(error or f"Invalid relation: {relation_type}")
                continue

            relations.append(
                ValidatedRelation(
                    head_id=head_id,
                    relation_type=relation_type,
                    tail_id=tail_id,
                    head_type=head_node.node_type,
                    tail_type=tail_node.node_type,
                    properties=properties,
                )
            )

        if errors:
            raise GraphValidationError(errors)

        return ValidatedGraphPayload(
            nodes=tuple(nodes),
            relations=tuple(relations),
            validation_token=_VALIDATION_TOKEN,
        )

    def _validate_node(
        self,
        node: Mapping[str, Any],
        *,
        node_type: str,
        required_fields: Sequence[str],
        enum_fields: Mapping[str, set[str]] | None = None,
    ) -> ValidatedNode:
        errors: list[str] = []
        if node.get("type") not in (None, node_type):
            errors.append(f"Expected node type {node_type}, got {node.get('type')}")

        for field in required_fields:
            if field not in node or node[field] in (None, ""):
                errors.append(f"{node_type} requires field: {field}")

        for field, allowed_values in (enum_fields or {}).items():
            value = node.get(field)
            if value not in (None, "") and value not in allowed_values:
                errors.append(f"{node_type}.{field} must be one of: {', '.join(sorted(allowed_values))}")

        if errors:
            raise GraphValidationError(errors)

        node_id = str(node["id"])
        properties = dict(node)
        properties.pop("type", None)
        return ValidatedNode(node_type=node_type, id=node_id, properties=properties)


def validate_document(document: Mapping[str, Any]) -> ValidatedNode:
    return OntologyValidator().validate_document(document)


def validate_relation(
    head_type: str,
    relation_type: str,
    tail_type: str,
    *,
    properties: Mapping[str, Any] | None = None,
    head_doc_type: str | None = None,
    tail_doc_type: str | None = None,
    head_id: str | None = None,
    tail_id: str | None = None,
) -> tuple[bool, str | None]:
    return OntologyValidator().validate_relation(
        head_type,
        relation_type,
        tail_type,
        properties=properties,
        head_doc_type=head_doc_type,
        tail_doc_type=tail_doc_type,
        head_id=head_id,
        tail_id=tail_id,
    )


def validate_graph_payload(payload: Mapping[str, Any]) -> ValidatedGraphPayload:
    return OntologyValidator().validate_graph_payload(payload)


def _serialize_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, tuple):
        return [_serialize_value(item) for item in value]
    if isinstance(value, list):
        return [_serialize_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize_value(item) for key, item in value.items()}
    return value
