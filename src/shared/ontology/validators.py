"""Write-time ontology validation — enforces graph payload integrity before Neo4j write.

All constants are imported from shared.ontology.contract (single source of truth).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Mapping, Sequence

from src.shared.ontology.contract import (
    APPENDIX_KINDS,
    ATTACHED_INSTRUMENT_KINDS,
    CONSTRAINTS,
    DOCUMENT_LEGAL_STATUSES,
    DOCUMENT_TYPES,
    CONTENT_LEGAL_STATUSES,
    GUIDES_WHITELIST,
    LEGACY_RELATION_ALIASES,
    ONTOLOGY_LABEL_MAP as ONTOLOGY_LABEL_MAP,
    PHASE1_PERSISTED_LABELS as PHASE1_PERSISTED_LABELS,
    RELATION_ENUM,
    RUNTIME_ONLY_LABELS,
)


_VALIDATION_TOKEN = object()


def _validate_property_types(
    relation_type: str,
    properties: Mapping[str, Any],
    property_types: Mapping[str, str],
) -> str | None:
    for key, expected in property_types.items():
        value = properties.get(key)
        if value is None:
            continue
        if expected == "float" and (
            isinstance(value, bool) or not isinstance(value, (int, float))
        ):
            return f"{relation_type}.{key} must be a float"
        if expected == "string" and not isinstance(value, str):
            return f"{relation_type}.{key} must be a string"
        if expected == "integer" and (
            isinstance(value, bool) or not isinstance(value, int)
        ):
            return f"{relation_type}.{key} must be an integer"
        if expected == "datetime":
            if isinstance(value, datetime):
                parsed = value
            elif hasattr(value, "iso_format") and callable(value.iso_format):
                try:
                    parsed = datetime.fromisoformat(
                        value.iso_format().replace("Z", "+00:00")
                    )
                except ValueError:
                    return f"{relation_type}.{key} must be an ISO-8601 datetime"
            elif isinstance(value, str):
                try:
                    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                except ValueError:
                    return f"{relation_type}.{key} must be an ISO-8601 datetime string"
            else:
                return f"{relation_type}.{key} must be an ISO-8601 datetime"
            if parsed.tzinfo is None:
                return f"{relation_type}.{key} must include a timezone"
    return None


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


@dataclass(frozen=True, slots=True)
class ValidatedExternalReference:
    """A relation plus registry-proven endpoint ownership evidence."""

    relation: ValidatedRelation
    source_id: str
    source_type: str
    source_document_id: str
    source_ancestor_ids: tuple[str, ...]
    target_id: str
    target_type: str
    target_document_id: str
    target_ancestor_ids: tuple[str, ...]
    reference_bundle_id: str


@dataclass(frozen=True, slots=True)
class ValidatedRelationBatch:
    """Root-gated relation-only write boundary for external references."""

    references: tuple[ValidatedExternalReference, ...]
    registry_build_id: str
    registry_snapshot_hash: str
    registry_provenance_hash: str
    validation_token: object


@dataclass(frozen=True, slots=True)
class ValidatedProviderTemporalRelation:
    """Registry-owned temporal relation derived from one provider candidate."""

    relation: ValidatedRelation
    source_document_id: str
    target_document_id: str
    provider_candidate_id: str


@dataclass(frozen=True, slots=True)
class ValidatedProviderTemporalBatch:
    """Root-gated relation-only batch for provider AMENDS/REPEALS edges."""

    relations: tuple[ValidatedProviderTemporalRelation, ...]
    registry_build_id: str
    registry_snapshot_hash: str
    registry_provenance_hash: str
    validation_token: object


class OntologyValidator:
    """Validate graph payloads against the frozen ontology."""

    def validate_document(self, document: Mapping[str, Any]) -> ValidatedNode:
        return self._validate_node(
            document,
            node_type="Document",
            required_fields=(
                "id",
                "doc_type",
                "number",
                "legal_status",
                "effective_from",
                "issuer_name",
            ),
            enum_fields={
                "doc_type": DOCUMENT_TYPES,
                "legal_status": DOCUMENT_LEGAL_STATUSES,
            },
        )

    def validate_issuer(self, issuer: Mapping[str, Any]) -> ValidatedNode:
        return self._validate_node(
            issuer,
            node_type="Issuer",
            required_fields=("id", "name"),
        )

    def validate_appendix(self, appendix: Mapping[str, Any]) -> ValidatedNode:
        return self._validate_node(
            appendix,
            node_type="Appendix",
            required_fields=(
                "id",
                "scope",
                "heading",
                "content_raw",
                "appendix_kind",
                "effective_from",
                "legal_status",
            ),
            enum_fields={
                "appendix_kind": APPENDIX_KINDS,
                "legal_status": CONTENT_LEGAL_STATUSES,
            },
        )

    def validate_attached_instrument(
        self, instrument: Mapping[str, Any]
    ) -> ValidatedNode:
        return self._validate_node(
            instrument,
            node_type="AttachedInstrument",
            required_fields=(
                "id",
                "scope",
                "heading",
                "adoption_text",
                "content_raw",
                "instrument_kind",
            ),
            enum_fields={"instrument_kind": ATTACHED_INSTRUMENT_KINDS},
        )

    def validate_chapter(self, chapter: Mapping[str, Any]) -> ValidatedNode:
        return self._validate_node(
            chapter,
            node_type="Chapter",
            required_fields=("id", "number", "title"),
        )

    def validate_part(self, part: Mapping[str, Any]) -> ValidatedNode:
        if isinstance(part.get("title"), str) and not str(part["title"]).strip():
            raise GraphValidationError(["Part requires field: title"])
        return self._validate_node(
            part,
            node_type="Part",
            required_fields=("id", "number", "title"),
        )

    def validate_section(self, section: Mapping[str, Any]) -> ValidatedNode:
        if isinstance(section.get("title"), str) and not str(section["title"]).strip():
            raise GraphValidationError(["Section requires field: title"])
        return self._validate_node(
            section,
            node_type="Section",
            required_fields=("id", "number", "title"),
        )

    def validate_subsection(self, subsection: Mapping[str, Any]) -> ValidatedNode:
        if (
            isinstance(subsection.get("title"), str)
            and not str(subsection["title"]).strip()
        ):
            raise GraphValidationError(["Subsection requires field: title"])
        return self._validate_node(
            subsection,
            node_type="Subsection",
            required_fields=("id", "number", "title"),
        )

    def validate_article(self, article: Mapping[str, Any]) -> ValidatedNode:
        return self._validate_node(
            article,
            node_type="Article",
            required_fields=(
                "id",
                "number",
                "content_raw",
                "effective_from",
                "legal_status",
            ),
            enum_fields={"legal_status": CONTENT_LEGAL_STATUSES},
        )

    def validate_clause(self, clause: Mapping[str, Any]) -> ValidatedNode:
        return self._validate_node(
            clause,
            node_type="Clause",
            required_fields=(
                "id",
                "number",
                "content_raw",
                "effective_from",
                "legal_status",
            ),
            enum_fields={"legal_status": CONTENT_LEGAL_STATUSES},
        )

    def validate_point(self, point: Mapping[str, Any]) -> ValidatedNode:
        return self._validate_node(
            point,
            node_type="Point",
            required_fields=("id", "label", "content_raw"),
        )

    def validate_semantic_node(
        self, node: Mapping[str, Any], node_type: str
    ) -> ValidatedNode:
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
                return (
                    False,
                    f"Legacy relation type {relation_type}; use canonical {canonical}",
                )
            return False, f"Unknown relation type: {relation_type}"

        constraint = CONSTRAINTS[relation_type]
        properties = dict(properties or {})

        if (
            constraint.get("no_self_loop")
            and head_id is not None
            and tail_id is not None
            and head_id == tail_id
        ):
            return False, f"{relation_type} does not allow self-loops"

        required_properties = constraint.get("required_properties", [])
        missing_properties = [
            key
            for key in required_properties
            if key not in properties or properties[key] in (None, "")
        ]
        if missing_properties:
            return (
                False,
                f"{relation_type} requires properties: {', '.join(missing_properties)}",
            )

        method_property_map = constraint.get(
            "required_properties_by_extraction_method", {}
        )
        if method_property_map:
            extraction_method = properties.get("extraction_method")
            method_properties = method_property_map.get(extraction_method, [])
            missing_method_properties = [
                key
                for key in method_properties
                if key not in properties or properties[key] in (None, "")
            ]
            if missing_method_properties:
                return False, (
                    f"{relation_type} with extraction_method={extraction_method} requires properties: "
                    f"{', '.join(missing_method_properties)}"
                )

        if (
            relation_type == "REFERS_TO"
            and properties.get("extraction_method") == "ENTITY_LINKING"
        ):
            ownership = properties.get("source_ownership", "HOST")
            ownership_requirements = {
                "HOST": ("source_char_start", "source_char_end"),
                "PROJECTED": (
                    "host_evidence_document_id",
                    "host_evidence_source_unit_id",
                    "host_evidence_char_start",
                    "host_evidence_char_end",
                    "projection_basis_candidate_id",
                ),
            }
            required = ownership_requirements.get(ownership)
            if required is None:
                return False, f"REFERS_TO.source_ownership is invalid: {ownership}"
            missing = [
                key
                for key in required
                if key not in properties or properties[key] in (None, "")
            ]
            if missing:
                return False, (
                    f"REFERS_TO with source_ownership={ownership} requires properties: "
                    f"{', '.join(missing)}"
                )

        if (
            relation_type in {"AMENDS", "REPEALS"}
            and properties.get("source_ownership") == "PROJECTED"
        ):
            required = (
                "host_evidence_document_id",
                "host_evidence_source_unit_id",
                "host_evidence_char_start",
                "host_evidence_char_end",
                "projection_basis_candidate_id",
            )
            missing = [
                key
                for key in required
                if key not in properties or properties[key] in (None, "")
            ]
            if missing:
                return False, (
                    f"{relation_type} with source_ownership=PROJECTED requires "
                    f"properties: {', '.join(missing)}"
                )

        for key, allowed_values in constraint.get("property_enums", {}).items():
            value = properties.get(key)
            if value is not None and value not in allowed_values:
                return (
                    False,
                    f"{relation_type}.{key} must be one of: {', '.join(sorted(allowed_values))}",
                )

        type_error = _validate_property_types(
            relation_type, properties, constraint.get("property_types", {})
        )
        if type_error:
            return False, type_error

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
                return (
                    False,
                    f"GUIDES does not allow {head_doc_type} -> {tail_doc_type}",
                )

        return True, None

    def validate_graph_payload(
        self, payload: Mapping[str, Any]
    ) -> ValidatedGraphPayload:
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
                elif node_type == "Appendix":
                    node = self.validate_appendix(raw_node)
                elif node_type == "AttachedInstrument":
                    node = self.validate_attached_instrument(raw_node)
                elif node_type == "Part":
                    node = self.validate_part(raw_node)
                elif node_type == "Chapter":
                    node = self.validate_chapter(raw_node)
                elif node_type == "Section":
                    node = self.validate_section(raw_node)
                elif node_type == "Subsection":
                    node = self.validate_subsection(raw_node)
                elif node_type == "Article":
                    node = self.validate_article(raw_node)
                elif node_type == "Clause":
                    node = self.validate_clause(raw_node)
                elif node_type == "Point":
                    node = self.validate_point(raw_node)
                elif node_type in RUNTIME_ONLY_LABELS:
                    raise GraphValidationError(
                        [
                            f"Runtime-only node type is not Phase 1 persistent: {node_type}"
                        ]
                    )
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
                errors.append(
                    f"{node_type}.{field} must be one of: {', '.join(sorted(allowed_values))}"
                )

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


def validate_external_relation_batch(
    references: Sequence[ValidatedExternalReference],
    *,
    registry_build_id: str,
    registry_snapshot_hash: str,
    registry_provenance_hash: str,
) -> ValidatedRelationBatch:
    """Validate relation shape before issuing the unforgeable batch token."""

    errors: list[str] = []
    seen_relation_ids: set[str] = set()
    seen_bundle_targets: set[tuple[str, str]] = set()
    validator = OntologyValidator()
    for reference in references:
        relation = reference.relation
        if relation.head_id != reference.source_id:
            errors.append("External reference source wrapper does not match relation")
        if relation.tail_id != reference.target_id:
            errors.append("External reference target wrapper does not match relation")
        if relation.head_type != reference.source_type:
            errors.append("External reference source type does not match relation")
        if relation.tail_type != reference.target_type:
            errors.append("External reference target type does not match relation")
        if (
            reference.source_document_id == reference.target_document_id
            and relation.properties.get("source_ownership") != "PROJECTED"
        ):
            errors.append(
                "External reference endpoints must belong to different Documents"
            )
        relation_id = str(relation.properties.get("relation_id") or "")
        if not relation_id:
            errors.append("External REFERS_TO relation requires relation_id")
        elif relation_id in seen_relation_ids:
            errors.append(f"Duplicate external relation_id: {relation_id}")
        seen_relation_ids.add(relation_id)
        identity = (reference.reference_bundle_id, reference.target_id)
        if identity in seen_bundle_targets:
            errors.append(
                "Duplicate external bundle target: "
                f"{reference.reference_bundle_id}/{reference.target_id}"
            )
        seen_bundle_targets.add(identity)
        ok, error = validator.validate_relation(
            relation.head_type,
            relation.relation_type,
            relation.tail_type,
            properties=relation.properties,
            head_id=relation.head_id,
            tail_id=relation.tail_id,
        )
        if not ok:
            errors.append(error or "Invalid external relation")
        if relation.relation_type != "REFERS_TO":
            errors.append("External relation batch only accepts REFERS_TO")
        if (
            relation.properties.get("reference_bundle_id")
            != reference.reference_bundle_id
        ):
            errors.append("External reference bundle wrapper does not match relation")

    if not references:
        errors.append("External relation batch must not be empty")
    if errors:
        raise GraphValidationError(errors)
    return ValidatedRelationBatch(
        references=tuple(references),
        registry_build_id=registry_build_id,
        registry_snapshot_hash=registry_snapshot_hash,
        registry_provenance_hash=registry_provenance_hash,
        validation_token=_VALIDATION_TOKEN,
    )


def validate_provider_temporal_relation_batch(
    relations: Sequence[ValidatedProviderTemporalRelation],
    *,
    registry_build_id: str,
    registry_snapshot_hash: str,
    registry_provenance_hash: str,
) -> ValidatedProviderTemporalBatch:
    """Validate provider temporal edges before relation-only persistence."""

    errors: list[str] = []
    seen_relation_ids: set[str] = set()
    seen_candidate_ids: set[str] = set()
    validator = OntologyValidator()
    for wrapped in relations:
        relation = wrapped.relation
        if relation.relation_type not in {"AMENDS", "REPEALS"}:
            errors.append("Provider temporal batch only accepts AMENDS/REPEALS")
        if relation.head_type not in {"Document", "Article", "Clause", "Point"}:
            errors.append(f"Unsupported temporal source type: {relation.head_type}")
        if relation.tail_type not in {"Document", "Article", "Clause", "Point"}:
            errors.append(f"Unsupported temporal target type: {relation.tail_type}")
        relation_id = str(relation.properties.get("relation_id") or "")
        if not relation_id:
            errors.append("Provider temporal relation requires relation_id")
        elif relation_id in seen_relation_ids:
            errors.append(f"Duplicate provider temporal relation_id: {relation_id}")
        seen_relation_ids.add(relation_id)
        if not wrapped.provider_candidate_id:
            errors.append("Provider temporal relation requires provider_candidate_id")
        elif wrapped.provider_candidate_id in seen_candidate_ids:
            errors.append(
                "Duplicate provider temporal candidate: "
                f"{wrapped.provider_candidate_id}"
            )
        seen_candidate_ids.add(wrapped.provider_candidate_id)
        if (
            relation.properties.get("provider_candidate_id")
            != wrapped.provider_candidate_id
        ):
            errors.append("Provider candidate wrapper does not match relation")
        ok, error = validator.validate_relation(
            relation.head_type,
            relation.relation_type,
            relation.tail_type,
            properties=relation.properties,
            head_id=relation.head_id,
            tail_id=relation.tail_id,
        )
        if not ok:
            errors.append(error or "Invalid provider temporal relation")

    if not relations:
        errors.append("Provider temporal relation batch must not be empty")
    if errors:
        raise GraphValidationError(errors)
    return ValidatedProviderTemporalBatch(
        relations=tuple(relations),
        registry_build_id=registry_build_id,
        registry_snapshot_hash=registry_snapshot_hash,
        registry_provenance_hash=registry_provenance_hash,
        validation_token=_VALIDATION_TOKEN,
    )


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
