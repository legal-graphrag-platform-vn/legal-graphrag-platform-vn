"""Deterministic execution and validation of bound exact-linear plans."""

from __future__ import annotations

import hashlib
import json
from typing import Mapping

from pydantic import BaseModel, ConfigDict

from src.retrieval.errors import RetrievalOutputError
from src.retrieval.models import GraphPath, GraphReasoningRequirement, RetrievalFilters
from src.retrieval.path_identity import build_topology_path_fingerprint
from src.retrieval.planning.models import (
    BoundSemanticPlan,
    PlanExecutionResult,
    PlanExecutionStatus,
    PlanReasonCode,
)
from src.retrieval.planning.patterns import SEMANTIC_LIFTABLE_TARGETS, QueryDirection
from src.retrieval.ports import PlannedPathLookupPort
from src.retrieval.retriever.graph import (
    deduplicate_topology_paths,
    graph_path_rank_key,
    is_graph_path_temporally_valid,
    map_graph_path,
)


DEFAULT_MAX_EXACT_PATHS = 20


class PlannedPathExecution(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    result: PlanExecutionResult
    paths: tuple[GraphPath, ...] = ()
    path_fingerprints: tuple[str, ...] = ()
    citable_unit_ids: tuple[str, ...] = ()


class PlannedPathExecutor:
    def __init__(
        self,
        lookup: PlannedPathLookupPort,
        *,
        max_paths: int = DEFAULT_MAX_EXACT_PATHS,
    ) -> None:
        if not 1 <= max_paths <= 100:
            raise ValueError("Exact path budget must be between 1 and 100")
        self._lookup = lookup
        self._max_paths = max_paths

    def execute(
        self,
        plan: BoundSemanticPlan,
        *,
        filters: RetrievalFilters,
    ) -> PlannedPathExecution:
        plan_fingerprint = _build_plan_fingerprint(plan)
        rows = self._lookup.lookup_exact_paths(
            anchor_id=plan.bound_anchor.node_id,
            target_id=plan.bound_target.node_id,
            steps=tuple(
                {
                    "relation": step.relation.value,
                    "direction": step.direction.value,
                    "next_label": step.next_label.value,
                }
                for step in plan.unlinked.steps
            ),
            filters=filters,
            limit=self._max_paths + 1,
        )
        if len(rows) > self._max_paths:
            return self._failed(
                plan, plan_fingerprint, PlanReasonCode.PATH_BUDGET_EXCEEDED
            )
        if not rows:
            return self._failed(plan, plan_fingerprint, PlanReasonCode.NO_PATH)

        mapped_paths = [map_graph_path(dict(row)) for row in rows]
        for path in mapped_paths:
            _validate_exact_path(path, plan)
        temporal_paths = [
            path
            for path in mapped_paths
            if is_graph_path_temporally_valid(path, filters.query_date)
        ]
        if not temporal_paths:
            return self._failed(
                plan, plan_fingerprint, PlanReasonCode.TEMPORAL_REJECTED
            )

        paths = deduplicate_topology_paths(temporal_paths)
        paths.sort(key=graph_path_rank_key)
        if len(paths) > 1:
            return self._failed(plan, plan_fingerprint, PlanReasonCode.AMBIGUOUS_PATH)

        path = paths[0]
        citable_unit_ids = _citable_unit_ids(path)
        if (
            plan.unlinked.target_label in SEMANTIC_LIFTABLE_TARGETS
            and not citable_unit_ids
        ):
            return self._failed(
                plan, plan_fingerprint, PlanReasonCode.EVIDENCE_UNLIFTABLE
            )

        path_fingerprint = build_topology_path_fingerprint(path)
        result = PlanExecutionResult(
            plan_fingerprint=plan_fingerprint,
            satisfied_path_fingerprints=(path_fingerprint,),
            bound_anchor_id=plan.bound_anchor.node_id,
            bound_target_id=plan.bound_target.node_id,
            execution_status=PlanExecutionStatus.SATISFIED,
            reason_code=PlanReasonCode.SATISFIED,
            derived_reasoning_requirement=GraphReasoningRequirement(
                minimum_edges=len(plan.unlinked.steps),
                required_relation_types=tuple(
                    step.relation.value for step in plan.unlinked.steps
                ),
            ),
        )
        return PlannedPathExecution(
            result=result,
            paths=(path,),
            path_fingerprints=(path_fingerprint,),
            citable_unit_ids=citable_unit_ids,
        )

    @staticmethod
    def _failed(
        plan: BoundSemanticPlan,
        plan_fingerprint: str,
        reason: PlanReasonCode,
    ) -> PlannedPathExecution:
        return PlannedPathExecution(
            result=PlanExecutionResult(
                plan_fingerprint=plan_fingerprint,
                satisfied_path_fingerprints=(),
                bound_anchor_id=plan.bound_anchor.node_id,
                bound_target_id=plan.bound_target.node_id,
                execution_status=PlanExecutionStatus.FAILED,
                reason_code=reason,
                message=_FAILURE_MESSAGES[reason],
            )
        )


def _validate_exact_path(path: GraphPath, plan: BoundSemanticPlan) -> None:
    steps = plan.unlinked.steps
    if len(path.edges) != len(steps) or len(path.nodes) != len(steps) + 1:
        raise RetrievalOutputError("Exact path depth differs from the bound plan")
    if path.nodes[0].node_id != plan.bound_anchor.node_id:
        raise RetrievalOutputError("Exact path does not start at the bound anchor")
    if path.nodes[-1].node_id != plan.bound_target.node_id:
        raise RetrievalOutputError("Exact path does not end at the bound target")
    node_ids = tuple(node.node_id for node in path.nodes)
    if len(node_ids) != len(set(node_ids)):
        raise RetrievalOutputError("Exact path contains a cycle")
    if plan.bound_anchor.label.value not in path.nodes[0].labels:
        raise RetrievalOutputError(
            "Exact path anchor label differs from the bound plan"
        )

    for index, (current, edge, following, step) in enumerate(
        zip(path.nodes[:-1], path.edges, path.nodes[1:], steps, strict=True), start=1
    ):
        if edge.relation_type != step.relation.value:
            raise RetrievalOutputError(f"Exact path step {index} relation mismatch")
        if step.next_label.value not in following.labels:
            raise RetrievalOutputError(f"Exact path step {index} label mismatch")
        expected_endpoints = (
            (current.node_id, following.node_id)
            if step.direction is QueryDirection.OUTGOING
            else (following.node_id, current.node_id)
        )
        if (edge.source_id, edge.target_id) != expected_endpoints:
            raise RetrievalOutputError(f"Exact path step {index} direction mismatch")


def _citable_unit_ids(path: GraphPath) -> tuple[str, ...]:
    ordered: dict[str, None] = {}
    for node in path.nodes:
        if node.citable_unit_id:
            ordered.setdefault(node.citable_unit_id, None)
    return tuple(ordered)


def _build_plan_fingerprint(plan: BoundSemanticPlan) -> str:
    canonical = json.dumps(
        plan.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "plan_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]


_FAILURE_MESSAGES: Mapping[PlanReasonCode, str] = {
    PlanReasonCode.NO_PATH: "No exact ordered path exists",
    PlanReasonCode.AMBIGUOUS_PATH: "Multiple exact path topologies exist",
    PlanReasonCode.PATH_BUDGET_EXCEEDED: "Exact path result exceeded its budget",
    PlanReasonCode.TEMPORAL_REJECTED: "Exact paths are invalid at the query date",
    PlanReasonCode.EVIDENCE_UNLIFTABLE: "Satisfied path has no citable legal unit",
}
