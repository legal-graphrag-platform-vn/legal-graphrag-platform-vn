"""Pilot-only development evaluation with explicit unsupported outcomes."""

from __future__ import annotations

import hashlib
import json
import statistics
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.retrieval.errors import RetrievalCapabilityError
from src.retrieval.eval.metrics import (
    calculate_grouped_graded_ndcg_at_k,
    calculate_mrr,
    calculate_recall_at_k,
)
from src.retrieval.models import (
    IntentType,
    RetrievalCapability,
    RetrievalContext,
    RetrievalRequest,
    RetrievedUnit,
)
from src.shared.retrieval_contract import RetrievalFilters


class RuntimeProtocol(Protocol):
    def retrieve(self, request: RetrievalRequest) -> RetrievalContext: ...


class EvaluationReview(BaseModel):
    model_config = ConfigDict(frozen=True)

    reviewer: str = Field(min_length=1)
    status: Literal["pending_human_sign_off", "approved", "rejected"]
    reviewed_at: datetime | None = None

    @model_validator(mode="after")
    def require_timestamp_for_final_review(self) -> "EvaluationReview":
        if self.status != "pending_human_sign_off" and self.reviewed_at is None:
            raise ValueError("A final review status requires reviewed_at")
        return self


class GoldRelevance(BaseModel):
    model_config = ConfigDict(frozen=True)

    unit_id: str = Field(min_length=1)
    relevance: int = Field(ge=1, le=3)
    reason: str = Field(min_length=1)


class GoldGraphPath(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_id: str = Field(min_length=1)
    relation_types: list[str] = Field(min_length=1)
    target_id: str = Field(min_length=1)


class TemporalEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_type: Literal["document_metadata", "statutory_basis"]
    source_id: str = Field(min_length=1)
    required_fields: list[Literal["effective_from", "effective_to", "legal_status"]] = (
        Field(min_length=1)
    )


class GoldTemporal(BaseModel):
    model_config = ConfigDict(frozen=True)

    query_date: date
    subject_unit_id: str = Field(min_length=1)
    temporal_scope_document_id: str = Field(min_length=1)
    expected_valid: bool
    required_metadata: list[
        Literal["effective_from", "effective_to", "legal_status"]
    ] = Field(min_length=1)
    legal_basis_unit_ids: list[str] = Field(default_factory=list)
    temporal_evidence: TemporalEvidence

    @model_validator(mode="after")
    def validate_temporal_evidence(self) -> "GoldTemporal":
        if set(self.required_metadata) != set(self.temporal_evidence.required_fields):
            raise ValueError(
                "temporal_evidence.required_fields must match required_metadata"
            )
        if (
            self.temporal_evidence.source_type == "document_metadata"
            and self.temporal_evidence.source_id != self.temporal_scope_document_id
        ):
            raise ValueError(
                "Document temporal evidence must use temporal_scope_document_id"
            )
        if (
            self.temporal_evidence.source_type == "statutory_basis"
            and self.temporal_evidence.source_id not in self.legal_basis_unit_ids
        ):
            raise ValueError(
                "Statutory temporal evidence must be listed as a legal basis"
            )
        return self


class GoldHierarchy(BaseModel):
    model_config = ConfigDict(frozen=True)

    parent_id: str = Field(min_length=1)
    relation_type: Literal["CONTAINS"]
    child_id: str = Field(min_length=1)


class EvaluationCapabilityRequirement(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: RetrievalCapability
    expected_available: bool
    reason: str = Field(min_length=1)


class DevelopmentEvaluationCase(BaseModel):
    model_config = ConfigDict(frozen=True)

    query_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    intent: IntentType
    expected_status: Literal["supported", "unsupported"]
    capability_requirement: EvaluationCapabilityRequirement
    gold_relevance: list[GoldRelevance] = Field(default_factory=list)
    requires_graph_path: bool = False
    minimum_hops: int = Field(default=0, ge=0)
    graph_case_type: Literal["multi_edge_traversal", "branching_reference"] | None = (
        None
    )
    gold_paths: list[GoldGraphPath] = Field(default_factory=list)
    gold_temporal: GoldTemporal | None = None
    gold_hierarchy: list[GoldHierarchy] = Field(default_factory=list)
    review: EvaluationReview
    force_intent: IntentType | None = None

    @model_validator(mode="after")
    def validate_gold_and_capability(self) -> "DevelopmentEvaluationCase":
        if self.expected_status == "supported" and not self.gold_relevance:
            raise ValueError("Supported evaluation cases require gold_relevance")
        if self.expected_status == "unsupported" and (
            self.capability_requirement.expected_available
        ):
            raise ValueError(
                "Unsupported cases require an unavailable capability expectation"
            )
        unit_ids = [item.unit_id for item in self.gold_relevance]
        if len(unit_ids) != len(set(unit_ids)):
            raise ValueError("gold_relevance unit IDs must be unique per case")
        if self.requires_graph_path and not self.gold_paths:
            raise ValueError("Graph-required cases require gold_paths")
        if self.requires_graph_path and self.minimum_hops < 1:
            raise ValueError("Graph-required cases require minimum_hops >= 1")
        if self.requires_graph_path and self.graph_case_type is None:
            raise ValueError("Graph-required cases require graph_case_type")
        if self.graph_case_type is not None and self.intent is not IntentType.MULTI_HOP:
            raise ValueError("graph_case_type is reserved for multi_hop cases")
        if self.graph_case_type == "multi_edge_traversal" and self.minimum_hops < 2:
            raise ValueError("Multi-edge traversal cases require minimum_hops >= 2")
        if self.graph_case_type == "branching_reference" and (
            self.minimum_hops != 1 or len(self.gold_paths) < 2
        ):
            raise ValueError(
                "Branching reference cases require multiple one-hop gold paths"
            )
        if (
            self.intent is IntentType.VALIDITY
            and self.expected_status == "supported"
            and self.gold_temporal is None
        ):
            raise ValueError("Supported validity cases require gold_temporal")
        if (
            self.intent is IntentType.HIERARCHY
            and self.expected_status == "supported"
            and not self.gold_hierarchy
        ):
            raise ValueError("Supported hierarchy cases require gold_hierarchy")
        return self


class DevelopmentEvaluationDataset(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal["retrieval-evaluation-dataset-v1"]
    evaluation_scope: Literal["pilot_development"]
    name: str = Field(min_length=1)
    document_ids: list[str] = Field(min_length=1)
    target_query_count: int = Field(ge=1)
    review: EvaluationReview
    cases: list[DevelopmentEvaluationCase] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_dataset_contract(self) -> "DevelopmentEvaluationDataset":
        if len(self.cases) != self.target_query_count:
            raise ValueError(
                "Dataset case count does not match target_query_count: "
                f"{len(self.cases)} != {self.target_query_count}"
            )
        query_ids = [item.query_id for item in self.cases]
        if len(query_ids) != len(set(query_ids)):
            raise ValueError("Evaluation query IDs must be unique")
        return self


class DevelopmentEvaluationMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_commit: str
    working_tree_state: str
    runtime_contract_version: str = "retrieval-runtime-v1"
    router_config_hash: str
    embedding_contract: str
    reranker_contract: str
    neo4j_graph_snapshot_hash: str


class DevelopmentEvaluationRunner:
    def __init__(self, profiles: dict[str, RuntimeProtocol]) -> None:
        if not profiles:
            raise ValueError("At least one retrieval runtime profile is required")
        self._profiles = profiles

    def run(
        self,
        dataset_path: str | Path,
        *,
        metadata: DevelopmentEvaluationMetadata,
        filters: RetrievalFilters | None = None,
        top_k: int = 5,
        require_approved_dataset: bool = False,
    ) -> dict[str, Any]:
        path = Path(dataset_path)
        dataset = load_development_dataset(path)
        if require_approved_dataset:
            assert_development_dataset_approved(dataset)
        profile_results = {
            profile: self._evaluate_profile(
                runtime,
                dataset.cases,
                filters=filters or RetrievalFilters(),
                top_k=top_k,
            )
            for profile, runtime in sorted(self._profiles.items())
        }
        return {
            "evaluation_scope": "pilot_development",
            "dataset_hash": hashlib.sha256(path.read_bytes()).hexdigest(),
            "dataset_schema_version": dataset.schema_version,
            "dataset_name": dataset.name,
            "dataset_review": dataset.review.model_dump(mode="json"),
            "official_source_dataset_eligible": _is_approved_dataset(dataset),
            "dataset_case_count": len(dataset.cases),
            "dataset_intent_distribution": _intent_distribution(dataset.cases),
            **metadata.model_dump(mode="json"),
            "profiles": profile_results,
            "Gate 7": "OPEN",
            "M3-B13": "OPEN",
            "Milestone A": "NOT PASSED",
            "Milestone B acceptance": "NOT STARTED",
        }

    def _evaluate_profile(
        self,
        runtime: RuntimeProtocol,
        dataset: list[DevelopmentEvaluationCase],
        *,
        filters: RetrievalFilters,
        top_k: int,
    ) -> dict[str, Any]:
        cases: list[dict[str, Any]] = []
        latencies: list[float] = []
        supported_metrics: list[
            tuple[list[str], list[str], dict[str, int], dict[str, int]]
        ] = []
        for item in dataset:
            force_intent = item.force_intent
            request = RetrievalRequest(
                query=item.query,
                filters=filters,
                top_k=max(top_k, 20),
                final_k=top_k,
                force_intent=force_intent,
            )
            started = time.perf_counter()
            try:
                context = runtime.retrieve(request)
            except RetrievalCapabilityError as exc:
                latencies.append((time.perf_counter() - started) * 1000)
                cases.append(
                    {
                        "query_id": item.query_id,
                        "status": "unsupported",
                        "expected_status": item.expected_status,
                        "expectation_match": (
                            item.expected_status == "unsupported"
                            and exc.required_capability
                            == item.capability_requirement.name.value
                        ),
                        "expected_intent": item.intent.value,
                        "reason": str(exc),
                        "required_capability": exc.required_capability,
                        "available_capability": exc.available_capability,
                        "force_intent_used": force_intent is not None,
                    }
                )
                continue
            latencies.append((time.perf_counter() - started) * 1000)
            retrieved_ids = [unit.id for unit in context.retrieved_units]
            group_by_id = {
                gold.unit_id: _structural_relevance_group(gold.unit_id)
                for gold in item.gold_relevance
            }
            expected_groups = list(dict.fromkeys(group_by_id.values()))
            relevance_by_id = {
                gold.unit_id: gold.relevance for gold in item.gold_relevance
            }
            retrieved_groups, returned_relevance_by_group = (
                _collapse_retrieved_relevance_groups(
                    retrieved_ids,
                    relevance_by_id=relevance_by_id,
                    group_by_id=group_by_id,
                )
            )
            ideal_relevance_by_group: dict[str, int] = {}
            for gold in item.gold_relevance:
                group_id = group_by_id[gold.unit_id]
                ideal_relevance_by_group[group_id] = max(
                    ideal_relevance_by_group.get(group_id, 0), gold.relevance
                )
            expectation_match = item.expected_status == "supported"
            if expectation_match:
                supported_metrics.append(
                    (
                        retrieved_groups,
                        expected_groups,
                        returned_relevance_by_group,
                        ideal_relevance_by_group,
                    )
                )
            graph_path_hit = _graph_path_hit(item, context)
            temporal_evaluation = _temporal_evaluation(item, context)
            hierarchy_hit = _hierarchy_hit(item, context)
            cases.append(
                {
                    "query_id": item.query_id,
                    "status": "supported",
                    "expected_status": item.expected_status,
                    "expectation_match": expectation_match,
                    "expected_intent": item.intent.value,
                    "actual_intent": context.intent.value,
                    "intent_match": context.intent == item.intent,
                    "force_intent_used": context.force_intent_used,
                    "retrieved_ids": retrieved_ids,
                    "retrieved_relevance_groups": retrieved_groups,
                    "returned_relevance_by_group": returned_relevance_by_group,
                    "graph_path_required": item.requires_graph_path,
                    "graph_case_type": item.graph_case_type,
                    "graph_path_hit": graph_path_hit,
                    "temporal_evaluation": temporal_evaluation,
                    "hierarchy_relation_hit": hierarchy_hit,
                }
            )
        expectation_mismatch_count = sum(
            not bool(case["expectation_match"]) for case in cases
        )
        return {
            "metrics": _aggregate_metrics(supported_metrics, top_k),
            "supported_count": sum(case["status"] == "supported" for case in cases),
            "unsupported_count": sum(case["status"] == "unsupported" for case in cases),
            "expectation_mismatch_count": expectation_mismatch_count,
            "outcomes_by_intent": _outcomes_by_intent(cases),
            "metric_unit": "relevance_group",
            "graph_path_hit_rate": _graph_path_hit_rate(cases),
            "temporal_decision_accuracy": _nested_boolean_rate(
                cases, "temporal_evaluation", "temporal_decision_correct"
            ),
            "temporal_evidence_completeness": _nested_boolean_rate(
                cases, "temporal_evaluation", "temporal_evidence_complete"
            ),
            "hierarchy_relation_hit_rate": _boolean_rate(
                cases, "hierarchy_relation_hit"
            ),
            "development_latency_distribution": _latency_distribution(latencies),
            "cases": cases,
        }


def write_development_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def load_development_dataset(path: Path) -> DevelopmentEvaluationDataset:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return DevelopmentEvaluationDataset.model_validate(payload)


def _is_approved_dataset(dataset: DevelopmentEvaluationDataset) -> bool:
    return dataset.review.status == "approved" and all(
        case.review.status == "approved" for case in dataset.cases
    )


def assert_development_dataset_approved(
    dataset: DevelopmentEvaluationDataset,
) -> None:
    if not _is_approved_dataset(dataset):
        raise ValueError(
            "Official evaluation requires approved dataset and case reviews"
        )


def _intent_distribution(
    cases: list[DevelopmentEvaluationCase],
) -> dict[str, int]:
    return {
        intent.value: sum(case.intent is intent for case in cases)
        for intent in IntentType
    }


def _outcomes_by_intent(cases: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    outcomes = {
        intent.value: {"supported": 0, "unsupported": 0} for intent in IntentType
    }
    for case in cases:
        intent = str(case["expected_intent"])
        status = str(case["status"])
        outcomes[intent][status] += 1
    return outcomes


def _graph_path_hit(
    item: DevelopmentEvaluationCase, context: RetrievalContext
) -> bool | None:
    if not item.requires_graph_path:
        return None
    path_hits = [
        any(
            bool(path.nodes)
            and len(path.relations) >= item.minimum_hops
            and path.nodes[0] == gold.source_id
            and path.nodes[-1] == gold.target_id
            and path.relations == gold.relation_types
            for path in context.graph_paths
        )
        for gold in item.gold_paths
    ]
    if item.graph_case_type == "branching_reference":
        return all(path_hits)
    return any(path_hits)


def _graph_path_hit_rate(cases: list[dict[str, Any]]) -> float | None:
    required = [case for case in cases if case.get("graph_path_required")]
    if not required:
        return None
    return statistics.fmean(bool(case.get("graph_path_hit")) for case in required)


def _temporal_evaluation(
    item: DevelopmentEvaluationCase, context: RetrievalContext
) -> dict[str, bool | str] | None:
    gold = item.gold_temporal
    if gold is None:
        return None
    retrieved = {unit.id: unit for unit in context.retrieved_units}
    evidence_ids = {gold.subject_unit_id, *gold.legal_basis_unit_ids}
    subject_hit = bool(evidence_ids & retrieved.keys())
    evidence = gold.temporal_evidence
    if evidence.source_type == "document_metadata":
        evidence_units = [
            unit
            for unit in retrieved.values()
            if unit.document_id == evidence.source_id
        ]
    else:
        evidence_units = [
            unit for unit in retrieved.values() if unit.id == evidence.source_id
        ]
    metadata_complete = any(
        _temporal_metadata_complete(unit, evidence.required_fields)
        for unit in evidence_units
    )
    return {
        "subject_retrieval_hit": subject_hit,
        "temporal_decision_correct": (
            context.temporal.resolved_from == gold.query_date
            and subject_hit == gold.expected_valid
        ),
        "temporal_evidence_complete": metadata_complete,
        "temporal_evidence_source_type": evidence.source_type,
        "temporal_evidence_source_id": evidence.source_id,
    }


def _temporal_metadata_complete(
    unit: RetrievedUnit,
    required_fields: list[str],
) -> bool:
    for field in required_fields:
        value = getattr(unit, field)
        if field != "effective_to" and value is None:
            return False
    return True


def _hierarchy_hit(
    item: DevelopmentEvaluationCase, context: RetrievalContext
) -> bool | None:
    if not item.gold_hierarchy:
        return None
    observed = {
        (source, relation, target)
        for path in context.graph_paths
        for source, relation, target in zip(
            path.nodes, path.relations, path.nodes[1:], strict=False
        )
    }
    return all(
        (gold.parent_id, gold.relation_type, gold.child_id) in observed
        for gold in item.gold_hierarchy
    )


def _boolean_rate(cases: list[dict[str, Any]], key: str) -> float | None:
    values = [case[key] for case in cases if case.get(key) is not None]
    return statistics.fmean(values) if values else None


def _nested_boolean_rate(
    cases: list[dict[str, Any]], container: str, key: str
) -> float | None:
    values = [case[container][key] for case in cases if case.get(container) is not None]
    return statistics.fmean(values) if values else None


def _structural_relevance_group(unit_id: str) -> str:
    article_id = unit_id.split("_cl", maxsplit=1)[0]
    return f"legal_basis:{article_id}"


def _collapse_retrieved_relevance_groups(
    retrieved_ids: list[str],
    *,
    relevance_by_id: dict[str, int],
    group_by_id: dict[str, str],
) -> tuple[list[str], dict[str, int]]:
    ordered_groups: list[str] = []
    returned_relevance: dict[str, int] = {}
    for unit_id in retrieved_ids:
        group_id = group_by_id.get(unit_id, f"unjudged:{unit_id}")
        if group_id not in returned_relevance:
            ordered_groups.append(group_id)
        returned_relevance[group_id] = max(
            returned_relevance.get(group_id, 0), relevance_by_id.get(unit_id, 0)
        )
    return ordered_groups, returned_relevance


def _aggregate_metrics(
    cases: list[tuple[list[str], list[str], dict[str, int], dict[str, int]]],
    top_k: int,
) -> dict[str, float | int]:
    if not cases:
        return {"sample_size": 0}
    return {
        "sample_size": len(cases),
        f"Recall@{top_k}": statistics.fmean(
            calculate_recall_at_k(retrieved, expected, k=top_k)
            for retrieved, expected, _, _ in cases
        ),
        "MRR": statistics.fmean(
            calculate_mrr(retrieved, expected) for retrieved, expected, _, _ in cases
        ),
        f"nDCG@{top_k}": statistics.fmean(
            calculate_grouped_graded_ndcg_at_k(
                retrieved,
                returned_relevance,
                ideal_relevance,
                k=top_k,
            )
            for retrieved, _, returned_relevance, ideal_relevance in cases
        ),
        "no_results_rate": statistics.fmean(
            not retrieved for retrieved, _, _, _ in cases
        ),
    }


def _latency_distribution(values: list[float]) -> dict[str, float | int]:
    if not values:
        return {"sample_size": 0}
    ordered = sorted(values)
    p95_index = min(len(ordered) - 1, max(0, int(len(ordered) * 0.95) - 1))
    return {
        "sample_size": len(ordered),
        "p50_ms": statistics.median(ordered),
        "p95_ms": ordered[p95_index],
    }
