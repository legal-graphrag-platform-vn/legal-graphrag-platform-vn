from __future__ import annotations

import asyncio

import pytest

from api.models import QueryRequest
from services.graphrag_retrieval_service import (
    GraphRAGRetrievalService,
    RetrievalQueryService,
)
from services.retrieval_runner import BoundedRetrievalRunner
from src.retrieval.errors import RetrievalCapabilityError
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
