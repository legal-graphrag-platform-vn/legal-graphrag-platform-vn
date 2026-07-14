"""Backend application service for the existing synchronous retrieval runtime."""

from __future__ import annotations

import logging
from functools import partial

from api.models import QueryRequest, RetrievalResponse
from services.interfaces import (
    AsyncRetrievalRunner,
    RetrievalApplicationPort,
    SyncRetrievalRuntime,
)
from services.retrieval_mapping import to_retrieval_request, to_retrieval_response
from src.retrieval.models import RetrievalContext
from src.shared.retrieval_contract import RetrievalRequest


logger = logging.getLogger(__name__)


class GraphRAGRetrievalService(RetrievalApplicationPort):
    def __init__(
        self,
        runtime: SyncRetrievalRuntime,
        runner: AsyncRetrievalRunner,
    ) -> None:
        self._runtime = runtime
        self._runner = runner

    async def retrieve_context(
        self,
        request: RetrievalRequest,
    ) -> RetrievalContext:
        return await self._runner.run(partial(self._runtime.retrieve, request))


class RetrievalQueryService:
    def __init__(self, retrieval: RetrievalApplicationPort) -> None:
        self._retrieval = retrieval

    async def retrieve(self, request: QueryRequest) -> RetrievalResponse:
        context = await self._retrieval.retrieve_context(to_retrieval_request(request))
        logger.info(
            "Backend retrieval completed: contract_version=%s intent=%s "
            "strategy=%s retrieval_mode=%s channels=%s document_filter_count=%d "
            "result_count=%d latency_ms=%s",
            context.contract_version,
            context.intent.value,
            context.strategy.value,
            context.retrieval_mode,
            [channel.value for channel in context.executed_channels],
            len(context.filters_applied.document_ids),
            len(context.retrieved_units),
            context.metrics.get("total_pipeline_latency_ms"),
        )
        return to_retrieval_response(context)
