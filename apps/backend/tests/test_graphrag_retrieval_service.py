from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

from api.models import QueryRequest
from observability import bind_trace, clear_trace, get_turn_trace
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

    def retrieve(self, request: RetrievalRequest, *, execution_context=None):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return retrieval_context(no_results=request.query == "none")

    def close(self) -> None:
        return None


class FakePlanningRuntime:
    """Runtime that exposes prepare/execute for the planning orchestration path."""

    def __init__(self, intent: IntentType) -> None:
        self._intent = intent
        self.prepare_calls = 0
        self.prepared_requests: list[object] = []
        self.executed_plans: list[object] = []
        self.executions: list[tuple[str, object]] = []
        self.prepare_thread_ids: list[int] = []
        self.execute_thread_ids: list[int] = []

    def prepare(self, request: RetrievalRequest, *, execution_context=None):
        self.prepare_calls += 1
        self.prepare_thread_ids.append(threading.get_ident())
        prepared = SimpleNamespace(
            request=request,
            routing=SimpleNamespace(decision=SimpleNamespace(intent=self._intent)),
        )
        self.prepared_requests.append(prepared)
        return prepared

    def execute(self, prepared, *, plan=None):
        assert prepared in self.prepared_requests
        self.execute_thread_ids.append(threading.get_ident())
        self.executed_plans.append(plan)
        self.executions.append((prepared.request.query, plan))
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
        self.thread_ids: list[int] = []

    async def plan(self, query: str):
        self.calls += 1
        self.thread_ids.append(threading.get_ident())
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
            context = await service.retrieve_context(
                RetrievalRequest(query="multi hop")
            )
        finally:
            await runner.aclose()
        assert planner.calls == 1
        assert runtime.prepare_calls == 1
        assert runtime.executed_plans == [plan]
        assert context.metrics["planner_provider_calls"] == 1

    asyncio.run(scenario())


def test_multi_hop_planner_emits_bounded_trace_event() -> None:
    async def scenario() -> None:
        runtime = FakePlanningRuntime(IntentType.MULTI_HOP)
        planner = FakePlanner(plan=_unlinked_plan())
        runner = _runner()
        service = GraphRAGRetrievalService(
            runtime, runner, planner=planner, planning_enabled=True
        )
        bind_trace(turn_id="planner-trace")
        try:
            await service.retrieve_context(RetrievalRequest(query="multi hop secret"))
            event = next(
                item
                for item in get_turn_trace()
                if item["stage"] == "retrieval.planner"
            )
        finally:
            clear_trace()
            await runner.aclose()

        assert event["status"] == "ok"
        assert event["provider"] == "fake"
        assert event["model"] == "fake-model"
        assert event["plan_depth"] == 2
        assert event["relations"] == ["REFERS_TO", "REFERS_TO"]
        assert "steps" not in event

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
            context = await service.retrieve_context(RetrievalRequest(query="factual"))
        finally:
            await runner.aclose()
        assert planner.calls == 0
        assert runtime.executed_plans == [None]
        assert context.metrics["planner_provider_calls"] == 0

    asyncio.run(scenario())


def test_planner_stays_on_event_loop_while_runtime_work_uses_runner_thread() -> None:
    async def scenario() -> None:
        event_loop_thread_id = threading.get_ident()
        runtime = FakePlanningRuntime(IntentType.MULTI_HOP)
        planner = FakePlanner(plan=_unlinked_plan())
        runner = _runner()
        service = GraphRAGRetrievalService(
            runtime, runner, planner=planner, planning_enabled=True
        )
        try:
            await service.retrieve_context(RetrievalRequest(query="multi hop"))
        finally:
            await runner.aclose()

        assert planner.thread_ids == [event_loop_thread_id]
        assert runtime.prepare_thread_ids
        assert runtime.execute_thread_ids
        assert all(
            thread_id != event_loop_thread_id
            for thread_id in runtime.prepare_thread_ids + runtime.execute_thread_ids
        )

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
        # Every prepared request is paired with its own plan. Merely comparing the
        # plan set would miss a cross-request swap between two concurrent calls.
        assert dict(runtime.executions) == plans
        assert len(runtime.executions) == len(plans)

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
