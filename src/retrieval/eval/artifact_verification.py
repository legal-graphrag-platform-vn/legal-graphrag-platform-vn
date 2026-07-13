"""Artifact-level verification for the pilot retrieval evaluation dataset."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from src.retrieval.eval.development import DevelopmentEvaluationDataset
from src.shared.ontology.payload_consistency_validator import (
    deterministic_relation_id,
    relation_identity_discriminator,
)
from src.shared.retrieval_contract import RetrievalCapability


_CAPABILITY_FIELDS: dict[RetrievalCapability, tuple[str, ...]] = {
    RetrievalCapability.HYBRID_SEED_AND_SEMANTIC_GRAPH: (
        "vector_article_index_available",
        "vector_clause_index_available",
        "fulltext_index_available",
        "semantic_multi_hop_graph_available",
    ),
    RetrievalCapability.LEXICAL_DEFINITION: ("fulltext_index_available",),
    RetrievalCapability.SEMANTIC_MULTI_HOP_GRAPH: (
        "semantic_multi_hop_graph_available",
    ),
    RetrievalCapability.SCOPED_TEMPORAL_METADATA: (
        "scoped_temporal_metadata_available",
    ),
    RetrievalCapability.CORPUS_COMPLETE_CURRENT_VALIDITY: (
        "corpus_complete_current_validity_available",
    ),
    RetrievalCapability.VERSION_CHAIN_VALIDITY: ("temporal_relations_available",),
    RetrievalCapability.STRUCTURAL_HIERARCHY: ("structural_hierarchy_available",),
    RetrievalCapability.GUIDES_RELATIONS: ("guides_relations_available",),
    RetrievalCapability.MULTIPLE_VERSIONS: ("multiple_versions_available",),
}
_SCOPED_VALID_STATUSES = {
    "Document": {"ACTIVE", "PARTIALLY_EFFECTIVE"},
    "Article": {"ACTIVE", "AMENDED"},
    "Clause": {"ACTIVE", "AMENDED"},
}
_CAPABILITY_QUERY_VERSION = "neo4j-retrieval-capability-v1"


def build_artifact_verification(
    *,
    dataset: DevelopmentEvaluationDataset,
    dataset_path: Path,
    hierarchy_path: Path,
    accepted_path: Path,
    graph_snapshot_path: Path,
    capabilities: dict[str, object],
    temporal_units: list[dict[str, Any]],
    runtime_identity: dict[str, object],
    source_commit: str,
    working_tree_state: str,
    verification_command_hash: str,
) -> dict[str, Any]:
    hierarchy = json.loads(hierarchy_path.read_text(encoding="utf-8"))
    graph_snapshot = json.loads(graph_snapshot_path.read_text(encoding="utf-8"))
    relation_records = _load_relation_records(accepted_path)
    relation_records.extend(_hierarchy_relation_records(hierarchy))

    graph_paths = []
    for case in dataset.cases:
        for gold in case.gold_paths:
            matches = _resolve_paths(
                source_id=gold.source_id,
                target_id=gold.target_id,
                relation_types=gold.relation_types,
                records=relation_records,
            )
            graph_paths.append(
                {
                    "query_id": case.query_id,
                    "graph_case_type": case.graph_case_type,
                    "expected": gold.model_dump(mode="json"),
                    "matched": bool(matches),
                    "resolved_path": matches[0] if matches else None,
                }
            )

    hierarchy_relations = []
    relation_index = {
        (record["source_id"], record["relation_type"], record["target_id"]): record
        for record in relation_records
    }
    for case in dataset.cases:
        for gold in case.gold_hierarchy:
            key = (gold.parent_id, gold.relation_type, gold.child_id)
            hierarchy_relations.append(
                {
                    "query_id": case.query_id,
                    "expected": gold.model_dump(mode="json"),
                    "matched": key in relation_index,
                    "record": relation_index.get(key),
                }
            )

    capability_checks = _capability_checks(dataset, capabilities)
    document_metadata = dict(hierarchy["document"])
    temporal_by_id = {str(unit["id"]): unit for unit in temporal_units}
    temporal_checks = [
        _temporal_check(case, document_metadata, temporal_by_id)
        for case in dataset.cases
        if case.gold_temporal is not None
    ]

    graph_path_pass = all(item["matched"] for item in graph_paths)
    hierarchy_pass = all(item["matched"] for item in hierarchy_relations)
    temporal_pass = all(item["matched"] for item in temporal_checks)
    capability_pass = all(item["matched"] for item in capability_checks)
    technical_checks_status = (
        "PASS"
        if all((graph_path_pass, hierarchy_pass, temporal_pass, capability_pass))
        else "FAIL"
    )
    approved_dataset = dataset.review.status == "approved" and all(
        case.review.status == "approved" for case in dataset.cases
    )
    official_evidence_eligible = (
        technical_checks_status == "PASS"
        and approved_dataset
        and working_tree_state == "clean"
        and source_commit != ""
    )
    return {
        "contract_version": "retrieval-evaluation-artifact-verification-v1",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "verifier_contract_version": "retrieval-evaluation-artifact-verification-v1",
        "source_commit": source_commit,
        "verifier_source_commit": source_commit,
        "working_tree_state": working_tree_state,
        "technical_checks_status": technical_checks_status,
        "evidence_tier": (
            "official_candidate" if official_evidence_eligible else "development"
        ),
        "official_evidence_eligible": official_evidence_eligible,
        "verification_command_hash": verification_command_hash,
        "runtime_config_hash": _hash_json({"document_ids": dataset.document_ids}),
        "capability_query_version": _CAPABILITY_QUERY_VERSION,
        "capability_query_hash": hashlib.sha256(
            _CAPABILITY_QUERY_VERSION.encode("utf-8")
        ).hexdigest(),
        "neo4j_runtime": _json_safe(runtime_identity),
        "document_ids": dataset.document_ids,
        "input_hashes": {
            "dataset_sha256": _sha256(dataset_path),
            "accepted_relations_sha256": _sha256(accepted_path),
            "hierarchy_sha256": _sha256(hierarchy_path),
            "graph_snapshot_sha256": _sha256(graph_snapshot_path),
            "graph_projection_sha256": graph_snapshot.get("graph_projection_sha256"),
        },
        "accepted_refers_to_records": _matched_refers_to_records(graph_paths),
        "graph_path_checks": graph_paths,
        "hierarchy_relation_checks": hierarchy_relations,
        "document_metadata": document_metadata,
        "temporal_evidence_checks": temporal_checks,
        "capability_snapshot": _json_safe(capabilities),
        "capability_checks": capability_checks,
        "verification": {
            "graph_paths_pass": graph_path_pass,
            "hierarchy_relations_pass": hierarchy_pass,
            "temporal_evidence_pass": temporal_pass,
            "capabilities_pass": capability_pass,
            "status": technical_checks_status,
        },
        "Gate 7": "OPEN",
        "M3-B13": "OPEN",
        "Milestone A": "NOT PASSED",
        "official_evaluation": "NOT STARTED",
    }


def _load_relation_records(path: Path) -> list[dict[str, Any]]:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        relation = payload.get("relation") or {}
        relation_type = relation.get("relation") or relation["type"]
        properties = relation.get("properties") or {}
        discriminator = relation_identity_discriminator(relation_type, properties)
        canonical_relation_id = deterministic_relation_id(
            relation["head"], relation_type, relation["tail"], discriminator
        )
        records.append(
            {
                "source_id": relation["head"],
                "relation_type": relation_type,
                "target_id": relation["tail"],
                "source_relation_id": relation.get("relation_id")
                or (relation.get("properties") or {}).get("relation_id"),
                "relation_id": canonical_relation_id,
                "relation_id_source": "derived_canonical_contract",
                "identity_discriminator": discriminator,
                "properties": properties,
                "source_artifact": "accepted.jsonl",
            }
        )
    return records


def _hierarchy_relation_records(hierarchy: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    document_id = hierarchy["document"]["id"]
    for article in hierarchy["articles"]:
        article_id = f"{document_id}_art{article['number']}"
        records.append(_contains_record(document_id, article_id))
        for clause in article.get("clauses", []):
            clause_id = f"{article_id}_cl{clause['number']}"
            records.append(_contains_record(article_id, clause_id))
            for point in clause.get("points", []):
                point_label = "dd" if point["label"] == "đ" else point["label"]
                records.append(
                    _contains_record(clause_id, f"{clause_id}_p{point_label}")
                )
    return records


def _contains_record(source_id: str, target_id: str) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "relation_type": "CONTAINS",
        "target_id": target_id,
        "relation_id": None,
        "properties": {},
        "source_artifact": "hierarchy.json",
    }


def _resolve_paths(
    *,
    source_id: str,
    target_id: str,
    relation_types: list[str],
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    paths: list[tuple[list[str], list[dict[str, Any]]]] = [([source_id], [])]
    for relation_type in relation_types:
        next_paths = []
        for nodes, edges in paths:
            for record in records:
                if (
                    record["source_id"] == nodes[-1]
                    and record["relation_type"] == relation_type
                ):
                    next_paths.append((nodes + [record["target_id"]], edges + [record]))
        paths = next_paths
    resolved = [
        {"nodes": nodes, "edges": edges}
        for nodes, edges in paths
        if nodes[-1] == target_id
    ]
    return sorted(resolved, key=lambda item: item["nodes"])


def _capability_checks(
    dataset: DevelopmentEvaluationDataset,
    capabilities: dict[str, object],
) -> list[dict[str, Any]]:
    checks = []
    seen: set[RetrievalCapability] = set()
    for case in dataset.cases:
        requirement = case.capability_requirement
        if requirement.name in seen:
            continue
        seen.add(requirement.name)
        fields = _CAPABILITY_FIELDS[requirement.name]
        values = {field: bool(capabilities.get(field)) for field in fields}
        actual = all(values.values())
        checks.append(
            {
                "capability": requirement.name.value,
                "expected_available": requirement.expected_available,
                "actual_available": actual,
                "source_fields": values,
                "matched": actual is requirement.expected_available,
            }
        )
    return sorted(checks, key=lambda item: item["capability"])


def _matched_refers_to_records(
    graph_paths: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    records: dict[tuple[str, str, str], dict[str, Any]] = {}
    for path in graph_paths:
        resolved = path.get("resolved_path") or {}
        for edge in resolved.get("edges", []):
            if edge["relation_type"] == "REFERS_TO":
                key = (edge["source_id"], edge["relation_type"], edge["target_id"])
                records[key] = edge
    return [records[key] for key in sorted(records)]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _hash_json(value: object) -> str:
    payload = json.dumps(
        _json_safe(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _temporal_check(
    case: Any,
    document_metadata: dict[str, Any],
    temporal_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    gold = case.gold_temporal
    evidence = gold.temporal_evidence
    subject = temporal_by_id.get(gold.subject_unit_id)
    subject_properties = dict(subject.get("properties") or {}) if subject else {}
    labels = [str(label) for label in (subject or {}).get("labels", [])]
    primary_label = next(
        (label for label in ("Document", "Article", "Clause") if label in labels),
        None,
    )
    effective_from = _as_date((subject or {}).get("effective_from"))
    effective_to = _as_date((subject or {}).get("effective_to"))
    legal_status = (subject or {}).get("legal_status")
    allowed_statuses = _SCOPED_VALID_STATUSES.get(primary_label or "", set())
    effective_from_check = (
        effective_from is not None and effective_from <= gold.query_date
    )
    effective_to_check = effective_to is None or effective_to > gold.query_date
    legal_status_check = legal_status in allowed_statuses
    computed_valid = effective_from_check and effective_to_check and legal_status_check
    source_values = {
        field: document_metadata.get(field) for field in evidence.required_fields
    }
    source_presence = {
        field: field in document_metadata for field in evidence.required_fields
    }
    source_matched = evidence.source_id == document_metadata["id"] and all(
        field == "effective_to" or document_metadata.get(field) is not None
        for field in evidence.required_fields
    )
    return {
        "query_id": case.query_id,
        "source_id": evidence.source_id,
        "source_type": evidence.source_type,
        "required_fields": evidence.required_fields,
        "values": source_values,
        "field_presence": source_presence,
        "normalization": {"missing_effective_to_means": "open_ended"},
        "subject_snapshot": {
            "id": gold.subject_unit_id,
            "labels": labels,
            "field_presence": {
                field: field in subject_properties
                for field in ("effective_from", "effective_to", "legal_status")
            },
            "effective_from": _date_string(effective_from),
            "effective_to": _date_string(effective_to),
            "legal_status": legal_status,
        },
        "predicate_evaluation": {
            "query_date": gold.query_date.isoformat(),
            "interval_convention": (
                "effective_from <= query_date AND "
                "(effective_to IS NULL OR effective_to > query_date)"
            ),
            "legal_status_rule": {
                "subject_label": primary_label,
                "allowed_statuses": sorted(allowed_statuses),
                "document_partially_effective_scope": (
                    "PARTIALLY_EFFECTIVE permits document-scoped evaluation but "
                    "child units are decided from their own persisted metadata"
                ),
            },
            "effective_from_check": effective_from_check,
            "effective_to_check": effective_to_check,
            "legal_status_check": legal_status_check,
            "computed_valid": computed_valid,
            "expected_valid": gold.expected_valid,
            "matched": computed_valid is gold.expected_valid,
        },
        "matched": source_matched and computed_valid is gold.expected_valid,
    }


def _as_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _date_string(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


def _json_safe(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (set, frozenset, tuple)):
        return sorted(_json_safe(item) for item in value)
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value
