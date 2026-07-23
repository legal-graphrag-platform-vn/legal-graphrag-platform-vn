from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from api.models import QueryRequest
from services.graphrag_retrieval_service import (
    GraphRAGRetrievalService,
    RetrievalQueryService,
)
from services.retrieval_runner import BoundedRetrievalRunner
from src.retrieval.errors import RetrievalCapabilityError
from src.retrieval.models import IntentType
from src.retrieval.planning.errors import QueryPlannerTimeoutError
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


def _unlinked_plan() -> UnlinkedSemanticPlan:
    return UnlinkedSemanticPlan(
        anchor=AnchorMention(text="Khoản 3 Điều 145", expected_label="Clause"),
        target=TargetMention(text="điều kiện của lần họp thứ nhất"),
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


def test_planner_timeout_falls_back_to_generic_execution() -> None:
    async def scenario() -> None:
        runtime = FakePlanningRuntime(IntentType.MULTI_HOP)
        planner = FakePlanner(error=QueryPlannerTimeoutError("slow"))
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
        assert runtime.executed_plans == [None]
        assert context.capability_status == "supported"

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
