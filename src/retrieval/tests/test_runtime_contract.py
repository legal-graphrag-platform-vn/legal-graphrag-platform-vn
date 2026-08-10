import pytest
from datetime import date

from src.retrieval.config import RetrievalConfig
from src.retrieval.context.context_builder import ContextBuilder
from src.retrieval.context.temporal_filter import TemporalFilter
from src.retrieval.errors import (
    CanonicalReferenceUnavailableError,
    RetrievalCapabilityError,
    RetrievalOutputError,
)
from src.retrieval.evidence.verifier import EvidenceVerifier
from src.retrieval.fusion.reciprocal_rank_fusion import ReciprocalRankFusion
from src.retrieval.models import (
    CanonicalAnchorHydration,
    GraphEdge,
    GraphExpansion,
    GraphNodeRef,
    GraphPath,
    GraphReasoningRequirement,
    IntentType,
    RetrievalRequest,
    RetrievedUnit,
)
from src.retrieval.path_identity import build_topology_path_fingerprint
from src.retrieval.planning.executor import PlannedPathExecution
from src.retrieval.planning.models import (
    AnchorMention,
    BoundEndpoint,
    BoundSemanticPlan,
    PathStepConstraint,
    PlanExecutionResult,
    TargetMention,
    UnlinkedSemanticPlan,
)
from src.retrieval.retriever.hybrid import SeedChannelExecutor
from src.retrieval.routing.router import IntentRouter
from src.retrieval.runtime.runtime import RetrievalRuntime
from src.retrieval.resolved_reference import (
    ReferenceSource,
    RelationGoal,
    ResolutionMethod,
    ResolvedReference,
    RetrievalExecutionContext,
)


class EmptyChannel:
    def retrieve(self, query, *, filters, top_k):
        return []


class EmptyGraph:
    def __init__(self) -> None:
        self.calls = 0

    def expand(self, entry_ids, intent, *, filters, relation_goal=None):
        self.calls += 1
        return GraphExpansion()


class GenericGraph(EmptyGraph):
    def expand(self, entry_ids, intent, *, filters, relation_goal=None):
        self.calls += 1
        return GraphExpansion(
            paths=[
                GraphPath(
                    nodes=(
                        GraphNodeRef(node_id="generic-a", labels=("Clause",)),
                        GraphNodeRef(node_id="generic-b", labels=("Clause",)),
                    ),
                    edges=(
                        GraphEdge(
                            relation_id="generic-edge",
                            relation_type="REFERS_TO",
                            source_id="generic-a",
                            target_id="generic-b",
                        ),
                    ),
                    path_description="generic-a -> generic-b",
                )
            ]
        )


def _canonical_unit(unit_id: str, *, number: str) -> RetrievedUnit:
    return RetrievedUnit(
        id=unit_id,
        label="Clause" if "_cl" in unit_id else "Article",
        content_raw=f"Nội dung {unit_id}",
        document_id="ldn_2020",
        document_number="59/2020/QH14",
        article_id=(unit_id if "_cl" not in unit_id else "ldn_2020_art4"),
        clause_id=(unit_id if "_cl" in unit_id else None),
        article_number=("4" if "_cl" in unit_id else number),
        clause_number=(number if "_cl" in unit_id else None),
        citation_label=f"Đơn vị {number}",
        retrieval_sources=["graph"],
    )


class CanonicalRelationGraph:
    def __init__(self, *, include_edge: bool = True) -> None:
        self.include_edge = include_edge
        self.hydration_calls: list[list[str]] = []
        self.expansion_calls: list[tuple[list[str], object]] = []
        self.anchor = _canonical_unit("ldn_2020_art4_cl11", number="11")
        self.target = _canonical_unit("ldn_2020_art88", number="88")

    def hydrate_anchors(self, anchor_ids, *, filters):
        self.hydration_calls.append(list(anchor_ids))
        if self.anchor.id not in anchor_ids:
            return CanonicalAnchorHydration()
        return CanonicalAnchorHydration(
            matched_anchor_ids=(self.anchor.id,), units=[self.anchor]
        )

    def expand(self, entry_ids, intent, *, filters, relation_goal=None):
        self.expansion_calls.append((list(entry_ids), relation_goal))
        if not self.include_edge:
            return GraphExpansion()
        return GraphExpansion(
            units=[self.target],
            paths=[
                GraphPath(
                    nodes=(
                        GraphNodeRef(
                            node_id=self.anchor.id,
                            labels=("Clause",),
                            citable_unit_id=self.anchor.id,
                        ),
                        GraphNodeRef(
                            node_id=self.target.id,
                            labels=("Article",),
                            citable_unit_id=self.target.id,
                        ),
                    ),
                    edges=(
                        GraphEdge(
                            relation_id="ref-1",
                            relation_type="REFERS_TO",
                            source_id=self.anchor.id,
                            target_id=self.target.id,
                        ),
                    ),
                    path_description="Khoản 11 Điều 4 -> Điều 88",
                )
            ],
        )


def _reference_context() -> RetrievalExecutionContext:
    return RetrievalExecutionContext(
        resolved_references=(
            ResolvedReference(
                mention="Khoản 11 Điều 4 Luật Doanh nghiệp 2020",
                node_id="ldn_2020_art4_cl11",
                node_type="Clause",
                label="Khoản 11 Điều 4",
                document_id="ldn_2020",
                resolution_method=ResolutionMethod.EXACT_STRUCTURAL_LOOKUP,
                source=ReferenceSource.CURRENT_MESSAGE,
            ),
        ),
        relation_goal=RelationGoal.REFERS_TO,
    )


def test_anchor_node_ids_are_derived_with_stable_deduplication() -> None:
    reference = _reference_context().resolved_references[0]
    context = RetrievalExecutionContext(
        resolved_references=(
            reference,
            reference.model_copy(update={"mention": "quy định này"}),
        )
    )

    assert context.anchor_node_ids == ("ldn_2020_art4_cl11",)


class CapabilityInspector:
    def __init__(self, **overrides) -> None:
        self._values = overrides

    def inspect_capabilities(self, filters):
        return self._values

    def inspect_dependencies(self):
        return {}


class FixedClock:
    def today(self):
        return date(2026, 7, 13)


def _runtime(
    capabilities: CapabilityInspector,
    graph: EmptyGraph,
    *,
    planned_executor=None,
) -> RetrievalRuntime:
    channel = EmptyChannel()
    return RetrievalRuntime(
        router=IntentRouter(RetrievalConfig(), clock=FixedClock()),
        seed_executor=SeedChannelExecutor(vector=channel, fulltext=channel),
        graph_retriever=graph,
        capability_inspector=capabilities,
        fusion=ReciprocalRankFusion(),
        temporal_filter=TemporalFilter(),
        context_builder=ContextBuilder(EvidenceVerifier()),
        planned_executor=planned_executor,
    )


def test_empty_supported_result_is_not_capability_failure() -> None:
    graph = EmptyGraph()
    context = _runtime(CapabilityInspector(), graph).retrieve("quy định")
    assert context.capability_status == "no_results"
    assert context.retrieval_mode == "no_results"
    assert graph.calls == 1


def test_unsupported_hierarchy_raises_typed_capability_error() -> None:
    runtime = _runtime(
        CapabilityInspector(guides_relations_available=False), EmptyGraph()
    )
    with pytest.raises(RetrievalCapabilityError) as raised:
        runtime.retrieve(
            RetrievalRequest(
                query="Văn bản hướng dẫn",
                force_intent=IntentType.HIERARCHY,
            )
        )
    assert raised.value.required_capability == "guides_relations"


class PlannedExecutorSpy:
    def __init__(self, execution: PlannedPathExecution) -> None:
        self.execution = execution
        self.calls = 0

    def execute(self, plan, *, filters):
        self.calls += 1
        return self.execution


def _bound_plan() -> BoundSemanticPlan:
    unlinked = UnlinkedSemanticPlan(
        anchor=AnchorMention(text="Khoản 3 Điều 145", expected_label="Clause"),
        target=TargetMention(text="Khoản 1 Điều 145"),
        steps=(
            PathStepConstraint(
                relation="REFERS_TO", direction="outgoing", next_label="Clause"
            ),
            PathStepConstraint(
                relation="REFERS_TO", direction="outgoing", next_label="Clause"
            ),
        ),
    )
    return BoundSemanticPlan(
        unlinked=unlinked,
        bound_anchor=BoundEndpoint(
            mention_text=unlinked.anchor.text,
            node_id="anchor",
            label="Clause",
            resolution_method="STRUCTURAL",
        ),
        bound_target=BoundEndpoint(
            mention_text=unlinked.target.text,
            node_id="target",
            label="Clause",
            resolution_method="STRUCTURAL",
        ),
    )


def _exact_path() -> GraphPath:
    return GraphPath(
        nodes=(
            GraphNodeRef(
                node_id="anchor", labels=("Clause",), citable_unit_id="anchor"
            ),
            GraphNodeRef(
                node_id="middle", labels=("Clause",), citable_unit_id="middle"
            ),
            GraphNodeRef(
                node_id="target", labels=("Clause",), citable_unit_id="target"
            ),
        ),
        edges=(
            GraphEdge(
                relation_id="edge-1",
                relation_type="REFERS_TO",
                source_id="anchor",
                target_id="middle",
            ),
            GraphEdge(
                relation_id="edge-2",
                relation_type="REFERS_TO",
                source_id="middle",
                target_id="target",
            ),
        ),
        path_description="anchor -> middle -> target",
    )


def _planned_execution(*, satisfied: bool) -> PlannedPathExecution:
    plan = _bound_plan()
    if not satisfied:
        return PlannedPathExecution(
            result=PlanExecutionResult(
                plan_fingerprint="plan-test",
                satisfied_path_fingerprints=(),
                bound_anchor_id=plan.bound_anchor.node_id,
                bound_target_id=plan.bound_target.node_id,
                execution_status="failed",
                reason_code="NO_PATH",
            )
        )
    path = _exact_path()
    fingerprint = build_topology_path_fingerprint(path)
    return PlannedPathExecution(
        result=PlanExecutionResult(
            plan_fingerprint="plan-test",
            satisfied_path_fingerprints=(fingerprint,),
            bound_anchor_id=plan.bound_anchor.node_id,
            bound_target_id=plan.bound_target.node_id,
            execution_status="satisfied",
            reason_code="SATISFIED",
            derived_reasoning_requirement=GraphReasoningRequirement(minimum_edges=2),
        ),
        paths=(path,),
        path_fingerprints=(fingerprint,),
        citable_unit_ids=("anchor", "middle", "target"),
    )


def test_prepare_is_pure_and_execute_preserves_non_multi_hop_contract() -> None:
    capabilities = CapabilityInspector()
    graph = EmptyGraph()
    runtime = _runtime(capabilities, graph)

    prepared = runtime.prepare(RetrievalRequest(query="quy định"))

    assert graph.calls == 0
    context = runtime.execute(prepared)
    assert context.contract_version == "retrieval-runtime-v2"
    assert context.plan_execution is None
    assert context.reasoning_requirement is None
    assert graph.calls == 1


def test_exact_anchor_outside_seed_top_k_still_starts_one_graph_expansion() -> None:
    graph = CanonicalRelationGraph()
    context = _runtime(CapabilityInspector(), graph).retrieve(
        "Khoản 11 Điều 4 dẫn chiếu đến điều nào?",
        execution_context=_reference_context(),
    )

    assert graph.hydration_calls == [["ldn_2020_art4_cl11"]]
    assert graph.expansion_calls == [
        (["ldn_2020_art4_cl11"], RelationGoal.REFERS_TO)
    ]
    assert context.intent is IntentType.FACTUAL
    assert [unit.id for unit in context.retrieved_units[:2]] == [
        "ldn_2020_art4_cl11",
        "ldn_2020_art88",
    ]
    assert context.resolved_references == _reference_context().resolved_references
    assert context.relation_goal is RelationGoal.REFERS_TO


def test_relation_goal_with_no_edge_does_not_fuzzy_fallback() -> None:
    graph = CanonicalRelationGraph(include_edge=False)
    context = _runtime(CapabilityInspector(), graph).retrieve(
        "Khoản 11 Điều 4 dẫn chiếu đến điều nào?",
        execution_context=_reference_context(),
    )

    assert len(graph.expansion_calls) == 1
    assert context.graph_paths == []
    assert [unit.id for unit in context.retrieved_units] == [
        "ldn_2020_art4_cl11"
    ]


def test_unavailable_exact_anchor_fails_with_typed_error() -> None:
    graph = CanonicalRelationGraph()
    graph.anchor = _canonical_unit("another_anchor", number="1")

    with pytest.raises(CanonicalReferenceUnavailableError):
        _runtime(CapabilityInspector(), graph).retrieve(
            "Khoản 11 Điều 4 dẫn chiếu đến điều nào?",
            execution_context=_reference_context(),
        )

    assert graph.expansion_calls == []


def test_multi_hop_without_bound_plan_remains_requirement_unresolved() -> None:
    context = _runtime(
        CapabilityInspector(semantic_multi_hop_graph_available=True), EmptyGraph()
    ).retrieve(
        RetrievalRequest(query="dẫn chiếu qua nhiều điều", force_intent="multi_hop")
    )

    assert context.intent is IntentType.MULTI_HOP
    assert context.plan_execution is None
    assert context.reasoning_requirement is None
    assert context.metrics["planned_execution_count"] == 0
    assert context.metrics["planned_execution_reason_code"] == "NOT_PROVIDED"


def test_failed_plan_executes_once_and_never_derives_reasoning_requirement() -> None:
    spy = PlannedExecutorSpy(_planned_execution(satisfied=False))
    runtime = _runtime(
        CapabilityInspector(semantic_multi_hop_graph_available=True),
        EmptyGraph(),
        planned_executor=spy,
    )
    prepared = runtime.prepare(
        RetrievalRequest(query="dẫn chiếu qua nhiều điều", force_intent="multi_hop")
    )

    context = runtime.execute(prepared, bound_plan=_bound_plan())

    assert spy.calls == 1
    assert context.plan_execution is not None
    assert context.plan_execution.reason_code.value == "NO_PATH"
    assert context.reasoning_requirement is None
    assert context.metrics["planned_execution_count"] == 1
    assert context.metrics["planned_execution_reason_code"] == "NO_PATH"


def test_satisfied_plan_path_is_in_context_and_only_it_is_authoritative() -> None:
    execution = _planned_execution(satisfied=True)
    spy = PlannedExecutorSpy(execution)
    runtime = _runtime(
        CapabilityInspector(semantic_multi_hop_graph_available=True),
        GenericGraph(),
        planned_executor=spy,
    )
    prepared = runtime.prepare(
        RetrievalRequest(query="dẫn chiếu qua nhiều điều", force_intent="multi_hop")
    )

    context = runtime.execute(prepared, bound_plan=_bound_plan())

    assert spy.calls == 1
    assert context.plan_execution == execution.result
    assert (
        context.reasoning_requirement == execution.result.derived_reasoning_requirement
    )
    fingerprints = {
        build_topology_path_fingerprint(path) for path in context.graph_paths
    }
    assert set(context.plan_execution.satisfied_path_fingerprints) <= fingerprints
    generic_fingerprint = build_topology_path_fingerprint(
        next(
            path for path in context.graph_paths if path.nodes[0].node_id == "generic-a"
        )
    )
    assert generic_fingerprint not in context.plan_execution.satisfied_path_fingerprints
    assert context.metrics["planned_execution_reason_code"] == "SATISFIED"


def test_satisfied_result_with_missing_context_path_is_rejected() -> None:
    execution = _planned_execution(satisfied=True).model_copy(update={"paths": ()})
    runtime = _runtime(
        CapabilityInspector(semantic_multi_hop_graph_available=True),
        EmptyGraph(),
        planned_executor=PlannedExecutorSpy(execution),
    )
    prepared = runtime.prepare(
        RetrievalRequest(query="dẫn chiếu qua nhiều điều", force_intent="multi_hop")
    )

    with pytest.raises(RetrievalOutputError, match="fingerprints"):
        runtime.execute(prepared, bound_plan=_bound_plan())
