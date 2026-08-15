"""Offline resolution and crash-safe external-reference reconciliation service."""

from __future__ import annotations

import json
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from src.infrastructure.neo4j.reference_writer import (
    ExternalReferenceWriteError,
    Neo4jExternalReferenceWriter,
    Neo4jProviderTemporalWriter,
)
from src.pipeline.extraction.corpus_structural_registry import (
    RegistryBuild,
    RegistryDocument,
    RegistryEndpoint,
    RegistryUnit,
)
from src.pipeline.extraction.provider_relation_candidates import (
    ProviderRelationCandidateV1,
    load_provider_relation_candidates,
    provider_owned_source_spans,
    provider_target_document_number_conflicts,
)
from src.pipeline.extraction.structural_context import StructuralRegistry
from src.pipeline.extraction.structural_references import (
    RESOLVER_NAME,
    RESOLVER_VERSION,
    ReferenceMention,
    ProjectionEvidence,
    RegistryResolutionEvidence,
    ResolvedReference,
    SourceContext,
    StructuralReferenceResolver,
)
from src.pipeline.parser.models import ParsedDocument
from src.pipeline.pipeline.reference_checkpoint_store import (
    ReferenceCheckpointStore,
    ReferenceCheckpointV2,
    ReferenceMaterializationAttempt,
    ReferenceMaterializationState,
    checkpoint_from_reference,
    committed_target_history,
)
from src.pipeline.validation.external_reference_validator import (
    ExternalReferenceValidationError,
    validate_external_reference_bundle,
)
from src.pipeline.validation.provider_temporal_validator import (
    validate_provider_temporal_candidates,
)


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    raw_doc_code: str
    build_id: str
    dry_run: bool
    detected_count: int
    provider_candidate_count: int
    provider_projected_requires_rebuild_count: int
    provider_temporal_candidate_count: int
    provider_temporal_ready_count: int
    provider_temporal_not_accepted_count: int
    provider_temporal_written_count: int
    resolved_external_count: int
    pending_count: int
    written_count: int
    failed_count: int
    blocked_count: int
    skipped_count: int
    ownership_path_divergence_count: int


def detect_references(
    parsed: ParsedDocument,
    source_text: str,
    *,
    raw_doc_code: str,
    build: RegistryBuild,
    provider_candidates: tuple[ProviderRelationCandidateV1, ...] = (),
) -> list[ResolvedReference]:
    local_registry = StructuralRegistry.from_parsed_document(parsed, raw_doc_code)
    resolver = StructuralReferenceResolver(
        local_registry,
        source_text,
        corpus_registry=build.registry,
        registry_receipt=build.receipt,
        excluded_source_spans=provider_owned_source_spans(
            provider_candidates, source_text
        ),
    )
    generic_references = [
        reference
        for article in parsed.articles
        for reference in resolver.resolve_article(article)
    ]
    return generic_references + _provider_external_references(
        provider_candidates,
        source_text=source_text,
        build=build,
    )


def _provider_external_references(
    candidates: tuple[ProviderRelationCandidateV1, ...],
    *,
    source_text: str,
    build: RegistryBuild,
) -> list[ResolvedReference]:
    """Convert provider citations into atomic registry-proven reference bundles."""

    references: list[ResolvedReference] = []
    receipt = build.receipt
    for candidate in candidates:
        if (
            candidate.status != "RESOLVED"
            or candidate.relation_candidate != "REFERS_TO"
            or candidate.canonical_source_id is None
            or not candidate.canonical_target_ids
        ):
            continue
        source = _unique_registry_endpoint(
            build, candidate.canonical_source_id, candidate.candidate_id
        )
        if not isinstance(source, RegistryUnit):
            raise ValueError(
                f"Provider REFERS_TO source is not a structural unit: {candidate.candidate_id}"
            )
        if source.unit_type != candidate.canonical_source_type:
            raise ValueError(
                f"Provider candidate source type drift: {candidate.candidate_id}"
            )
        if len(candidate.canonical_target_ids) != len(
            candidate.canonical_target_types
        ):
            raise ValueError(
                f"Provider candidate target cardinality drift: {candidate.candidate_id}"
            )
        if (
            candidate.source_ownership == "PROJECTED"
            and not candidate.projection_basis_candidate_id
        ):
            # Old v1 sidecars do not contain enough proof to materialize safely.
            continue

        target_evidences: list[RegistryResolutionEvidence] = []
        target_document_ids: list[str] = []
        for expected_target_id, expected_target_type in zip(
            candidate.canonical_target_ids,
            candidate.canonical_target_types,
            strict=True,
        ):
            target = _unique_registry_endpoint(
                build, expected_target_id, candidate.candidate_id
            )
            target_id, target_type, target_document_id, target_ancestors = (
                _registry_endpoint_evidence(target)
            )
            target_document = _unique_registry_endpoint(
                build, target_document_id, candidate.candidate_id
            )
            if not isinstance(target_document, RegistryDocument):
                raise ValueError(
                    f"Provider target owner is not a Document: {candidate.candidate_id}"
                )
            if provider_target_document_number_conflicts(
                candidate.reference.citation_text, target_document.number
            ):
                raise ValueError(
                    f"provider_text_target_conflict: {candidate.candidate_id}"
                )
            if target_type != expected_target_type:
                raise ValueError(
                    f"Provider candidate target type drift: {candidate.candidate_id}"
                )
            target_document_ids.append(target_document_id)
            target_evidences.append(
                RegistryResolutionEvidence(
                    build_id=receipt.build_id,
                    snapshot_hash=receipt.snapshot_hash,
                    provenance_hash=receipt.provenance_hash,
                    source_id=source.unit_id,
                    source_type=source.unit_type,
                    source_document_id=source.document_id,
                    source_ancestor_ids=source.ancestor_ids,
                    target_id=target_id,
                    target_type=target_type,
                    target_document_id=target_document_id,
                    target_ancestor_ids=target_ancestors,
                )
            )

        projection_evidence = None
        if candidate.source_ownership == "PROJECTED":
            if candidate.host_source_id is None:
                raise ValueError(
                    f"Projected provider candidate has no host source: {candidate.candidate_id}"
                )
            host = _unique_registry_endpoint(
                build, candidate.host_source_id, candidate.candidate_id
            )
            if not isinstance(host, RegistryUnit):
                raise ValueError(
                    f"Projected host source is not a structural unit: {candidate.candidate_id}"
                )
            projection_evidence = ProjectionEvidence(
                host_document_id=host.document_id,
                host_source_unit_id=host.unit_id,
                host_source_type=host.unit_type,
                host_source_ancestor_ids=host.ancestor_ids,
                host_source_char_start=candidate.reference.source_char_start,
                host_source_char_end=candidate.reference.source_char_end,
                projection_basis_candidate_id=(
                    candidate.projection_basis_candidate_id or ""
                ),
            )

        article_id, clause_id, point_id = _source_context_ancestors(build, source)
        reference = candidate.reference
        raw_text = source_text[reference.source_char_start : reference.source_char_end]
        mention = ReferenceMention(
            source_context=SourceContext(
                document_id=source.document_id,
                article_id=article_id,
                clause_id=clause_id,
                point_id=point_id,
                source_unit_id=source.unit_id,
                source_start_char=(
                    reference.source_char_start
                    if candidate.source_ownership == "HOST"
                    else None
                ),
                source_end_char=(
                    reference.source_char_end
                    if candidate.source_ownership == "HOST"
                    else None
                ),
            ),
            raw_text=raw_text,
            reference_kind="EXPLICIT",
            source_char_start=reference.source_char_start,
            source_char_end=reference.source_char_end,
            reference_bundle_id=candidate.candidate_id,
        )
        references.append(
            ResolvedReference(
                mention=mention,
                target_unit_ids=tuple(candidate.canonical_target_ids),
                status="RESOLVED",
                reference_scope=(
                    "EXTERNAL"
                    if any(
                        document_id != source.document_id
                        for document_id in target_document_ids
                    )
                    else "LOCAL"
                ),
                is_self_reference=(
                    len(candidate.canonical_target_ids) == 1
                    and candidate.canonical_target_ids[0] == source.unit_id
                ),
                resolution_method="ENTITY_LINKING",
                reason_code="provider_external_structural_resolution",
                registry_evidence=target_evidences[0],
                registry_evidences=tuple(target_evidences),
                projection_evidence=projection_evidence,
            )
        )
    return references


def _unique_registry_endpoint(
    build: RegistryBuild, endpoint_id: str, candidate_id: str
) -> RegistryEndpoint:
    endpoints = build.registry.endpoint_candidates(endpoint_id)
    if len(endpoints) != 1:
        raise ValueError(
            f"Provider candidate endpoint cardinality is {len(endpoints)}: "
            f"{candidate_id}/{endpoint_id}"
        )
    return endpoints[0]


def _registry_endpoint_evidence(
    endpoint: RegistryEndpoint,
) -> tuple[str, str, str, tuple[str, ...]]:
    if isinstance(endpoint, RegistryDocument):
        return endpoint.document_id, "Document", endpoint.document_id, ()
    return (
        endpoint.unit_id,
        endpoint.unit_type,
        endpoint.document_id,
        endpoint.ancestor_ids,
    )


def _source_context_ancestors(
    build: RegistryBuild, source: RegistryUnit
) -> tuple[str, str | None, str | None]:
    units = {
        endpoint.unit_type: endpoint.unit_id
        for ancestor_id in source.ancestor_ids
        for endpoint in build.registry.endpoint_candidates(ancestor_id)
        if isinstance(endpoint, RegistryUnit)
    }
    if source.unit_type == "Article":
        units["Article"] = source.unit_id
    elif source.unit_type == "Clause":
        units["Clause"] = source.unit_id
    elif source.unit_type == "Point":
        units["Point"] = source.unit_id
    article_id = units.get("Article")
    if article_id is None:
        raise ValueError(f"Provider source has no Article ancestor: {source.unit_id}")
    return article_id, units.get("Clause"), units.get("Point")


def reconcile_external_references(
    *,
    raw_doc_code: str,
    processed_dir: Path,
    parsed: ParsedDocument,
    source_text: str,
    build: RegistryBuild,
    apply: bool,
    session: Any | None = None,
) -> ReconciliationReport:
    provider_candidates = load_provider_relation_candidates(
        processed_dir / "provider_relation_candidates.jsonl"
    )
    _validate_projected_candidate_bases(provider_candidates)
    temporal_validation = validate_provider_temporal_candidates(
        provider_candidates,
        _load_jsonl(processed_dir / "accepted.jsonl"),
        build,
    )
    references = detect_references(
        parsed,
        source_text,
        raw_doc_code=raw_doc_code,
        build=build,
        provider_candidates=provider_candidates,
    )
    store = ReferenceCheckpointStore(processed_dir)
    with store.locked():
        checkpoints = _replace_resolution_state(store, references)

    external = [
        checkpoint
        for checkpoint in checkpoints.values()
        if checkpoint.resolution.status == "RESOLVED"
        and (
            checkpoint.resolution.reference_scope == "EXTERNAL"
            or checkpoint.reference.projection_evidence is not None
        )
    ]
    # Validate graph-independent evidence in dry-run too.
    validation_failures: dict[str, str] = {}
    for checkpoint in external:
        try:
            validate_external_reference_bundle([checkpoint], build)
        except ExternalReferenceValidationError as exc:
            validation_failures[checkpoint.reference_bundle_id] = str(exc)

    divergence_count = 0
    temporal_written_count = 0
    if apply:
        if session is None:
            raise ValueError("Neo4j session is required when apply=True")
        writer = Neo4jExternalReferenceWriter(session=session)
        for initial in external:
            bundle_id = initial.reference_bundle_id
            with store.locked():
                current = store.read_checkpoints()
                attempts = store.read_attempts()
                expected_hash = store.checkpoint_hash()
                checkpoint = current[bundle_id]
                old_writes = committed_target_history(attempts, bundle_id)
                if checkpoint.materialization.status in {"WRITTEN", "BLOCKED"}:
                    continue
                if (
                    old_writes
                    and tuple(sorted(checkpoint.resolution.target_ids))
                    not in old_writes
                ):
                    current[bundle_id] = _set_materialization(
                        checkpoint,
                        status="BLOCKED",
                        reason="resolved_target_changed_after_materialization",
                    )
                    store.compare_and_swap(current, expected_hash=expected_hash)
                    continue
                if bundle_id in validation_failures:
                    current[bundle_id] = _set_materialization(
                        checkpoint,
                        status="FAILED",
                        reason="external_reference_validation_failed",
                    )
                    store.compare_and_swap(current, expected_hash=expected_hash)
                    continue

                batch = validate_external_reference_bundle([checkpoint], build)
                started = datetime.now(timezone.utc)
                observed: tuple[str, ...] = ()
                relation_ids: tuple[str, ...] = ()
                graph_outcome = "UNKNOWN"
                error_code: str | None = None
                result = None
                try:
                    result = writer.write(batch)[0]
                    observed = result.observed_existing_target_ids
                    relation_ids = result.relation_ids
                    divergence_count += result.ownership_path_divergence_count
                    graph_outcome = "COMMITTED"
                except ExternalReferenceWriteError as exc:
                    graph_outcome = "NOT_COMMITTED"
                    error_code = exc.code
                    observed = exc.observed_target_ids
                except Exception:
                    error_code = "neo4j_commit_outcome_unknown"

                attempt = ReferenceMaterializationAttempt(
                    attempt_id=str(uuid.uuid4()),
                    reference_bundle_id=bundle_id,
                    build_id=build.receipt.build_id,
                    snapshot_hash=build.receipt.snapshot_hash,
                    provenance_hash=build.receipt.provenance_hash,
                    expected_checkpoint_hash=expected_hash,
                    expected_target_ids=checkpoint.resolution.target_ids,
                    observed_existing_target_ids=observed,
                    graph_outcome=graph_outcome,
                    relation_ids=relation_ids,
                    started_at=started,
                    finished_at=datetime.now(timezone.utc),
                    error_code=error_code,
                )
                # Mandatory ordering: graph transaction -> durable ledger -> checkpoint CAS.
                store.append_attempt(attempt)
                if graph_outcome == "COMMITTED" and result is not None:
                    current[bundle_id] = _set_materialization(
                        checkpoint,
                        status="WRITTEN",
                        reason=None,
                        relation_ids=relation_ids,
                    )
                elif error_code in {
                    "bundle_target_conflict_in_graph",
                    "partial_materialized_bundle_in_graph",
                    "endpoint_document_ownership_ambiguous_in_graph",
                }:
                    reason = (
                        "resolved_target_changed_after_materialization"
                        if error_code == "bundle_target_conflict_in_graph"
                        else error_code
                    )
                    current[bundle_id] = _set_materialization(
                        checkpoint, status="BLOCKED", reason=reason
                    )
                else:
                    current[bundle_id] = _set_materialization(
                        checkpoint,
                        status="FAILED",
                        reason=error_code or "neo4j_materialization_failed",
                    )
                store.compare_and_swap(current, expected_hash=expected_hash)

        if temporal_validation.batch is not None:
            temporal_writer = Neo4jProviderTemporalWriter(session=session)
            temporal_written_count = len(
                temporal_writer.write(temporal_validation.batch)
            )

    final = store.read_checkpoints()
    materialization_counts = Counter(
        checkpoint.materialization.status for checkpoint in final.values()
    )
    return ReconciliationReport(
        raw_doc_code=raw_doc_code,
        build_id=build.receipt.build_id,
        dry_run=not apply,
        detected_count=len(references),
        provider_candidate_count=len(provider_candidates),
        provider_projected_requires_rebuild_count=sum(
            candidate.status == "RESOLVED"
            and candidate.source_ownership == "PROJECTED"
            and not candidate.projection_basis_candidate_id
            and candidate.relation_candidate in {"AMENDS", "REPEALS", "REFERS_TO"}
            for candidate in provider_candidates
        ),
        provider_temporal_candidate_count=temporal_validation.candidate_count,
        provider_temporal_ready_count=temporal_validation.ready_count,
        provider_temporal_not_accepted_count=(temporal_validation.not_accepted_count),
        provider_temporal_written_count=temporal_written_count,
        resolved_external_count=len(external),
        pending_count=materialization_counts["PENDING"],
        written_count=materialization_counts["WRITTEN"],
        failed_count=materialization_counts["FAILED"],
        blocked_count=materialization_counts["BLOCKED"],
        skipped_count=sum(
            count
            for status, count in materialization_counts.items()
            if status == "NOT_APPLICABLE"
        ),
        ownership_path_divergence_count=divergence_count,
    )


def _validate_projected_candidate_bases(
    candidates: tuple[ProviderRelationCandidateV1, ...],
) -> None:
    """Prove that every v2 projected source comes from its governing edge."""

    by_id = {candidate.candidate_id: candidate for candidate in candidates}
    for candidate in candidates:
        if (
            candidate.status != "RESOLVED"
            or candidate.source_ownership != "PROJECTED"
            or not candidate.projection_basis_candidate_id
        ):
            continue
        basis = by_id.get(candidate.projection_basis_candidate_id)
        if (
            basis is None
            or basis.status != "RESOLVED"
            or basis.source_ownership != "HOST"
            or basis.relation_candidate not in {"AMENDS", "REPEALS"}
            or candidate.canonical_source_id not in basis.canonical_target_ids
        ):
            raise ValueError(
                "projected_source_basis_invalid: "
                f"{candidate.candidate_id}/{candidate.projection_basis_candidate_id}"
            )


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"Expected JSON object at {path}:{line_number}")
        records.append(value)
    return records


def reference_status(processed_dir: Path) -> dict[str, Any]:
    store = ReferenceCheckpointStore(processed_dir)
    checkpoints = store.read_checkpoints()
    attempts = store.read_attempts()
    resolution = Counter(item.resolution.status for item in checkpoints.values())
    scopes = Counter(item.resolution.reference_scope for item in checkpoints.values())
    materialization = Counter(
        item.materialization.status for item in checkpoints.values()
    )
    reasons = Counter(
        item.materialization.reason_code or item.resolution.reason_code
        for item in checkpoints.values()
    )
    builds = Counter(
        item.resolution.build_id or "none" for item in checkpoints.values()
    )
    snapshots = Counter(
        item.resolution.snapshot_hash or "none" for item in checkpoints.values()
    )
    provenances = Counter(
        item.resolution.provenance_hash or "none" for item in checkpoints.values()
    )
    target_documents = Counter(
        item.reference.registry_evidence.target_document_id
        for item in checkpoints.values()
        if item.reference.registry_evidence is not None
    )
    return {
        "checkpoint_count": len(checkpoints),
        "attempt_count": len(attempts),
        "resolution_status": dict(sorted(resolution.items())),
        "reference_scope": dict(sorted(scopes.items())),
        "self_reference_count": sum(
            item.resolution.is_self_reference for item in checkpoints.values()
        ),
        "materialization_status": dict(sorted(materialization.items())),
        "reason_code": dict(sorted(reasons.items())),
        "build_id": dict(sorted(builds.items())),
        "snapshot_hash": dict(sorted(snapshots.items())),
        "provenance_hash": dict(sorted(provenances.items())),
        "target_document": dict(sorted(target_documents.items())),
        "blocked_conflict_count": sum(
            item.materialization.status == "BLOCKED" for item in checkpoints.values()
        ),
        "registry_graph_divergence_count": sum(
            item.materialization.reason_code
            in {
                "endpoint_document_ownership_mismatch_in_graph",
                "endpoint_document_ownership_missing_in_graph",
                "endpoint_document_ownership_ambiguous_in_graph",
                "endpoint_missing_or_non_unique_in_graph",
            }
            for item in checkpoints.values()
        ),
        "unknown_graph_outcome_count": sum(
            attempt.graph_outcome == "UNKNOWN" for attempt in attempts
        ),
    }


def _replace_resolution_state(
    store: ReferenceCheckpointStore,
    references: Iterable[ResolvedReference],
) -> dict[str, ReferenceCheckpointV2]:
    existing = store.read_checkpoints()
    attempts = store.read_attempts()
    expected_hash = store.checkpoint_hash()
    now = datetime.now(timezone.utc)
    committed_bundles = {
        attempt.reference_bundle_id
        for attempt in attempts
        if attempt.graph_outcome == "COMMITTED"
    }
    updated: dict[str, ReferenceCheckpointV2] = {
        bundle_id: checkpoint
        for bundle_id, checkpoint in existing.items()
        if bundle_id in committed_bundles
        or checkpoint.materialization.status in {"WRITTEN", "BLOCKED"}
    }
    for reference in references:
        bundle_id = reference.mention.reference_bundle_id
        updated[bundle_id] = checkpoint_from_reference(
            reference,
            resolver_name=RESOLVER_NAME,
            resolver_version=RESOLVER_VERSION,
            detected_at=now,
            prior=existing.get(bundle_id),
            prior_written=bool(committed_target_history(attempts, bundle_id)),
        )
    store.compare_and_swap(updated, expected_hash=expected_hash)
    return updated


def _set_materialization(
    checkpoint: ReferenceCheckpointV2,
    *,
    status: str,
    reason: str | None,
    relation_ids: tuple[str, ...] = (),
) -> ReferenceCheckpointV2:
    now = datetime.now(timezone.utc)
    old = checkpoint.materialization
    state = ReferenceMaterializationState(
        status=status,
        reason_code=reason,
        relation_ids=relation_ids or old.relation_ids,
        attempt_count=old.attempt_count + 1,
        last_attempt_at=now,
        written_at=(now if status == "WRITTEN" else old.written_at),
    )
    return checkpoint.model_copy(update={"materialization": state})
