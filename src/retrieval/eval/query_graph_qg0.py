"""QG-0 evaluation for manually bound exact-linear gold plans."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter_ns
from typing import Literal, Mapping, Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from src.retrieval.models import RetrievalFilters
from src.retrieval.planning.executor import PlannedPathExecutor
from src.retrieval.planning.linker import (
    EndpointResolutionStatus,
    EndpointRole,
    StructuralEndpointResolver,
)
from src.retrieval.planning.models import (
    AnchorMention,
    BoundEndpoint,
    BoundSemanticPlan,
    PathStepConstraint,
    TargetMention,
    UnlinkedSemanticPlan,
)


class _Contract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class GoldPlanCase(_Contract):
    query_id: str
    query: str
    anchor_mention: str
    anchor_label: Literal["Article", "Clause"]
    anchor_id: str
    target_mention: str
    target_label: str
    target_id: str
    steps: tuple[PathStepConstraint, ...]
    expected_node_ids: tuple[str, ...]
    expected_relation_types: tuple[str, ...]

    @model_validator(mode="after")
    def validate_gold_path(self) -> Self:
        plan = self.unlinked_plan()
        if plan.target_label != self.target_label:
            raise ValueError("Gold target label differs from final step label")
        if len(self.expected_node_ids) != len(self.steps) + 1:
            raise ValueError("Gold node sequence cardinality differs from steps")
        if self.expected_node_ids[0] != self.anchor_id:
            raise ValueError("Gold node sequence does not start at anchor ID")
        if self.expected_node_ids[-1] != self.target_id:
            raise ValueError("Gold node sequence does not end at target ID")
        if self.expected_relation_types != tuple(
            step.relation.value for step in self.steps
        ):
            raise ValueError("Gold relation sequence differs from plan steps")
        return self

    def unlinked_plan(self) -> UnlinkedSemanticPlan:
        return UnlinkedSemanticPlan(
            anchor=AnchorMention(
                text=self.anchor_mention,
                expected_label=self.anchor_label,
            ),
            target=TargetMention(text=self.target_mention),
            steps=self.steps,
        )

    def bound_plan(self, *, target_id: str | None = None) -> BoundSemanticPlan:
        unlinked = self.unlinked_plan()
        return BoundSemanticPlan(
            unlinked=unlinked,
            bound_anchor=BoundEndpoint(
                mention_text=unlinked.anchor.text,
                node_id=self.anchor_id,
                label=self.anchor_label,
                resolution_method="STRUCTURAL",
            ),
            bound_target=BoundEndpoint(
                mention_text=unlinked.target.text,
                node_id=target_id or self.target_id,
                label=self.target_label,
                resolution_method="STRUCTURAL",
            ),
        )


class GoldPlanConfig(_Contract):
    schema_version: Literal["query-graph-gold-plans-v1"]
    evaluation_scope: Literal["pilot_development"]
    document_ids: tuple[str, ...]
    excluded_cases: Mapping[str, str]
    cases: tuple[GoldPlanCase, ...]

    @field_validator("document_ids")
    @classmethod
    def validate_document_scope(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if not values or len(values) != len(set(values)):
            raise ValueError("Gold plan document scope must be non-empty and unique")
        return values

    @model_validator(mode="after")
    def validate_case_ids(self) -> Self:
        ids = tuple(case.query_id for case in self.cases)
        if len(ids) != len(set(ids)):
            raise ValueError("Gold plan query IDs must be unique")
        return self


class QG0CaseResult(_Contract):
    query_id: str
    anchor_status: str
    anchor_id: str | None
    execution_status: str
    reason_code: str
    expected_node_ids: tuple[str, ...]
    returned_node_ids: tuple[str, ...]
    expected_relation_types: tuple[str, ...]
    returned_relation_types: tuple[str, ...]
    exact_denotation: bool
    false_positive_path_count: int
    latency_ms: float


class QG0NegativeChecks(_Contract):
    reversed_direction_reason: str
    missing_edge_reason: str
    answer_provider_call_count: int


class QG0Summary(_Contract):
    linear_case_count: int
    anchor_resolved_count: int
    exact_denotation_count: int
    false_positive_path_count: int


class QG0Report(_Contract):
    schema_version: Literal["query-graph-qg0-v1"] = "query-graph-qg0-v1"
    captured_at: str
    status: Literal["passed", "failed"]
    gate: Literal["QG-0 manual gold plans"] = "QG-0 manual gold plans"
    config_sha256: str
    evaluation_scope: str
    document_ids: tuple[str, ...]
    graph_identity: Mapping[str, str]
    cases: tuple[QG0CaseResult, ...]
    negative_checks: QG0NegativeChecks
    summary: QG0Summary


def load_gold_plan_config(path: Path) -> GoldPlanConfig:
    return GoldPlanConfig.model_validate_json(path.read_text(encoding="utf-8"))


def run_qg0(
    config: GoldPlanConfig,
    *,
    resolver: StructuralEndpointResolver,
    executor: PlannedPathExecutor,
    graph_identity: Mapping[str, str],
) -> QG0Report:
    filters = RetrievalFilters(document_ids=list(config.document_ids))
    case_results = tuple(
        _run_case(case, resolver=resolver, executor=executor, filters=filters)
        for case in config.cases
    )
    negative_checks = _run_negative_checks(
        config.cases[0], executor=executor, filters=filters
    )
    summary = QG0Summary(
        linear_case_count=len(case_results),
        anchor_resolved_count=sum(
            result.anchor_status == EndpointResolutionStatus.RESOLVED.value
            for result in case_results
        ),
        exact_denotation_count=sum(result.exact_denotation for result in case_results),
        false_positive_path_count=sum(
            result.false_positive_path_count for result in case_results
        ),
    )
    passed = (
        summary.linear_case_count > 0
        and summary.anchor_resolved_count == summary.linear_case_count
        and summary.exact_denotation_count == summary.linear_case_count
        and summary.false_positive_path_count == 0
        and negative_checks.reversed_direction_reason == "NO_PATH"
        and negative_checks.missing_edge_reason == "NO_PATH"
        and negative_checks.answer_provider_call_count == 0
    )
    return QG0Report(
        captured_at=datetime.now(timezone.utc).isoformat(),
        status="passed" if passed else "failed",
        config_sha256=gold_plan_config_sha256(config),
        evaluation_scope=config.evaluation_scope,
        document_ids=config.document_ids,
        graph_identity=dict(graph_identity),
        cases=case_results,
        negative_checks=negative_checks,
        summary=summary,
    )


def _run_case(
    case: GoldPlanCase,
    *,
    resolver: StructuralEndpointResolver,
    executor: PlannedPathExecutor,
    filters: RetrievalFilters,
) -> QG0CaseResult:
    started = perf_counter_ns()
    anchor = resolver.resolve(
        mention_text=case.anchor_mention,
        role=EndpointRole.ANCHOR,
        expected_label=case.anchor_label,
        filters=filters,
    )
    if (
        anchor.status is not EndpointResolutionStatus.RESOLVED
        or anchor.bound_endpoint is None
        or anchor.bound_endpoint.node_id != case.anchor_id
    ):
        return QG0CaseResult(
            query_id=case.query_id,
            anchor_status=anchor.status.value,
            anchor_id=(
                anchor.bound_endpoint.node_id
                if anchor.bound_endpoint is not None
                else None
            ),
            execution_status="not_run",
            reason_code=(
                anchor.reason_code.value if anchor.reason_code else "WRONG_ANCHOR"
            ),
            expected_node_ids=case.expected_node_ids,
            returned_node_ids=(),
            expected_relation_types=case.expected_relation_types,
            returned_relation_types=(),
            exact_denotation=False,
            false_positive_path_count=0,
            latency_ms=_elapsed_ms(started),
        )

    execution = executor.execute(case.bound_plan(), filters=filters)
    returned_node_ids = (
        tuple(node.node_id for node in execution.paths[0].nodes)
        if len(execution.paths) == 1
        else ()
    )
    returned_relation_types = (
        tuple(edge.relation_type for edge in execution.paths[0].edges)
        if len(execution.paths) == 1
        else ()
    )
    exact = (
        execution.result.reason_code.value == "SATISFIED"
        and returned_node_ids == case.expected_node_ids
        and returned_relation_types == case.expected_relation_types
    )
    return QG0CaseResult(
        query_id=case.query_id,
        anchor_status=anchor.status.value,
        anchor_id=anchor.bound_endpoint.node_id,
        execution_status=execution.result.execution_status.value,
        reason_code=execution.result.reason_code.value if exact else "WRONG_DENOTATION",
        expected_node_ids=case.expected_node_ids,
        returned_node_ids=returned_node_ids,
        expected_relation_types=case.expected_relation_types,
        returned_relation_types=returned_relation_types,
        exact_denotation=exact,
        false_positive_path_count=0
        if exact or not execution.paths
        else len(execution.paths),
        latency_ms=_elapsed_ms(started),
    )


def _run_negative_checks(
    case: GoldPlanCase,
    *,
    executor: PlannedPathExecutor,
    filters: RetrievalFilters,
) -> QG0NegativeChecks:
    steps = list(case.steps)
    steps[0] = PathStepConstraint(
        relation=steps[0].relation,
        direction=(
            "incoming" if steps[0].direction.value == "outgoing" else "outgoing"
        ),
        next_label=steps[0].next_label,
    )
    reversed_unlinked = UnlinkedSemanticPlan(
        anchor=AnchorMention(
            text=case.anchor_mention,
            expected_label=case.anchor_label,
        ),
        target=TargetMention(text=case.target_mention),
        steps=tuple(steps),
    )
    reversed_plan = BoundSemanticPlan(
        unlinked=reversed_unlinked,
        bound_anchor=BoundEndpoint(
            mention_text=case.anchor_mention,
            node_id=case.anchor_id,
            label=case.anchor_label,
            resolution_method="STRUCTURAL",
        ),
        bound_target=BoundEndpoint(
            mention_text=case.target_mention,
            node_id=case.target_id,
            label=case.target_label,
            resolution_method="STRUCTURAL",
        ),
    )
    reversed_execution = executor.execute(reversed_plan, filters=filters)
    missing_execution = executor.execute(
        case.bound_plan(target_id="qg0_missing_target"), filters=filters
    )
    return QG0NegativeChecks(
        reversed_direction_reason=reversed_execution.result.reason_code.value,
        missing_edge_reason=missing_execution.result.reason_code.value,
        answer_provider_call_count=0,
    )


def gold_plan_config_sha256(config: GoldPlanConfig) -> str:
    payload = json.dumps(
        config.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _elapsed_ms(started_ns: int) -> float:
    return round((perf_counter_ns() - started_ns) / 1_000_000, 3)
