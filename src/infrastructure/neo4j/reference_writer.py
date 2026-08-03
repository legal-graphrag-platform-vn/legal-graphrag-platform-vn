"""Transaction-guarded relation-only writer for external REFERS_TO bundles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from src.shared.ontology import validators as root_validator
from src.shared.ontology.validators import (
    ValidatedExternalReference,
    ValidatedRelationBatch,
)
from src.shared.ontology.hierarchy import MAX_DOCUMENT_HIERARCHY_DEPTH


SOURCE_LABELS = frozenset({"Article", "Clause", "Point"})
TARGET_LABELS = frozenset(
    {
        "Document",
        "Part",
        "Chapter",
        "Section",
        "Subsection",
        "Article",
        "Clause",
        "Point",
    }
)


class ExternalReferenceWriteError(RuntimeError):
    """Typed materialization failure; callback exceptions roll back the bundle."""

    def __init__(
        self,
        code: str,
        detail: str = "",
        *,
        observed_target_ids: tuple[str, ...] = (),
    ) -> None:
        self.code = code
        self.detail = detail
        self.observed_target_ids = observed_target_ids
        super().__init__(f"{code}: {detail}" if detail else code)


@dataclass(frozen=True, slots=True)
class BundleMaterializationResult:
    reference_bundle_id: str
    source_id: str
    expected_target_ids: tuple[str, ...]
    observed_existing_target_ids: tuple[str, ...]
    final_target_ids: tuple[str, ...]
    relation_ids: tuple[str, ...]
    ownership_path_divergence_count: int
    matched_existing: bool


@dataclass(slots=True)
class Neo4jExternalReferenceWriter:
    session: Any

    def write(self, batch: Any) -> tuple[BundleMaterializationResult, ...]:
        if (
            not isinstance(batch, ValidatedRelationBatch)
            or batch.validation_token is not root_validator._VALIDATION_TOKEN
        ):
            raise TypeError(
                "Neo4jExternalReferenceWriter.write expects a root "
                "ValidatedRelationBatch"
            )
        bundles: dict[str, list[ValidatedExternalReference]] = {}
        for reference in batch.references:
            bundles.setdefault(reference.reference_bundle_id, []).append(reference)
        results = []
        for bundle_id in sorted(bundles):
            references = tuple(bundles[bundle_id])
            results.append(self.session.execute_write(self._write_bundle, references))
        return tuple(results)

    def _write_bundle(
        self,
        tx: Any,
        references: tuple[ValidatedExternalReference, ...],
    ) -> BundleMaterializationResult:
        if not references:
            raise ExternalReferenceWriteError("empty_reference_bundle")
        bundle_ids = {reference.reference_bundle_id for reference in references}
        source_ids = {reference.source_id for reference in references}
        if len(bundle_ids) != 1 or len(source_ids) != 1:
            raise ExternalReferenceWriteError("invalid_reference_bundle_shape")
        bundle_id = next(iter(bundle_ids))
        source_id = next(iter(source_ids))
        expected_targets = tuple(sorted({item.target_id for item in references}))
        if len(expected_targets) != len(references):
            raise ExternalReferenceWriteError("duplicate_reference_bundle_target")

        divergence_count = 0
        endpoints: dict[tuple[str, str, str], None] = {}
        for reference in references:
            _require_label(reference.source_type, SOURCE_LABELS, "source")
            _require_label(reference.target_type, TARGET_LABELS, "target")
            if reference.source_document_id == reference.target_document_id:
                raise ExternalReferenceWriteError(
                    "same_document_reference_not_external"
                )
            endpoints[
                (
                    reference.source_id,
                    reference.source_type,
                    reference.source_document_id,
                )
            ] = None
            endpoints[
                (
                    reference.target_id,
                    reference.target_type,
                    reference.target_document_id,
                )
            ] = None

        # Every endpoint is verified before any relation MERGE occurs.
        for endpoint_id, endpoint_type, expected_owner in endpoints:
            evidence = _verify_endpoint(
                tx,
                endpoint_id=endpoint_id,
                endpoint_type=endpoint_type,
            )
            if evidence["endpoint_count"] != 1:
                raise ExternalReferenceWriteError(
                    "endpoint_missing_or_non_unique_in_graph", endpoint_id
                )
            owners = tuple(sorted(evidence["owner_ids"]))
            if owners != (expected_owner,):
                code = (
                    "endpoint_document_ownership_ambiguous_in_graph"
                    if len(owners) > 1
                    else "endpoint_document_ownership_mismatch_in_graph"
                )
                raise ExternalReferenceWriteError(code, endpoint_id)
            path_count = int(evidence["ownership_path_count"])
            if endpoint_type == "Document":
                if path_count != 1:
                    raise ExternalReferenceWriteError(
                        "document_endpoint_identity_mismatch_in_graph", endpoint_id
                    )
            elif path_count < 1:
                raise ExternalReferenceWriteError(
                    "endpoint_document_ownership_missing_in_graph", endpoint_id
                )
            elif path_count > 1:
                divergence_count += path_count - 1

        source_type = references[0].source_type
        existing_targets = _existing_bundle_targets(
            tx,
            source_id=source_id,
            source_type=source_type,
            bundle_id=bundle_id,
        )
        if existing_targets and existing_targets != expected_targets:
            code = (
                "partial_materialized_bundle_in_graph"
                if set(existing_targets) < set(expected_targets)
                else "bundle_target_conflict_in_graph"
            )
            raise ExternalReferenceWriteError(
                code,
                f"existing={existing_targets}, expected={expected_targets}",
                observed_target_ids=existing_targets,
            )

        written_relation_ids: set[str] = set()
        written_target_ids: set[str] = set()
        grouped: dict[str, list[ValidatedExternalReference]] = {}
        for reference in references:
            grouped.setdefault(reference.target_type, []).append(reference)
        for target_type, group in sorted(grouped.items()):
            rows = [
                {
                    "target_id": item.target_id,
                    "relation_id": item.relation.properties["relation_id"],
                    "properties": dict(item.relation.properties),
                }
                for item in group
            ]
            query = (
                f"MATCH (source:{source_type} {{id: $source_id}}) "
                "UNWIND $rows AS row "
                f"MATCH (target:{target_type} {{id: row.target_id}}) "
                "MERGE (source)-[relation:REFERS_TO "
                "{relation_id: row.relation_id}]->(target) "
                "SET relation += row.properties "
                "RETURN target.id AS target_id, "
                "relation.relation_id AS relation_id"
            )
            result_rows = _result_rows(tx.run(query, source_id=source_id, rows=rows))
            written_target_ids.update(str(row["target_id"]) for row in result_rows)
            written_relation_ids.update(str(row["relation_id"]) for row in result_rows)

        expected_relation_ids = {
            str(item.relation.properties["relation_id"]) for item in references
        }
        if written_target_ids != set(expected_targets):
            raise ExternalReferenceWriteError("incomplete_bundle_write_result")
        if written_relation_ids != expected_relation_ids:
            raise ExternalReferenceWriteError("relation_identity_write_mismatch")
        return BundleMaterializationResult(
            reference_bundle_id=bundle_id,
            source_id=source_id,
            expected_target_ids=expected_targets,
            observed_existing_target_ids=existing_targets,
            final_target_ids=tuple(sorted(written_target_ids)),
            relation_ids=tuple(sorted(written_relation_ids)),
            ownership_path_divergence_count=divergence_count,
            matched_existing=bool(existing_targets),
        )


def _verify_endpoint(
    tx: Any,
    *,
    endpoint_id: str,
    endpoint_type: str,
) -> dict[str, Any]:
    _require_label(endpoint_type, TARGET_LABELS, "endpoint")
    if endpoint_type == "Document":
        query = (
            "OPTIONAL MATCH (endpoint:Document {id: $endpoint_id}) "
            "RETURN count(DISTINCT endpoint) AS endpoint_count, "
            "collect(DISTINCT endpoint.id) AS owner_ids, "
            "count(endpoint) AS ownership_path_count"
        )
    else:
        query = (
            f"OPTIONAL MATCH (endpoint:{endpoint_type} {{id: $endpoint_id}}) "
            "OPTIONAL MATCH path=(owner:Document)"
            f"-[:CONTAINS*1..{MAX_DOCUMENT_HIERARCHY_DEPTH}]->(endpoint) "
            "RETURN count(DISTINCT endpoint) AS endpoint_count, "
            "collect(DISTINCT owner.id) AS owner_ids, "
            "count(path) AS ownership_path_count"
        )
    rows = _result_rows(tx.run(query, endpoint_id=endpoint_id))
    if len(rows) != 1:
        raise ExternalReferenceWriteError(
            "endpoint_verification_result_cardinality", endpoint_id
        )
    row = rows[0]
    return {
        "endpoint_count": int(row.get("endpoint_count") or 0),
        "owner_ids": tuple(str(value) for value in (row.get("owner_ids") or ())),
        "ownership_path_count": int(row.get("ownership_path_count") or 0),
    }


def _existing_bundle_targets(
    tx: Any,
    *,
    source_id: str,
    source_type: str,
    bundle_id: str,
) -> tuple[str, ...]:
    _require_label(source_type, SOURCE_LABELS, "source")
    query = (
        f"MATCH (source:{source_type} {{id: $source_id}}) "
        "OPTIONAL MATCH (source)-[existing:REFERS_TO]->(target) "
        "WHERE existing.reference_bundle_id = $bundle_id "
        "RETURN collect(DISTINCT target.id) AS target_ids"
    )
    rows = _result_rows(tx.run(query, source_id=source_id, bundle_id=bundle_id))
    if len(rows) != 1:
        raise ExternalReferenceWriteError("bundle_inspection_result_cardinality")
    return tuple(sorted(str(value) for value in (rows[0].get("target_ids") or ())))


def _require_label(label: str, allowed: frozenset[str], role: str) -> None:
    if label not in allowed:
        raise ExternalReferenceWriteError(f"unsupported_{role}_label", label)


def _result_rows(result: Any) -> list[Mapping[str, Any]]:
    if hasattr(result, "data") and callable(result.data):
        return list(result.data())
    if isinstance(result, Iterable):
        return [dict(row) for row in result]
    raise ExternalReferenceWriteError("neo4j_result_not_consumable")
