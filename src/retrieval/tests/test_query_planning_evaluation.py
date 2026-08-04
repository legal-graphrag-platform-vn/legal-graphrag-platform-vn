from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.retrieval.eval.query_graph_qg0 import load_gold_plan_config
from src.retrieval.eval.query_planning import (
    QG1Metadata,
    QG1Observation,
    QG1ObservationCollector,
    QG1Profile,
    QG1Report,
    QG1TargetCandidateDiagnostic,
    QG1TargetDiagnostic,
    RuleBasedPlannerBaseline,
    evaluate_qg1,
    load_qg1_thresholds,
    write_qg1_artifacts,
)
from src.retrieval.planning.models import (
    AnchorMention,
    BoundEndpoint,
    PathStepConstraint,
    TargetMention,
    UnlinkedSemanticPlan,
)
from src.retrieval.execution_contract import PlanReasonCode
from src.retrieval.planning.linker import EndpointResolutionStatus


GOLD_PATH = Path("configs/evaluation/query_graph_gold_plans.json")
THRESHOLD_PATH = Path("configs/evaluation/query_graph_generation_thresholds.json")


def test_thresholds_are_preregistered_for_development_scope() -> None:
    thresholds = load_qg1_thresholds(THRESHOLD_PATH)

    assert thresholds.evaluation_scope == "pilot_development"
    assert thresholds.claim_label == "development_case_study"
    assert thresholds.minimum_case_count == 3
    assert set(thresholds.required_profiles) == set(QG1Profile)
    assert thresholds.llm_acceptance.answer_provider_calls_after_plan_failure == 0


def test_rule_based_baseline_emits_valid_plans_without_canonical_ids() -> None:
    gold = load_gold_plan_config(GOLD_PATH)
    baseline = RuleBasedPlannerBaseline()

    plans = tuple(baseline.plan(case.query) for case in gold.cases)

    assert all(plan is not None for plan in plans)
    assert all(
        tuple(step.relation.value for step in plan.steps)
        == case.expected_relation_types
        for plan, case in zip(plans, gold.cases, strict=True)
        if plan is not None
    )
    assert all("ldn_2020" not in plan.model_dump_json() for plan in plans if plan)


def test_qg1_scores_each_stage_and_counts_wrong_but_valid_plan_as_wrong() -> None:
    gold = load_gold_plan_config(GOLD_PATH)
    observations = _perfect_observations()
    wrong = _wrong_but_valid_plan(gold.cases[0])
    observations = tuple(
        observation.model_copy(
            update={
                "predicted_plan": wrong,
            }
        )
        if observation.profile is QG1Profile.LLM_PLANNER
        and observation.query_id == gold.cases[0].query_id
        else observation
        for observation in observations
    )

    report = evaluate_qg1(
        gold,
        load_qg1_thresholds(THRESHOLD_PATH),
        observations,
        metadata=_metadata(),
    )

    llm = report.profile(QG1Profile.LLM_PLANNER)
    assert llm.plan_schema_valid_rate == 1.0
    assert llm.exact_plan_sequence_match_rate == pytest.approx(2 / 3)
    assert llm.anchor_binding_accuracy == 1.0
    assert llm.target_binding_accuracy == 1.0
    assert llm.exact_path_denotation_accuracy == 1.0
    assert llm.graph_path_hit_rate == 1.0
    assert llm.extra_path_rate == 0.0
    assert llm.planner_latency.p50_ms == 20.0
    assert llm.planner_latency.p95_ms == 30.0


def test_qg1_rejects_missing_profile_case_observation() -> None:
    gold = load_gold_plan_config(GOLD_PATH)
    observations = _perfect_observations()[:-1]

    with pytest.raises(ValueError, match="exactly one observation"):
        evaluate_qg1(
            gold,
            load_qg1_thresholds(THRESHOLD_PATH),
            observations,
            metadata=_metadata(),
        )


def test_target_diagnostic_preserves_ranking_without_execution_data() -> None:
    diagnostic = QG1TargetDiagnostic(
        mention_text="trình tự chào bán phần vốn góp",
        resolution_status="ambiguous",
        candidates=(
            QG1TargetCandidateDiagnostic(
                rank=1,
                node_id="ldn_2020_art46_cl1",
                label="Clause",
                score=0.0635,
                retrieval_sources=("vector", "fulltext"),
            ),
            QG1TargetCandidateDiagnostic(
                rank=2,
                node_id="ldn_2020_art52_cl1",
                label="Clause",
                score=0.0631,
                retrieval_sources=("vector",),
            ),
        ),
        gold_rank=2,
        top_score=0.0635,
        top_two_margin=0.0004,
    )

    payload = diagnostic.model_dump(mode="json")

    assert [item["node_id"] for item in payload["candidates"]] == [
        "ldn_2020_art46_cl1",
        "ldn_2020_art52_cl1",
    ]
    assert payload["gold_rank"] == 2
    assert "path" not in payload
    assert "raw_response" not in payload


def test_report_metadata_is_stable_and_gold_is_only_an_upper_bound() -> None:
    gold = load_gold_plan_config(GOLD_PATH)
    thresholds = load_qg1_thresholds(THRESHOLD_PATH)

    first = evaluate_qg1(
        gold, thresholds, _perfect_observations(), metadata=_metadata()
    )
    second = evaluate_qg1(
        gold, thresholds, _perfect_observations(), metadata=_metadata()
    )

    assert first.metadata == second.metadata
    assert first.metadata.dataset_sha256
    assert first.metadata.thresholds_sha256
    assert first.metadata.graph_snapshot_sha256 == "graph-snapshot-test"
    assert first.metadata.planner_model == "gemini-test"
    assert first.metadata.prompt_fingerprint == "prompt-test"
    assert first.profile(QG1Profile.GOLD_MANUAL_UPPER_BOUND).role == "upper_bound"
    assert first.claim_label == "development_case_study"
    assert first.official is False


def test_qg1_artifacts_round_trip_and_state_development_limitations(
    tmp_path: Path,
) -> None:
    observations = tuple(
        observation.model_copy(
            update={
                "target_diagnostic": QG1TargetDiagnostic(
                    mention_text="trình tự chào bán phần vốn góp",
                    resolution_status="unbound",
                    candidates=(
                        QG1TargetCandidateDiagnostic(
                            rank=1,
                            node_id="ldn_2020_art46_cl1",
                            label="Clause",
                            score=0.0625,
                            retrieval_sources=("vector",),
                        ),
                    ),
                    top_score=0.0625,
                )
            }
        )
        if observation.profile is QG1Profile.LLM_PLANNER
        and observation.query_id == "multi_hop_04"
        else observation
        for observation in _perfect_observations()
    )
    report = evaluate_qg1(
        load_gold_plan_config(GOLD_PATH),
        load_qg1_thresholds(THRESHOLD_PATH),
        observations,
        metadata=_metadata(),
    )
    json_path = tmp_path / "qg1.json"
    markdown_path = tmp_path / "qg1.md"

    write_qg1_artifacts(report, json_path=json_path, markdown_path=markdown_path)

    restored = QG1Report.model_validate_json(json_path.read_text(encoding="utf-8"))
    markdown = markdown_path.read_text(encoding="utf-8")
    assert restored == report
    assert "development case study" in markdown
    assert "không phải baseline cạnh tranh" in markdown
    assert "Không phải kết quả official" in markdown
    assert "trình tự chào bán phần vốn góp" in markdown
    assert "ldn_2020_art46_cl1" in markdown
    assert "raw_response" not in markdown
    assert not list(tmp_path.glob(".*.tmp"))


def test_observation_collector_runs_all_profiles_and_preserves_stage_outcomes() -> None:
    async def scenario() -> None:
        gold = load_gold_plan_config(GOLD_PATH)
        planner = _FakePlanner(gold)
        collector = QG1ObservationCollector(
            generic_runtime=_FakeGenericRuntime(gold),
            linker=_FakeLinker(gold),
            executor=_FakeExecutor(gold),
            llm_planner=planner,
            rule_based_planner=RuleBasedPlannerBaseline(),
        )

        observations = await collector.collect(gold)

        assert len(observations) == len(gold.cases) * len(QG1Profile)
        assert planner.calls == len(gold.cases)
        llm = [item for item in observations if item.profile is QG1Profile.LLM_PLANNER]
        gold_upper = [
            item
            for item in observations
            if item.profile is QG1Profile.GOLD_MANUAL_UPPER_BOUND
        ]
        rule = [
            item
            for item in observations
            if item.profile is QG1Profile.RULE_BASED_PLANNER
        ]
        assert all(item.reason_code == "SATISFIED" for item in llm)
        assert all(item.reason_code == "SATISFIED" for item in gold_upper)
        assert rule[0].bound_anchor_id == "ldn_2020_art38"
        assert rule[0].reason_code == "NO_PATH"

        report = evaluate_qg1(
            gold,
            load_qg1_thresholds(THRESHOLD_PATH),
            observations,
            metadata=_metadata(),
        )
        target_diagnostic = (
            report.profile(QG1Profile.LLM_PLANNER).cases[0].target_diagnostic
        )
        assert target_diagnostic is not None
        assert target_diagnostic.mention_text == gold.cases[0].target_mention
        assert target_diagnostic.gold_rank == 1
        assert target_diagnostic.top_score == 0.064
        assert target_diagnostic.top_two_margin is None

    import asyncio

    asyncio.run(scenario())


def _perfect_observations() -> tuple[QG1Observation, ...]:
    gold = load_gold_plan_config(GOLD_PATH)
    observations = []
    for profile in QG1Profile:
        for index, case in enumerate(gold.cases, start=1):
            has_planner = profile is not QG1Profile.GENERIC_RETRIEVAL
            observations.append(
                QG1Observation(
                    profile=profile,
                    query_id=case.query_id,
                    plan_schema_valid=True if has_planner else None,
                    predicted_plan=case.unlinked_plan() if has_planner else None,
                    bound_anchor_id=case.anchor_id if has_planner else None,
                    bound_target_id=case.target_id if has_planner else None,
                    reason_code="SATISFIED",
                    returned_paths=(case.expected_node_ids,),
                    answer_provider_calls_after_plan_failure=0,
                    planner_latency_ms=float(index * 10) if has_planner else None,
                    total_retrieval_latency_ms=float(index * 20),
                )
            )
    return tuple(observations)


def _wrong_but_valid_plan(case) -> UnlinkedSemanticPlan:
    return UnlinkedSemanticPlan(
        anchor=AnchorMention(
            text=case.anchor_mention,
            expected_label=case.anchor_label,
        ),
        target=TargetMention(text=case.target_mention),
        steps=(
            PathStepConstraint(
                relation="CONTAINS",
                direction="incoming",
                next_label="Article",
            ),
            PathStepConstraint(
                relation="CONTAINS",
                direction="outgoing",
                next_label="Clause",
            ),
        ),
    )


def _metadata() -> QG1Metadata:
    return QG1Metadata(
        graph_snapshot_sha256="graph-snapshot-test",
        planner_provider="gemini",
        planner_model="gemini-test",
        prompt_fingerprint="prompt-test",
    )


class _FakePlanner:
    provider_name = "fake"
    model_name = "fake-model"

    def __init__(self, gold) -> None:
        self._by_query = {case.query: case for case in gold.cases}
        self.calls = 0

    async def plan(self, query: str) -> UnlinkedSemanticPlan:
        self.calls += 1
        return self._by_query[query].unlinked_plan()


class _FakeGenericRuntime:
    def __init__(self, gold) -> None:
        self._by_query = {case.query: case for case in gold.cases}

    def retrieve(self, request):
        case = self._by_query[request.query]
        return SimpleNamespace(graph_paths=(_fake_path(case.expected_node_ids),))


class _FakeLinker:
    def __init__(self, gold) -> None:
        self._cases = gold.cases

    def resolve(self, *, mention_text, role, expected_label, filters):
        if role.value == "anchor":
            node_id = _anchor_id(mention_text, self._cases)
        else:
            node_id = _target_id(mention_text, self._cases)
        return SimpleNamespace(
            status=EndpointResolutionStatus.RESOLVED,
            mention_text=mention_text,
            bound_endpoint=BoundEndpoint(
                mention_text=mention_text,
                node_id=node_id,
                label=expected_label,
                resolution_method="STRUCTURAL",
            ),
            candidates=(
                SimpleNamespace(
                    node_id=node_id,
                    label=expected_label,
                    score=0.064,
                    retrieval_sources=("vector",),
                ),
            ),
            reason_code=None,
        )


class _FakeExecutor:
    def __init__(self, gold) -> None:
        self._cases = gold.cases

    def execute(self, plan, *, filters):
        case = next(
            case for case in self._cases if case.target_id == plan.bound_target.node_id
        )
        exact = (
            plan.bound_anchor.node_id == case.anchor_id
            and tuple(step.relation.value for step in plan.unlinked.steps)
            == case.expected_relation_types
        )
        return SimpleNamespace(
            result=SimpleNamespace(
                reason_code=(
                    PlanReasonCode.SATISFIED if exact else PlanReasonCode.NO_PATH
                )
            ),
            paths=(_fake_path(case.expected_node_ids),) if exact else (),
        )


def _fake_path(node_ids):
    return SimpleNamespace(
        nodes=tuple(SimpleNamespace(node_id=node_id) for node_id in node_ids)
    )


def _anchor_id(mention_text: str, cases) -> str:
    for case in cases:
        if mention_text == case.anchor_mention:
            return case.anchor_id
    if mention_text.casefold() == "điều 38":
        return "ldn_2020_art38"
    raise AssertionError(f"Unexpected anchor mention: {mention_text}")


def _target_id(mention_text: str, cases) -> str:
    for case in cases:
        if mention_text == case.target_mention:
            return case.target_id
    normalized = mention_text.casefold()
    if "tên gây nhầm lẫn" in normalized:
        return "ldn_2020_art41_cl2"
    if "trình tự chào bán" in normalized:
        return "ldn_2020_art52_cl1"
    raise AssertionError(f"Unexpected target mention: {mention_text}")
