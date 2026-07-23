from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from api.models import QueryRequest
from services.graphrag_retrieval_service import (
    GraphRAGRetrievalService,
    RetrievalQueryService,
)
from services.errors import (
    BackendPlanningOutputError,
    BackendPlanningTimeoutError,
    BackendPlanningUnavailableError,
)
from services.retrieval_runner import BoundedRetrievalRunner
from src.retrieval.errors import RetrievalCapabilityError
from src.retrieval.models import IntentType
from src.retrieval.planning.errors import (
    QueryPlannerDependencyError,
    QueryPlannerInvalidPlanError,
    QueryPlannerTimeoutError,
)
from src.retrieval.planning.models import (
    AnchorMention,
    PathStepConstraint,
    TargetMention,
    UnlinkedSemanticPlan,
)
from src.shared.retrieval_contract import RetrievalRequest
from tests.factories import retrieval_context


class FakeRuntime:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.requests: list[RetrievalRequest] = []

    def retrieve(self, request: RetrievalRequest):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return retrieval_context(no_results=request.query == "none")

    def close(self) -> None:
        return None


class FakePlanningRuntime:
    """Runtime that exposes prepare/execute for the planning orchestration path."""

    def __init__(self, intent: IntentType) -> None:
        self._prepared = SimpleNamespace(
            routing=SimpleNamespace(decision=SimpleNamespace(intent=intent))
        )
        self.prepare_calls = 0
        self.executed_plans: list[object] = []

    def prepare(self, request: RetrievalRequest):
        self.prepare_calls += 1
        return self._prepared

    def execute(self, prepared, *, plan=None):
        assert prepared is self._prepared
        self.executed_plans.append(plan)
        return retrieval_context()

    def retrieve(self, request: RetrievalRequest):
        raise AssertionError("planning path must not use retrieve")

    def close(self) -> None:
        return None


class FakePlanner:
    provider_name = "fake"
    model_name = "fake-model"

    def __init__(self, *, plan=None, error: Exception | None = None) -> None:
        self._plan = plan
        self._error = error
        self.calls = 0

    async def plan(self, query: str):
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._plan

    async def aclose(self) -> None:
        return None


class _PerQueryPlanner:
    provider_name = "fake"
    model_name = "fake-model"

    def __init__(self, plans: dict[str, UnlinkedSemanticPlan]) -> None:
        self._plans = plans

    async def plan(self, query: str) -> UnlinkedSemanticPlan:
        await asyncio.sleep(0)  # yield so requests genuinely interleave
        return self._plans[query]

    async def aclose(self) -> None:
        return None


def _unlinked_plan(
    target: str = "điều kiện của lần họp thứ nhất",
) -> UnlinkedSemanticPlan:
    return UnlinkedSemanticPlan(
        anchor=AnchorMention(text="Khoản 3 Điều 145", expected_label="Clause"),
        target=TargetMention(text=target),
        steps=(
            PathStepConstraint(
                relation="REFERS_TO", direction="outgoing", next_label="Clause"
            ),
            PathStepConstraint(
                relation="REFERS_TO", direction="outgoing", next_label="Clause"
            ),
        ),
    )


def _runner() -> BoundedRetrievalRunner:
    return BoundedRetrievalRunner(
        max_concurrency=1, timeout_seconds=1, shutdown_grace_seconds=1
    )


def test_multi_hop_plans_once_then_executes_with_plan() -> None:
    async def scenario() -> None:
        runtime = FakePlanningRuntime(IntentType.MULTI_HOP)
        plan = _unlinked_plan()
        planner = FakePlanner(plan=plan)
        runner = _runner()
        service = GraphRAGRetrievalService(
            runtime, runner, planner=planner, planning_enabled=True
        )
        try:
            await service.retrieve_context(RetrievalRequest(query="multi hop"))
        finally:
            await runner.aclose()
        assert planner.calls == 1
        assert runtime.prepare_calls == 1
        assert runtime.executed_plans == [plan]

    asyncio.run(scenario())


def test_non_multi_hop_skips_planner_and_executes_without_plan() -> None:
    async def scenario() -> None:
        runtime = FakePlanningRuntime(IntentType.FACTUAL)
        planner = FakePlanner(plan=_unlinked_plan())
        runner = _runner()
        service = GraphRAGRetrievalService(
            runtime, runner, planner=planner, planning_enabled=True
        )
        try:
            await service.retrieve_context(RetrievalRequest(query="factual"))
        finally:
            await runner.aclose()
        assert planner.calls == 0
        assert runtime.executed_plans == [None]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("planner_error", "backend_error"),
    [
        (QueryPlannerTimeoutError("slow-secret"), BackendPlanningTimeoutError),
        (
            QueryPlannerDependencyError("provider-secret"),
            BackendPlanningUnavailableError,
        ),
        (QueryPlannerInvalidPlanError("payload-secret"), BackendPlanningOutputError),
    ],
)
def test_planner_infra_failure_raises_typed_backend_error_without_execution(
    planner_error: Exception,
    backend_error: type[Exception],
) -> None:
    async def scenario() -> None:
        runtime = FakePlanningRuntime(IntentType.MULTI_HOP)
        planner = FakePlanner(error=planner_error)
        runner = _runner()
        service = GraphRAGRetrievalService(
            runtime, runner, planner=planner, planning_enabled=True
        )
        try:
            with pytest.raises(backend_error) as captured:
                await service.retrieve_context(RetrievalRequest(query="multi hop"))
        finally:
            await runner.aclose()
        assert planner.calls == 1
        assert runtime.executed_plans == []  # no Neo4j work after a planner failure
        # the raw provider message must not leak through the typed boundary error
        assert str(planner_error) not in str(captured.value)

    asyncio.run(scenario())


def test_concurrent_requests_keep_independent_plan_state() -> None:
    async def scenario() -> None:
        runtime = FakePlanningRuntime(IntentType.MULTI_HOP)
        plans = {
            query: _unlinked_plan(target=f"đích số {query}")
            for query in ("a", "b", "c", "d")
        }
        planner = _PerQueryPlanner(plans)
        runner = BoundedRetrievalRunner(
            max_concurrency=4, timeout_seconds=1, shutdown_grace_seconds=1
        )
        service = GraphRAGRetrievalService(
            runtime, runner, planner=planner, planning_enabled=True
        )
        try:
            await asyncio.gather(
                *(
                    service.retrieve_context(RetrievalRequest(query=query))
                    for query in plans
                )
            )
        finally:
            await runner.aclose()
        # every request executed with exactly its own plan, none shared or dropped
        assert set(runtime.executed_plans) == set(plans.values())
        assert len(runtime.executed_plans) == len(plans)

    asyncio.run(scenario())


def test_planner_cancellation_propagates_without_execution() -> None:
    async def scenario() -> None:
        runtime = FakePlanningRuntime(IntentType.MULTI_HOP)
        planner = FakePlanner(error=asyncio.CancelledError())
        runner = _runner()
        service = GraphRAGRetrievalService(
            runtime, runner, planner=planner, planning_enabled=True
        )
        try:
            with pytest.raises(asyncio.CancelledError):
                await service.retrieve_context(RetrievalRequest(query="multi hop"))
        finally:
            await runner.aclose()
        assert runtime.executed_plans == []

    asyncio.run(scenario())


def test_planning_disabled_uses_legacy_retrieve_path() -> None:
    async def scenario() -> None:
        runtime = FakeRuntime()
        planner = FakePlanner(plan=_unlinked_plan())
        runner = _runner()
        service = GraphRAGRetrievalService(
            runtime, runner, planner=planner, planning_enabled=False
        )
        try:
            await service.retrieve_context(RetrievalRequest(query="quyền"))
        finally:
            await runner.aclose()
        assert planner.calls == 0
        assert len(runtime.requests) == 1

    asyncio.run(scenario())


def test_service_calls_runtime_once_and_maps_response() -> None:
    async def scenario() -> None:
        runtime = FakeRuntime()
        runner = BoundedRetrievalRunner(
            max_concurrency=1,
            timeout_seconds=1,
            shutdown_grace_seconds=1,
        )
        service = RetrievalQueryService(GraphRAGRetrievalService(runtime, runner))
        try:
            response = await service.retrieve(
                QueryRequest(query="quyền", document_ids=["doc"])
            )
        finally:
            await runner.aclose()

        assert response.query == "quyền thành lập doanh nghiệp"
        assert len(runtime.requests) == 1
        assert runtime.requests[0].filters.document_ids == ["doc"]

    asyncio.run(scenario())


def test_no_results_is_not_converted_to_an_error() -> None:
    async def scenario() -> None:
        runtime = FakeRuntime()
        runner = BoundedRetrievalRunner(
            max_concurrency=1,
            timeout_seconds=1,
            shutdown_grace_seconds=1,
        )
        service = GraphRAGRetrievalService(runtime, runner)
        try:
            context = await service.retrieve_context(RetrievalRequest(query="none"))
        finally:
            await runner.aclose()
        assert context.capability_status == "no_results"

    asyncio.run(scenario())


def test_typed_runtime_failure_propagates_unchanged() -> None:
    async def scenario() -> None:
        error = RetrievalCapabilityError(
            "missing versions",
            required_capability="multiple_versions",
            available_capability="single_version",
        )
        runtime = FakeRuntime(error=error)
        runner = BoundedRetrievalRunner(
            max_concurrency=1,
            timeout_seconds=1,
            shutdown_grace_seconds=1,
        )
        service = GraphRAGRetrievalService(runtime, runner)
        try:
            with pytest.raises(RetrievalCapabilityError) as captured:
                await service.retrieve_context(RetrievalRequest(query="compare"))
        finally:
            await runner.aclose()
        assert captured.value is error
        assert len(runtime.requests) == 1

    asyncio.run(scenario())
