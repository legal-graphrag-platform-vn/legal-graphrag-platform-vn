"""Validate provider-backed temporal candidates through the extraction gates."""

from __future__ import annotations

from datetime import date, datetime, timezone

from src.pipeline.extraction.provider_relation_candidates import (
    ProviderRelationCandidateV1,
)
from src.pipeline.extraction.structural_context import StructuralRegistry
from src.pipeline.parser.hierarchy_parser import infer_source_effective_from
from src.pipeline.parser.models import DocumentInfo
from src.pipeline.validation.record_consistency_validator import (
    validate_record_relation,
)
from src.pipeline.validation.schema_validator import (
    validate_relation as validate_schema,
)
from src.shared.ontology.validators import validate_relation as validate_ontology


PROVIDER_EXTRACTION_METHOD = "PROVIDER_HTML"
PROVIDER_MATERIALIZATION_ROUTE = "CORPUS_RELATION_RECONCILIATION"
SUPPORTED_PROVIDER_RELATIONS = frozenset({"AMENDS", "REPEALS"})


def build_provider_relation_records(
    candidates: tuple[ProviderRelationCandidateV1, ...],
    *,
    document: DocumentInfo,
    registry: StructuralRegistry,
    source_text: str,
    selected_article_numbers: set[str],
    created_at: datetime | None = None,
) -> list[dict]:
    """Build only fully resolved temporal records; other candidates stay sidecar-only."""

    detected_at = (created_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    effective_from = _effective_from(document, source_text)
    records: list[dict] = []
    for candidate in candidates:
        if (
            candidate.status != "RESOLVED"
            or candidate.relation_candidate not in SUPPORTED_PROVIDER_RELATIONS
        ):
            continue
        _validate_candidate_integrity(candidate, source_text, registry)
        article_number = _host_article_number(candidate, registry)
        if article_number not in selected_article_numbers:
            continue
        properties = {
            "effective_from": str(effective_from) if effective_from else None,
            "extraction_method": PROVIDER_EXTRACTION_METHOD,
            "created_at": detected_at.isoformat().replace("+00:00", "Z"),
            "provider": candidate.reference.provider,
            "provider_candidate_id": candidate.candidate_id,
            "provider_relation_id": candidate.provider_relation_id,
            "provider_source_document_id": (
                candidate.reference.provider_source_document_id
            ),
            "provider_source_item_id": candidate.reference.provider_source_item_id,
            "provider_target_document_id": (
                candidate.reference.provider_target_document_id
            ),
            "source_char_start": candidate.reference.source_char_start,
            "source_char_end": candidate.reference.source_char_end,
            "materialization_route": PROVIDER_MATERIALIZATION_ROUTE,
        }
        properties = {
            key: value for key, value in properties.items() if value is not None
        }
        if candidate.relation_candidate == "AMENDS":
            properties["source_doc_id"] = document.id

        known_ids = set(registry.types) | set(candidate.canonical_target_ids)
        for target_id, target_type in zip(
            candidate.canonical_target_ids,
            candidate.canonical_target_types,
            strict=True,
        ):
            relation = {
                "head": candidate.canonical_source_id,
                "relation": candidate.relation_candidate,
                "tail": target_id,
                "evidence": candidate.evidence,
                "properties": properties,
            }
            parsed_relation, schema_error = validate_schema(relation)
            schema_valid = parsed_relation is not None
            ontology_ok, ontology_error = validate_ontology(
                candidate.canonical_source_type or "",
                candidate.relation_candidate,
                target_type,
                head_id=candidate.canonical_source_id,
                tail_id=target_id,
                properties=properties,
            )
            consistency = validate_record_relation(
                relation_type=candidate.relation_candidate,
                head_id=candidate.canonical_source_id or "",
                tail_id=target_id,
                properties=properties,
                known_entity_ids=known_ids,
                ontology_valid=ontology_ok,
                head_type=candidate.canonical_source_type,
                tail_type=target_type,
            )
            records.append(
                {
                    "document_id": document.id,
                    "article_number": article_number,
                    "raw_relation": relation,
                    "relation": relation,
                    "endpoint_resolution": {
                        "head": {
                            "status": "resolved",
                            "method": PROVIDER_EXTRACTION_METHOD,
                            "canonical_id": candidate.canonical_source_id,
                            "canonical_type": candidate.canonical_source_type,
                        },
                        "tail": {
                            "status": "resolved",
                            "method": PROVIDER_EXTRACTION_METHOD,
                            "canonical_id": target_id,
                            "canonical_type": target_type,
                        },
                    },
                    "schema_valid": schema_valid,
                    "schema_error": schema_error,
                    "ontology_valid": ontology_ok,
                    "ontology_error": ontology_error,
                    "consistency_valid": consistency.valid,
                    "consistency_error": consistency.error,
                    "review_reason": consistency.review_reason,
                    "blocking": consistency.blocking,
                    "confidence": None,
                    "extraction_method": PROVIDER_EXTRACTION_METHOD,
                    "materialization_route": PROVIDER_MATERIALIZATION_ROUTE,
                    "provider_bundle_id": candidate.candidate_id,
                }
            )
    return records


def _validate_candidate_integrity(
    candidate: ProviderRelationCandidateV1,
    source_text: str,
    registry: StructuralRegistry,
) -> None:
    if not candidate.canonical_source_id or not candidate.canonical_source_type:
        raise ValueError(
            f"Resolved provider candidate has no source: {candidate.candidate_id}"
        )
    if candidate.canonical_source_id not in registry.types:
        raise ValueError(
            f"Provider candidate source is not in current hierarchy: {candidate.candidate_id}"
        )
    if registry.types[candidate.canonical_source_id] != candidate.canonical_source_type:
        raise ValueError(
            f"Provider candidate source type drift: {candidate.candidate_id}"
        )
    if not candidate.canonical_target_ids or len(candidate.canonical_target_ids) != len(
        candidate.canonical_target_types
    ):
        raise ValueError(
            f"Resolved provider candidate has invalid targets: {candidate.candidate_id}"
        )
    reference = candidate.reference
    marker = source_text[reference.source_char_start : reference.source_char_end]
    if marker != f"[{reference.citation_text}]":
        raise ValueError(
            f"Provider candidate source span drift: {candidate.candidate_id}"
        )


def _host_article_number(
    candidate: ProviderRelationCandidateV1, registry: StructuralRegistry
) -> str:
    source_id = candidate.host_source_id or candidate.canonical_source_id or ""
    matches = [
        number
        for number, article_id in registry.articles.items()
        if source_id == article_id or source_id.startswith(f"{article_id}_")
    ]
    if len(matches) != 1:
        raise ValueError(
            f"Provider candidate host Article is unresolved: {candidate.candidate_id}"
        )
    return matches[0]


def _effective_from(document: DocumentInfo, source_text: str) -> date | None:
    return document.effective_from or infer_source_effective_from(source_text)
