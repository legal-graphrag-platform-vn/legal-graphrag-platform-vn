"""Registry and decision-gate validation for provider temporal relations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from src.pipeline.extraction.corpus_structural_registry import (
    RegistryBuild,
    RegistryDocument,
    RegistryEndpoint,
    RegistryUnit,
)
from src.pipeline.extraction.provider_relation_candidates import (
    ProviderRelationCandidateV1,
    provider_target_document_number_conflicts,
)
from src.shared.ontology.payload_consistency_validator import (
    deterministic_relation_id,
    relation_identity_discriminator,
)
from src.shared.ontology.validators import (
    GraphValidationError,
    ValidatedProviderTemporalBatch,
    ValidatedProviderTemporalRelation,
    ValidatedRelation,
    validate_provider_temporal_relation_batch,
)


@dataclass(frozen=True, slots=True)
class ProviderTemporalValidationResult:
    batch: ValidatedProviderTemporalBatch | None
    candidate_count: int
    ready_count: int
    projected_blocked_count: int
    not_accepted_count: int


def validate_provider_temporal_candidates(
    candidates: Sequence[ProviderRelationCandidateV1],
    accepted_records: Sequence[Mapping[str, object]],
    build: RegistryBuild,
) -> ProviderTemporalValidationResult:
    """Admit decision-gated temporal candidates with complete endpoint provenance."""

    temporal = tuple(
        candidate
        for candidate in candidates
        if candidate.status == "RESOLVED"
        and candidate.relation_candidate in {"AMENDS", "REPEALS"}
    )
    accepted_by_candidate: dict[str, list[Mapping[str, object]]] = {}
    for record in accepted_records:
        candidate_id = str(record.get("provider_bundle_id") or "")
        if candidate_id:
            accepted_by_candidate.setdefault(candidate_id, []).append(record)

    wrapped_relations: list[ValidatedProviderTemporalRelation] = []
    projected_blocked = 0
    not_accepted = 0
    errors: list[str] = []
    for candidate in temporal:
        if (
            candidate.source_ownership == "PROJECTED"
            and not candidate.projection_basis_candidate_id
        ):
            projected_blocked += 1
            continue
        records = accepted_by_candidate.get(candidate.candidate_id, [])
        if len(records) != 1:
            not_accepted += 1
            if len(records) > 1:
                errors.append(
                    f"{candidate.candidate_id}: multiple accepted provider records"
                )
            continue
        if (
            candidate.canonical_source_id is None
            or candidate.canonical_source_type is None
            or len(candidate.canonical_target_ids) != 1
            or len(candidate.canonical_target_types) != 1
        ):
            errors.append(f"{candidate.candidate_id}: invalid temporal candidate shape")
            continue

        source = _unique_endpoint(
            build, candidate.canonical_source_id, candidate.candidate_id, errors
        )
        target = _unique_endpoint(
            build, candidate.canonical_target_ids[0], candidate.candidate_id, errors
        )
        if source is None or target is None:
            continue
        if candidate.source_ownership == "PROJECTED":
            if candidate.host_source_id is None:
                errors.append(f"{candidate.candidate_id}: projected host is missing")
                continue
            host = _unique_endpoint(
                build, candidate.host_source_id, candidate.candidate_id, errors
            )
            if not isinstance(host, RegistryUnit):
                errors.append(
                    f"{candidate.candidate_id}: projected host is not a structural unit"
                )
                continue
        source_type, source_document_id = _endpoint_identity(source)
        target_type, target_document_id = _endpoint_identity(target)
        target_document = _unique_endpoint(
            build, target_document_id, candidate.candidate_id, errors
        )
        if not isinstance(target_document, RegistryDocument):
            errors.append(f"{candidate.candidate_id}: target owner is not a Document")
            continue
        if provider_target_document_number_conflicts(
            candidate.reference.citation_text, target_document.number
        ):
            errors.append(f"{candidate.candidate_id}: provider_text_target_conflict")
            continue
        if source_type != candidate.canonical_source_type:
            errors.append(f"{candidate.candidate_id}: source type drift")
            continue
        if target_type != candidate.canonical_target_types[0]:
            errors.append(f"{candidate.candidate_id}: target type drift")
            continue

        record = records[0]
        relation = record.get("relation")
        if not isinstance(relation, Mapping):
            errors.append(f"{candidate.candidate_id}: accepted relation is missing")
            continue
        if (
            relation.get("head") != candidate.canonical_source_id
            or relation.get("tail") != candidate.canonical_target_ids[0]
            or relation.get("relation") != candidate.relation_candidate
        ):
            errors.append(f"{candidate.candidate_id}: accepted relation drift")
            continue
        properties = dict(relation.get("properties") or {})
        properties.pop("materialization_route", None)
        if properties.get("provider_candidate_id") != candidate.candidate_id:
            errors.append(f"{candidate.candidate_id}: provider provenance drift")
            continue
        if properties.get("source_ownership", "HOST") != candidate.source_ownership:
            errors.append(f"{candidate.candidate_id}: source ownership drift")
            continue
        if candidate.source_ownership == "PROJECTED" and (
            properties.get("host_evidence_document_id") != host.document_id
            or properties.get("host_evidence_source_unit_id") != host.unit_id
            or properties.get("projection_basis_candidate_id")
            != candidate.projection_basis_candidate_id
        ):
            errors.append(f"{candidate.candidate_id}: projection provenance drift")
            continue
        discriminator = relation_identity_discriminator(
            candidate.relation_candidate, properties
        )
        properties["relation_id"] = deterministic_relation_id(
            candidate.canonical_source_id,
            candidate.relation_candidate,
            candidate.canonical_target_ids[0],
            discriminator,
        )
        wrapped_relations.append(
            ValidatedProviderTemporalRelation(
                relation=ValidatedRelation(
                    head_id=candidate.canonical_source_id,
                    relation_type=candidate.relation_candidate,
                    tail_id=candidate.canonical_target_ids[0],
                    head_type=source_type,
                    tail_type=target_type,
                    properties=properties,
                ),
                source_document_id=source_document_id,
                target_document_id=target_document_id,
                provider_candidate_id=candidate.candidate_id,
            )
        )

    if errors:
        raise GraphValidationError(errors)
    batch = (
        validate_provider_temporal_relation_batch(
            wrapped_relations,
            registry_build_id=build.receipt.build_id,
            registry_snapshot_hash=build.receipt.snapshot_hash,
            registry_provenance_hash=build.receipt.provenance_hash,
        )
        if wrapped_relations
        else None
    )
    return ProviderTemporalValidationResult(
        batch=batch,
        candidate_count=len(temporal),
        ready_count=len(wrapped_relations),
        projected_blocked_count=projected_blocked,
        not_accepted_count=not_accepted,
    )


def _unique_endpoint(
    build: RegistryBuild,
    endpoint_id: str,
    candidate_id: str,
    errors: list[str],
) -> RegistryEndpoint | None:
    endpoints = build.registry.endpoint_candidates(endpoint_id)
    if len(endpoints) != 1:
        errors.append(
            f"{candidate_id}: endpoint cardinality is {len(endpoints)} for {endpoint_id}"
        )
        return None
    return endpoints[0]


def _endpoint_identity(endpoint: RegistryEndpoint) -> tuple[str, str]:
    if isinstance(endpoint, RegistryDocument):
        return "Document", endpoint.document_id
    if isinstance(endpoint, RegistryUnit):
        return endpoint.unit_type, endpoint.document_id
    raise TypeError(f"Unsupported registry endpoint: {type(endpoint)!r}")
