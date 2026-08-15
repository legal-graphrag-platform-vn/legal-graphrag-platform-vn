"""Consistency and ontology gate for registry-resolved external references."""

from __future__ import annotations

from collections import Counter

from src.pipeline.extraction.corpus_structural_registry import (
    RegistryBuild,
    RegistryDocument,
    RegistryEndpoint,
    RegistryUnit,
)
from src.pipeline.extraction.structural_references import (
    LINKER_NAME,
    LINKER_VERSION,
)
from src.pipeline.pipeline.reference_checkpoint_store import ReferenceCheckpointV2
from src.shared.ontology.payload_consistency_validator import (
    deterministic_relation_id,
    relation_identity_discriminator,
)
from src.shared.ontology.validators import (
    GraphValidationError,
    ValidatedExternalReference,
    ValidatedRelation,
    ValidatedRelationBatch,
    validate_external_relation_batch,
)


class ExternalReferenceValidationError(GraphValidationError):
    """Raised when registry/checkpoint evidence is inconsistent."""


def validate_external_reference_bundle(
    checkpoints: list[ReferenceCheckpointV2] | tuple[ReferenceCheckpointV2, ...],
    build: RegistryBuild,
) -> ValidatedRelationBatch:
    """Validate one atomic external bundle against one verified registry build."""

    errors: list[str] = []
    if not checkpoints:
        raise ExternalReferenceValidationError(["External bundle must not be empty"])
    bundle_ids = {checkpoint.reference_bundle_id for checkpoint in checkpoints}
    if len(bundle_ids) != 1:
        errors.append("External validation input contains multiple bundle IDs")
    expected_target_count = sum(
        len(checkpoint.reference.target_unit_ids) for checkpoint in checkpoints
    )
    references: list[ValidatedExternalReference] = []

    for checkpoint in checkpoints:
        resolution = checkpoint.resolution
        reference = checkpoint.reference
        evidences = reference.all_registry_evidences()
        if resolution.status != "RESOLVED":
            errors.append(
                f"{checkpoint.reference_bundle_id}: resolution is not RESOLVED"
            )
            continue
        if (
            resolution.reference_scope != "EXTERNAL"
            and reference.projection_evidence is None
        ) or resolution.is_self_reference:
            errors.append(
                f"{checkpoint.reference_bundle_id}: reference is not external"
            )
            continue
        if checkpoint.materialization.status == "BLOCKED":
            errors.append(f"{checkpoint.reference_bundle_id}: checkpoint is BLOCKED")
            continue
        if not evidences:
            errors.append(
                f"{checkpoint.reference_bundle_id}: registry evidence is missing"
            )
            continue
        receipt = build.receipt
        receipt_tuple = (
            receipt.build_id,
            receipt.snapshot_hash,
            receipt.provenance_hash,
        )
        state_tuple = (
            resolution.build_id,
            resolution.snapshot_hash,
            resolution.provenance_hash,
        )
        if (
            any(
                (
                    evidence.build_id,
                    evidence.snapshot_hash,
                    evidence.provenance_hash,
                )
                != receipt_tuple
                for evidence in evidences
            )
            or state_tuple != receipt_tuple
        ):
            errors.append(
                f"{checkpoint.reference_bundle_id}: registry build evidence mismatch"
            )
            continue
        if tuple(reference.target_unit_ids) != tuple(resolution.target_ids):
            errors.append(
                f"{checkpoint.reference_bundle_id}: resolution target mismatch"
            )
            continue
        if tuple(item.target_id for item in evidences) != tuple(
            reference.target_unit_ids
        ):
            errors.append(
                f"{checkpoint.reference_bundle_id}: target evidence collection mismatch"
            )
            continue
        projection = reference.projection_evidence
        if projection is not None:
            host = _unique_endpoint(
                build, projection.host_source_unit_id, "host source", errors
            )
            if host is None:
                continue
            host_actual = _endpoint_evidence(host)
            host_expected = (
                projection.host_source_type,
                projection.host_document_id,
                projection.host_source_ancestor_ids,
            )
            if host_actual != host_expected:
                errors.append(
                    f"{checkpoint.reference_bundle_id}: host evidence mismatch"
                )
                continue

        for evidence in evidences:
            source = _unique_endpoint(build, evidence.source_id, "source", errors)
            target = _unique_endpoint(build, evidence.target_id, "target", errors)
            if source is None or target is None:
                continue
            source_type, source_document_id, source_ancestors = _endpoint_evidence(source)
            target_type, target_document_id, target_ancestors = _endpoint_evidence(target)
            actual_source = (
                evidence.source_type,
                evidence.source_document_id,
                evidence.source_ancestor_ids,
            )
            actual_target = (
                evidence.target_type,
                evidence.target_document_id,
                evidence.target_ancestor_ids,
            )
            if actual_source != (source_type, source_document_id, source_ancestors):
                errors.append(
                    f"{checkpoint.reference_bundle_id}: source evidence mismatch"
                )
                continue
            if actual_target != (target_type, target_document_id, target_ancestors):
                errors.append(
                    f"{checkpoint.reference_bundle_id}: target evidence mismatch"
                )
                continue
            if source_document_id == target_document_id and projection is None:
                errors.append(
                    f"{checkpoint.reference_bundle_id}: endpoints share a Document"
                )
                continue

            mention = reference.mention
            properties = {
                "citation_text": mention.raw_text,
                "citation_type": "RANGE" if expected_target_count > 1 else "DIRECT",
                "extraction_method": "ENTITY_LINKING",
                "created_at": checkpoint.detected_at.isoformat(),
                "reference_bundle_id": checkpoint.reference_bundle_id,
                "reference_target_count": expected_target_count,
                "source_unit_id": evidence.source_id,
                "linker_name": LINKER_NAME,
                "linker_version": LINKER_VERSION,
                "source_ownership": "PROJECTED" if projection else "HOST",
            }
            if projection is None:
                properties.update(
                    {
                        "source_char_start": mention.source_char_start,
                        "source_char_end": mention.source_char_end,
                    }
                )
            else:
                properties.update(
                    {
                        "host_evidence_document_id": projection.host_document_id,
                        "host_evidence_source_unit_id": projection.host_source_unit_id,
                        "host_evidence_char_start": projection.host_source_char_start,
                        "host_evidence_char_end": projection.host_source_char_end,
                        "projection_basis_candidate_id": (
                            projection.projection_basis_candidate_id
                        ),
                    }
                )
            discriminator = relation_identity_discriminator("REFERS_TO", properties)
            properties["relation_id"] = deterministic_relation_id(
                evidence.source_id,
                "REFERS_TO",
                evidence.target_id,
                discriminator,
            )
            relation = ValidatedRelation(
                head_id=evidence.source_id,
                relation_type="REFERS_TO",
                tail_id=evidence.target_id,
                head_type=source_type,
                tail_type=target_type,
                properties=properties,
            )
            references.append(
                ValidatedExternalReference(
                    relation=relation,
                    source_id=evidence.source_id,
                    source_type=source_type,
                    source_document_id=source_document_id,
                    source_ancestor_ids=source_ancestors,
                    target_id=evidence.target_id,
                    target_type=target_type,
                    target_document_id=target_document_id,
                    target_ancestor_ids=target_ancestors,
                    reference_bundle_id=checkpoint.reference_bundle_id,
                )
            )

    if len(references) != expected_target_count:
        errors.append(
            f"Incomplete external bundle: expected {expected_target_count}, "
            f"validated {len(references)}"
        )
    target_counts = Counter(reference.target_id for reference in references)
    duplicates = sorted(target for target, count in target_counts.items() if count > 1)
    if duplicates:
        errors.append(f"Duplicate external bundle targets: {', '.join(duplicates)}")
    if errors:
        raise ExternalReferenceValidationError(errors)
    return validate_external_relation_batch(
        references,
        registry_build_id=build.receipt.build_id,
        registry_snapshot_hash=build.receipt.snapshot_hash,
        registry_provenance_hash=build.receipt.provenance_hash,
    )


def _unique_endpoint(
    build: RegistryBuild,
    endpoint_id: str,
    role: str,
    errors: list[str],
) -> RegistryEndpoint | None:
    candidates = build.registry.endpoint_candidates(endpoint_id)
    if len(candidates) != 1:
        errors.append(
            f"Registry {role} endpoint cardinality is {len(candidates)}: {endpoint_id}"
        )
        return None
    return candidates[0]


def _endpoint_evidence(
    endpoint: RegistryEndpoint,
) -> tuple[str, str, tuple[str, ...]]:
    if isinstance(endpoint, RegistryDocument):
        return "Document", endpoint.document_id, ()
    if isinstance(endpoint, RegistryUnit):
        return endpoint.unit_type, endpoint.document_id, endpoint.ancestor_ids
    raise TypeError(f"Unsupported registry endpoint: {type(endpoint)!r}")
