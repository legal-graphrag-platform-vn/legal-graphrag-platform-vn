"""Deterministic QG-1 scoring for query-planning profile observations."""

from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
from enum import Enum
from pathlib import Path
from time import perf_counter_ns
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.retrieval.eval.query_graph_qg0 import (
    GoldPlanCase,
    GoldPlanConfig,
    gold_plan_config_sha256,
)
from src.retrieval.models import IntentType, RetrievalFilters, RetrievalRequest
from src.retrieval.planning.errors import (
    QueryPlannerDependencyError,
    QueryPlannerInvalidPlanError,
    QueryPlannerTimeoutError,
)
from src.retrieval.planning.linker import EndpointResolutionStatus, EndpointRole
from src.retrieval.planning.models import (
    AnchorMention,
    BoundSemanticPlan,
    PathStepConstraint,
    TargetMention,
    UnlinkedSemanticPlan,
)
from src.retrieval.planning.ports import QueryPlannerPort


class _Contract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class QG1Profile(str, Enum):
    GENERIC_RETRIEVAL = "generic_retrieval"
    RULE_BASED_PLANNER = "rule_based_planner"
    GOLD_MANUAL_UPPER_BOUND = "gold_manual_upper_bound"
    LLM_PLANNER = "llm_planner"


class RuleBasedPlannerBaseline:
    """Small deterministic comparison baseline for the reviewed linear shapes."""

    _clause_article = re.compile(
        r"\bKhoản\s+(?P<clause>\d+)\s+Điều\s+(?P<article>\d+)\b",
        re.IGNORECASE,
    )
    _article = re.compile(r"\bĐiều\s+(?P<article>\d+)\b", re.IGNORECASE)
    _target_question = re.compile(r"\bkhoản nào\b(?P<tail>[^?]*)", re.IGNORECASE)

    def plan(self, query: str) -> UnlinkedSemanticPlan | None:
        normalized = " ".join(query.split())
        anchor_match = self._clause_article.search(normalized)
        if anchor_match is not None:
            article_number = anchor_match.group("article")
            anchor = AnchorMention(text=anchor_match.group(0), expected_label="Clause")
        else:
            article_match = self._article.search(normalized)
            if article_match is None:
                return None
            article_number = article_match.group("article")
            anchor = AnchorMention(
                text=article_match.group(0), expected_label="Article"
            )

        if "lần theo các dẫn chiếu" in normalized.casefold():
            target = TargetMention(text=f"Khoản 1 Điều {article_number}")
            steps = (
                PathStepConstraint(
                    relation="REFERS_TO",
                    direction="outgoing",
                    next_label="Clause",
                ),
                PathStepConstraint(
                    relation="REFERS_TO",
                    direction="outgoing",
                    next_label="Clause",
                ),
            )
        else:
            target_match = self._target_question.search(normalized)
            if target_match is None:
                return None
            target_text = " ".join(target_match.group(0).split()).rstrip(" ?")
            target = TargetMention(text=target_text)
            steps = (
                PathStepConstraint(
                    relation="REFERS_TO",
                    direction="outgoing",
                    next_label="Article",
                ),
                PathStepConstraint(
                    relation="CONTAINS",
                    direction="outgoing",
                    next_label="Clause",
                ),
            )
        return UnlinkedSemanticPlan(anchor=anchor, target=target, steps=steps)


class QG1AcceptanceThresholds(_Contract):
    plan_schema_valid_rate: float = Field(ge=0, le=1)
    exact_plan_sequence_match_rate: float = Field(ge=0, le=1)
    anchor_binding_accuracy: float = Field(ge=0, le=1)
    target_binding_accuracy: float = Field(ge=0, le=1)
    exact_path_denotation_accuracy: float = Field(ge=0, le=1)
    graph_path_hit_rate: float = Field(ge=0, le=1)
    maximum_extra_path_rate: float = Field(ge=0, le=1)
    answer_provider_calls_after_plan_failure: int = Field(ge=0)


class QG1ThresholdConfig(_Contract):
    schema_version: Literal["query-graph-qg1-thresholds-v1"]
    evaluation_scope: Literal["pilot_development"]
    claim_label: Literal["development_case_study"]
    preregistered_at: str = Field(min_length=1)
    minimum_case_count: int = Field(ge=1)
    required_profiles: tuple[QG1Profile, ...]
    llm_acceptance: QG1AcceptanceThresholds

    @model_validator(mode="after")
    def validate_profiles(self) -> Self:
        if len(self.required_profiles) != len(set(self.required_profiles)):
            raise ValueError("QG-1 required profiles must be unique")
        if set(self.required_profiles) != set(QG1Profile):
            raise ValueError("QG-1 thresholds must preregister all four profiles")
        return self


class QG1Metadata(_Contract):
    graph_snapshot_sha256: str = Field(min_length=1)
    planner_provider: str = Field(min_length=1)
    planner_model: str = Field(min_length=1)
    prompt_fingerprint: str = Field(min_length=1)


class QG1ReportMetadata(QG1Metadata):
    dataset_sha256: str = Field(min_length=64, max_length=64)
    thresholds_sha256: str = Field(min_length=64, max_length=64)


class QG1TargetCandidateDiagnostic(_Contract):
    rank: int = Field(ge=1)
    node_id: str = Field(min_length=1)
    label: Literal["Article", "Clause", "Point"]
    score: float | None = Field(default=None, ge=0)
    retrieval_sources: tuple[Literal["vector", "fulltext"], ...] = ()


class QG1TargetDiagnostic(_Contract):
    mention_text: str = Field(min_length=1)
    resolution_status: EndpointResolutionStatus
    candidates: tuple[QG1TargetCandidateDiagnostic, ...] = ()
    gold_rank: int | None = Field(default=None, ge=1)
    top_score: float | None = Field(default=None, ge=0)
    top_two_margin: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_candidate_order(self) -> Self:
        ranks = tuple(candidate.rank for candidate in self.candidates)
        if ranks != tuple(range(1, len(self.candidates) + 1)):
            raise ValueError("Target diagnostic candidate ranks must be contiguous")
        return self


class QG1Observation(_Contract):
    profile: QG1Profile
    query_id: str = Field(min_length=1)
    plan_schema_valid: bool | None = None
    predicted_plan: UnlinkedSemanticPlan | None = None
    bound_anchor_id: str | None = None
    bound_target_id: str | None = None
    target_diagnostic: QG1TargetDiagnostic | None = None
    reason_code: str = Field(min_length=1)
    returned_paths: tuple[tuple[str, ...], ...] = ()
    answer_provider_calls_after_plan_failure: int = Field(default=0, ge=0)
    planner_latency_ms: float | None = Field(default=None, ge=0)
    total_retrieval_latency_ms: float = Field(ge=0)

    @model_validator(mode="after")
    def validate_profile_shape(self) -> Self:
        if self.profile is QG1Profile.GENERIC_RETRIEVAL:
            if self.plan_schema_valid is not None or self.predicted_plan is not None:
                raise ValueError("Generic retrieval must not carry a planner output")
            if self.planner_latency_ms is not None:
                raise ValueError("Generic retrieval must not carry planner latency")
        elif self.plan_schema_valid and self.predicted_plan is None:
            raise ValueError("Schema-valid planner output requires a parsed plan")
        elif self.predicted_plan is not None and self.plan_schema_valid is not True:
            raise ValueError("A parsed plan must be marked schema-valid")
        return self


class QG1ObservationCollector:
    """Collect four comparable QG-1 profiles without calling answer generation."""

    def __init__(
        self,
        *,
        generic_runtime,
        linker,
        executor,
        llm_planner: QueryPlannerPort,
        rule_based_planner: RuleBasedPlannerBaseline,
    ) -> None:
        self._generic_runtime = generic_runtime
        self._linker = linker
        self._executor = executor
        self._llm_planner = llm_planner
        self._rule_based_planner = rule_based_planner

    async def collect(self, gold: GoldPlanConfig) -> tuple[QG1Observation, ...]:
        filters = RetrievalFilters(document_ids=list(gold.document_ids))
        observations: list[QG1Observation] = []
        for case in gold.cases:
            observations.append(await self._collect_generic(case, filters))
            observations.append(await self._collect_rule(case, filters))
            observations.append(await self._collect_gold(case, filters))
            observations.append(await self._collect_llm(case, filters))
        return tuple(observations)

    async def _collect_generic(
        self, case: GoldPlanCase, filters: RetrievalFilters
    ) -> QG1Observation:
        started = perf_counter_ns()
        context = self._generic_runtime.retrieve(
            RetrievalRequest(
                query=case.query,
                filters=filters,
                force_intent=IntentType.MULTI_HOP,
            ),
        )
        paths = _returned_node_paths(context.graph_paths)
        return QG1Observation(
            profile=QG1Profile.GENERIC_RETRIEVAL,
            query_id=case.query_id,
            reason_code="SATISFIED" if case.expected_node_ids in paths else "NO_PATH",
            returned_paths=paths,
            total_retrieval_latency_ms=_elapsed_ms(started),
        )

    async def _collect_rule(
        self, case: GoldPlanCase, filters: RetrievalFilters
    ) -> QG1Observation:
        started = perf_counter_ns()
        planner_started = perf_counter_ns()
        plan = self._rule_based_planner.plan(case.query)
        planner_latency = _elapsed_ms(planner_started)
        if plan is None:
            return _planner_failure_observation(
                profile=QG1Profile.RULE_BASED_PLANNER,
                case=case,
                reason_code="INVALID_PLAN",
                started=started,
                planner_latency_ms=planner_latency,
            )
        return await self._collect_planned(
            profile=QG1Profile.RULE_BASED_PLANNER,
            case=case,
            plan=plan,
            filters=filters,
            started=started,
            planner_latency_ms=planner_latency,
        )

    async def _collect_gold(
        self, case: GoldPlanCase, filters: RetrievalFilters
    ) -> QG1Observation:
        started = perf_counter_ns()
        execution = self._executor.execute(
            case.bound_plan(),
            filters=filters,
        )
        return QG1Observation(
            profile=QG1Profile.GOLD_MANUAL_UPPER_BOUND,
            query_id=case.query_id,
            plan_schema_valid=True,
            predicted_plan=case.unlinked_plan(),
            bound_anchor_id=case.anchor_id,
            bound_target_id=case.target_id,
            reason_code=execution.result.reason_code.value,
            returned_paths=_returned_node_paths(execution.paths),
            total_retrieval_latency_ms=_elapsed_ms(started),
        )

    async def _collect_llm(
        self, case: GoldPlanCase, filters: RetrievalFilters
    ) -> QG1Observation:
        started = perf_counter_ns()
        planner_started = perf_counter_ns()
        try:
            plan = await self._llm_planner.plan(case.query)
        except QueryPlannerInvalidPlanError:
            return _planner_failure_observation(
                profile=QG1Profile.LLM_PLANNER,
                case=case,
                reason_code="INVALID_PLAN",
                started=started,
                planner_latency_ms=_elapsed_ms(planner_started),
            )
        except QueryPlannerTimeoutError:
            return _planner_failure_observation(
                profile=QG1Profile.LLM_PLANNER,
                case=case,
                reason_code="PLANNER_TIMEOUT",
                started=started,
                planner_latency_ms=_elapsed_ms(planner_started),
            )
        except QueryPlannerDependencyError:
            return _planner_failure_observation(
                profile=QG1Profile.LLM_PLANNER,
                case=case,
                reason_code="PLANNER_UNAVAILABLE",
                started=started,
                planner_latency_ms=_elapsed_ms(planner_started),
            )
        return await self._collect_planned(
            profile=QG1Profile.LLM_PLANNER,
            case=case,
            plan=plan,
            filters=filters,
            started=started,
            planner_latency_ms=_elapsed_ms(planner_started),
        )

    async def _collect_planned(
        self,
        *,
        profile: QG1Profile,
        case: GoldPlanCase,
        plan: UnlinkedSemanticPlan,
        filters: RetrievalFilters,
        started: int,
        planner_latency_ms: float,
    ) -> QG1Observation:
        anchor, target, execution = self._link_and_execute(plan, filters)
        reason_code = (
            execution.result.reason_code.value
            if execution is not None
            else (anchor.reason_code or target.reason_code).value
        )
        return QG1Observation(
            profile=profile,
            query_id=case.query_id,
            plan_schema_valid=True,
            predicted_plan=plan,
            bound_anchor_id=(
                anchor.bound_endpoint.node_id
                if anchor.bound_endpoint is not None
                else None
            ),
            bound_target_id=(
                target.bound_endpoint.node_id
                if target.bound_endpoint is not None
                else None
            ),
            target_diagnostic=_target_diagnostic(target),
            reason_code=reason_code,
            returned_paths=(
                _returned_node_paths(execution.paths) if execution is not None else ()
            ),
            planner_latency_ms=planner_latency_ms,
            total_retrieval_latency_ms=_elapsed_ms(started),
        )

    def _link_and_execute(
        self,
        plan: UnlinkedSemanticPlan,
        filters: RetrievalFilters,
    ):
        anchor = self._linker.resolve(
            mention_text=plan.anchor.text,
            role=EndpointRole.ANCHOR,
            expected_label=(
                plan.anchor.expected_label.value
                if plan.anchor.expected_label is not None
                else None
            ),
            filters=filters,
        )
        target = self._linker.resolve(
            mention_text=plan.target.text,
            role=EndpointRole.TARGET,
            expected_label=plan.target_label,
            filters=filters,
        )
        if (
            anchor.status is not EndpointResolutionStatus.RESOLVED
            or target.status is not EndpointResolutionStatus.RESOLVED
            or anchor.bound_endpoint is None
            or target.bound_endpoint is None
        ):
            return anchor, target, None
        bound = BoundSemanticPlan(
            unlinked=plan,
            bound_anchor=anchor.bound_endpoint.model_copy(
                update={"mention_text": plan.anchor.text}
            ),
            bound_target=target.bound_endpoint.model_copy(
                update={"mention_text": plan.target.text}
            ),
        )
        return anchor, target, self._executor.execute(bound, filters=filters)


class LatencyDistribution(_Contract):
    sample_size: int = Field(ge=0)
    p50_ms: float | None = Field(default=None, ge=0)
    p95_ms: float | None = Field(default=None, ge=0)


class QG1CaseResult(_Contract):
    query_id: str
    plan_schema_valid: bool | None
    exact_plan_sequence_match: bool | None
    anchor_binding_correct: bool | None
    target_binding_correct: bool | None
    exact_path_denotation: bool
    graph_path_hit: bool
    extra_path_count: int
    returned_path_count: int
    reason_code: str
    answer_provider_calls_after_plan_failure: int
    target_diagnostic: QG1TargetDiagnostic | None = None


class QG1ProfileReport(_Contract):
    profile: QG1Profile
    role: Literal["reference", "baseline", "upper_bound", "candidate"]
    case_count: int
    plan_schema_valid_rate: float | None
    exact_plan_sequence_match_rate: float | None
    anchor_binding_accuracy: float | None
    target_binding_accuracy: float | None
    exact_path_denotation_accuracy: float
    extra_path_rate: float
    no_path_rate: float
    ambiguous_path_rate: float
    graph_path_hit_rate: float
    answer_provider_calls_after_plan_failure: int
    planner_latency: LatencyDistribution
    total_retrieval_latency: LatencyDistribution
    cases: tuple[QG1CaseResult, ...]


class QG1Report(_Contract):
    schema_version: Literal["query-graph-qg1-v1"] = "query-graph-qg1-v1"
    evaluation_scope: Literal["pilot_development"] = "pilot_development"
    claim_label: Literal["development_case_study"] = "development_case_study"
    official: Literal[False] = False
    threshold_status: Literal["passed", "failed"]
    metadata: QG1ReportMetadata
    profiles: tuple[QG1ProfileReport, ...]

    def profile(self, profile: QG1Profile) -> QG1ProfileReport:
        return next(item for item in self.profiles if item.profile is profile)


def load_qg1_thresholds(path: Path) -> QG1ThresholdConfig:
    return QG1ThresholdConfig.model_validate_json(path.read_text(encoding="utf-8"))


def evaluate_qg1(
    gold: GoldPlanConfig,
    thresholds: QG1ThresholdConfig,
    observations: tuple[QG1Observation, ...],
    *,
    metadata: QG1Metadata,
) -> QG1Report:
    if len(gold.cases) < thresholds.minimum_case_count:
        raise ValueError("QG-1 gold dataset is smaller than the preregistered minimum")
    indexed = _index_observations(gold, thresholds, observations)
    profiles = tuple(
        _score_profile(profile, gold.cases, indexed)
        for profile in thresholds.required_profiles
    )
    llm = next(item for item in profiles if item.profile is QG1Profile.LLM_PLANNER)
    return QG1Report(
        threshold_status=(
            "passed" if _passes_thresholds(llm, thresholds.llm_acceptance) else "failed"
        ),
        metadata=QG1ReportMetadata(
            **metadata.model_dump(),
            dataset_sha256=gold_plan_config_sha256(gold),
            thresholds_sha256=_canonical_sha256(thresholds),
        ),
        profiles=profiles,
    )


def write_qg1_artifacts(
    report: QG1Report,
    *,
    json_path: Path,
    markdown_path: Path,
) -> None:
    """Atomically persist the machine-readable and review-readable QG-1 report."""
    json_payload = json.dumps(
        report.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
    )
    _write_atomic(json_path, json_payload + "\n")
    _write_atomic(markdown_path, _render_markdown(report))


def _planner_failure_observation(
    *,
    profile: QG1Profile,
    case: GoldPlanCase,
    reason_code: str,
    started: int,
    planner_latency_ms: float,
) -> QG1Observation:
    return QG1Observation(
        profile=profile,
        query_id=case.query_id,
        plan_schema_valid=False,
        reason_code=reason_code,
        planner_latency_ms=planner_latency_ms,
        total_retrieval_latency_ms=_elapsed_ms(started),
    )


def _returned_node_paths(paths) -> tuple[tuple[str, ...], ...]:
    return tuple(tuple(node.node_id for node in path.nodes) for path in paths)


def _target_diagnostic(resolution) -> QG1TargetDiagnostic:
    candidates = tuple(
        QG1TargetCandidateDiagnostic(
            rank=rank,
            node_id=candidate.node_id,
            label=candidate.label,
            score=getattr(candidate, "score", None),
            retrieval_sources=getattr(candidate, "retrieval_sources", ()),
        )
        for rank, candidate in enumerate(resolution.candidates, start=1)
    )
    top_score = candidates[0].score if candidates else None
    top_two_margin = (
        top_score - candidates[1].score
        if len(candidates) > 1
        and top_score is not None
        and candidates[1].score is not None
        else None
    )
    return QG1TargetDiagnostic(
        mention_text=resolution.mention_text,
        resolution_status=resolution.status,
        candidates=candidates,
        top_score=top_score,
        top_two_margin=top_two_margin,
    )


def _elapsed_ms(started_ns: int) -> float:
    return round((perf_counter_ns() - started_ns) / 1_000_000, 3)


def _index_observations(
    gold: GoldPlanConfig,
    thresholds: QG1ThresholdConfig,
    observations: tuple[QG1Observation, ...],
) -> dict[tuple[QG1Profile, str], QG1Observation]:
    indexed = {(item.profile, item.query_id): item for item in observations}
    expected = {
        (profile, case.query_id)
        for profile in thresholds.required_profiles
        for case in gold.cases
    }
    if len(indexed) != len(observations) or set(indexed) != expected:
        raise ValueError("QG-1 requires exactly one observation per profile and case")
    return indexed


def _score_profile(
    profile: QG1Profile,
    cases: tuple[GoldPlanCase, ...],
    indexed: dict[tuple[QG1Profile, str], QG1Observation],
) -> QG1ProfileReport:
    observations = tuple(indexed[(profile, case.query_id)] for case in cases)
    case_results = tuple(
        _score_case(case, observation)
        for case, observation in zip(cases, observations, strict=True)
    )
    planner_applicable = profile is not QG1Profile.GENERIC_RETRIEVAL
    returned_path_count = sum(item.returned_path_count for item in case_results)
    extra_path_count = sum(item.extra_path_count for item in case_results)
    return QG1ProfileReport(
        profile=profile,
        role=_profile_role(profile),
        case_count=len(case_results),
        plan_schema_valid_rate=(
            _mean(bool(item.plan_schema_valid) for item in case_results)
            if planner_applicable
            else None
        ),
        exact_plan_sequence_match_rate=(
            _mean(bool(item.exact_plan_sequence_match) for item in case_results)
            if planner_applicable
            else None
        ),
        anchor_binding_accuracy=(
            _mean(bool(item.anchor_binding_correct) for item in case_results)
            if planner_applicable
            else None
        ),
        target_binding_accuracy=(
            _mean(bool(item.target_binding_correct) for item in case_results)
            if planner_applicable
            else None
        ),
        exact_path_denotation_accuracy=_mean(
            item.exact_path_denotation for item in case_results
        ),
        extra_path_rate=(
            extra_path_count / returned_path_count if returned_path_count else 0.0
        ),
        no_path_rate=_mean(item.reason_code == "NO_PATH" for item in case_results),
        ambiguous_path_rate=_mean(
            item.reason_code == "AMBIGUOUS_PATH" for item in case_results
        ),
        graph_path_hit_rate=_mean(item.graph_path_hit for item in case_results),
        answer_provider_calls_after_plan_failure=sum(
            item.answer_provider_calls_after_plan_failure
            for item in case_results
            if item.reason_code != "SATISFIED"
        ),
        planner_latency=_latency_distribution(
            [
                item.planner_latency_ms
                for item in observations
                if item.planner_latency_ms is not None
            ]
        ),
        total_retrieval_latency=_latency_distribution(
            [item.total_retrieval_latency_ms for item in observations]
        ),
        cases=case_results,
    )


def _score_case(case: GoldPlanCase, observation: QG1Observation) -> QG1CaseResult:
    expected = case.expected_node_ids
    extra_paths = tuple(path for path in observation.returned_paths if path != expected)
    planner_applicable = observation.profile is not QG1Profile.GENERIC_RETRIEVAL
    target_diagnostic = observation.target_diagnostic
    if target_diagnostic is not None:
        gold_rank = next(
            (
                candidate.rank
                for candidate in target_diagnostic.candidates
                if candidate.node_id == case.target_id
            ),
            None,
        )
        target_diagnostic = target_diagnostic.model_copy(
            update={"gold_rank": gold_rank}
        )
    return QG1CaseResult(
        query_id=case.query_id,
        plan_schema_valid=observation.plan_schema_valid,
        exact_plan_sequence_match=(
            _plan_sequence(observation.predicted_plan)
            == _plan_sequence(case.unlinked_plan())
            if planner_applicable and observation.predicted_plan is not None
            else False
            if planner_applicable
            else None
        ),
        anchor_binding_correct=(
            observation.bound_anchor_id == case.anchor_id
            if planner_applicable
            else None
        ),
        target_binding_correct=(
            observation.bound_target_id == case.target_id
            if planner_applicable
            else None
        ),
        exact_path_denotation=observation.returned_paths == (expected,),
        graph_path_hit=expected in observation.returned_paths,
        extra_path_count=len(extra_paths),
        returned_path_count=len(observation.returned_paths),
        reason_code=observation.reason_code,
        answer_provider_calls_after_plan_failure=(
            observation.answer_provider_calls_after_plan_failure
        ),
        target_diagnostic=target_diagnostic,
    )


def _plan_sequence(plan: UnlinkedSemanticPlan) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        (step.relation.value, step.direction.value, step.next_label.value)
        for step in plan.steps
    )


def _profile_role(
    profile: QG1Profile,
) -> Literal["reference", "baseline", "upper_bound", "candidate"]:
    return {
        QG1Profile.GENERIC_RETRIEVAL: "reference",
        QG1Profile.RULE_BASED_PLANNER: "baseline",
        QG1Profile.GOLD_MANUAL_UPPER_BOUND: "upper_bound",
        QG1Profile.LLM_PLANNER: "candidate",
    }[profile]


def _latency_distribution(values: list[float]) -> LatencyDistribution:
    if not values:
        return LatencyDistribution(sample_size=0)
    ordered = sorted(values)
    p95_index = max(0, math.ceil(len(ordered) * 0.95) - 1)
    return LatencyDistribution(
        sample_size=len(ordered),
        p50_ms=statistics.median(ordered),
        p95_ms=ordered[p95_index],
    )


def _passes_thresholds(
    report: QG1ProfileReport,
    thresholds: QG1AcceptanceThresholds,
) -> bool:
    return all(
        (
            (report.plan_schema_valid_rate or 0) >= thresholds.plan_schema_valid_rate,
            (report.exact_plan_sequence_match_rate or 0)
            >= thresholds.exact_plan_sequence_match_rate,
            (report.anchor_binding_accuracy or 0) >= thresholds.anchor_binding_accuracy,
            (report.target_binding_accuracy or 0) >= thresholds.target_binding_accuracy,
            report.exact_path_denotation_accuracy
            >= thresholds.exact_path_denotation_accuracy,
            report.graph_path_hit_rate >= thresholds.graph_path_hit_rate,
            report.extra_path_rate <= thresholds.maximum_extra_path_rate,
            report.answer_provider_calls_after_plan_failure
            <= thresholds.answer_provider_calls_after_plan_failure,
        )
    )


def _mean(values) -> float:
    materialized = tuple(values)
    return statistics.fmean(materialized) if materialized else 0.0


def _canonical_sha256(model: BaseModel) -> str:
    payload = json.dumps(
        model.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _write_atomic(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _render_markdown(report: QG1Report) -> str:
    lines = [
        "# QG-1 query planning evaluation",
        "",
        "> Phạm vi: development case study. Không phải kết quả official.",
        "",
        (
            "Gold manual planner chỉ là upper bound để cô lập executor; "
            "không phải baseline cạnh tranh."
        ),
        "",
        f"- Threshold status: `{report.threshold_status}`",
        f"- Dataset SHA-256: `{report.metadata.dataset_sha256}`",
        f"- Graph snapshot SHA-256: `{report.metadata.graph_snapshot_sha256}`",
        f"- Planner: `{report.metadata.planner_provider}:{report.metadata.planner_model}`",
        f"- Prompt fingerprint: `{report.metadata.prompt_fingerprint}`",
        "",
        "| Profile | Role | Schema valid | Exact plan | Anchor | Target | "
        "Exact path | Extra path | Graph hit |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for profile in report.profiles:
        lines.append(
            "| "
            + " | ".join(
                (
                    profile.profile.value,
                    profile.role,
                    _format_rate(profile.plan_schema_valid_rate),
                    _format_rate(profile.exact_plan_sequence_match_rate),
                    _format_rate(profile.anchor_binding_accuracy),
                    _format_rate(profile.target_binding_accuracy),
                    _format_rate(profile.exact_path_denotation_accuracy),
                    _format_rate(profile.extra_path_rate),
                    _format_rate(profile.graph_path_hit_rate),
                )
            )
            + " |"
        )
    llm_diagnostics = tuple(
        case
        for case in report.profile(QG1Profile.LLM_PLANNER).cases
        if case.target_diagnostic is not None
    )
    if llm_diagnostics:
        lines.extend(
            (
                "",
                "## LLM target-linker diagnostic",
                "",
                "| Query | Target mention | Status | Gold rank | Top score | "
                "Top-2 margin | Candidates |",
                "|---|---|---|---:|---:|---:|---|",
            )
        )
        for case in llm_diagnostics:
            diagnostic = case.target_diagnostic
            assert diagnostic is not None
            candidates = "; ".join(
                f"{candidate.rank}:{candidate.node_id}"
                f"({_format_optional(candidate.score)})"
                for candidate in diagnostic.candidates
            )
            lines.append(
                "| "
                + " | ".join(
                    (
                        case.query_id,
                        _escape_markdown_cell(diagnostic.mention_text),
                        diagnostic.resolution_status.value,
                        str(diagnostic.gold_rank or "n/a"),
                        _format_optional(diagnostic.top_score),
                        _format_optional(diagnostic.top_two_margin),
                        candidates or "n/a",
                    )
                )
                + " |"
            )
    lines.extend(
        (
            "",
            "Corpus hiện chỉ gồm các case đã review trong `ldn_2020`; không "
            "claim khả năng generalize hoặc leave-one-document-out.",
            "",
        )
    )
    return "\n".join(lines)


def _format_rate(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def _format_optional(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.6f}"


def _escape_markdown_cell(value: str) -> str:
    return " ".join(value.split()).replace("|", "\\|")
