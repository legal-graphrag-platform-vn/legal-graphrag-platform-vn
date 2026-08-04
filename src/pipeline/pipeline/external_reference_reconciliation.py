"""Offline resolution and crash-safe external-reference reconciliation service."""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from src.infrastructure.neo4j.reference_writer import (
    ExternalReferenceWriteError,
    Neo4jExternalReferenceWriter,
)
from src.pipeline.extraction.corpus_structural_registry import RegistryBuild
from src.pipeline.extraction.structural_context import StructuralRegistry
from src.pipeline.extraction.structural_references import (
    RESOLVER_NAME,
    RESOLVER_VERSION,
    ResolvedReference,
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


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    raw_doc_code: str
    build_id: str
    dry_run: bool
    detected_count: int
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
) -> list[ResolvedReference]:
    local_registry = StructuralRegistry.from_parsed_document(parsed, raw_doc_code)
    resolver = StructuralReferenceResolver(
        local_registry,
        source_text,
        corpus_registry=build.registry,
        registry_receipt=build.receipt,
    )
    return [
        reference
        for article in parsed.articles
        for reference in resolver.resolve_article(article)
    ]


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
    references = detect_references(
        parsed,
        source_text,
        raw_doc_code=raw_doc_code,
        build=build,
    )
    store = ReferenceCheckpointStore(processed_dir)
    with store.locked():
        checkpoints = _replace_resolution_state(store, references)

    external = [
        checkpoint
        for checkpoint in checkpoints.values()
        if checkpoint.resolution.status == "RESOLVED"
        and checkpoint.resolution.reference_scope == "EXTERNAL"
    ]
    # Validate graph-independent evidence in dry-run too.
    validation_failures: dict[str, str] = {}
    for checkpoint in external:
        try:
            validate_external_reference_bundle([checkpoint], build)
        except ExternalReferenceValidationError as exc:
            validation_failures[checkpoint.reference_bundle_id] = str(exc)

    divergence_count = 0
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

    final = store.read_checkpoints()
    materialization_counts = Counter(
        checkpoint.materialization.status for checkpoint in final.values()
    )
    return ReconciliationReport(
        raw_doc_code=raw_doc_code,
        build_id=build.receipt.build_id,
        dry_run=not apply,
        detected_count=len(references),
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
