"""Backend application service for the existing synchronous retrieval runtime."""

from __future__ import annotations

import asyncio
import logging
from functools import partial

from api.models import QueryRequest, RetrievalResponse
from services.errors import (
    BackendPlanningOutputError,
    BackendPlanningTimeoutError,
    BackendPlanningUnavailableError,
)
from services.interfaces import (
    AsyncRetrievalRunner,
    QueryPlannerPort,
    RetrievalApplicationPort,
    SyncRetrievalRuntime,
)
from services.retrieval_mapping import to_retrieval_request, to_retrieval_response
from src.retrieval.models import IntentType, RetrievalContext
from src.retrieval.planning.errors import (
    QueryPlannerDependencyError,
    QueryPlannerInvalidPlanError,
    QueryPlannerTimeoutError,
)
from src.retrieval.planning.models import UnlinkedSemanticPlan
from src.shared.retrieval_contract import RetrievalRequest


logger = logging.getLogger(__name__)


class GraphRAGRetrievalService(RetrievalApplicationPort):
    def __init__(
        self,
        runtime: SyncRetrievalRuntime,
        runner: AsyncRetrievalRunner,
        *,
        planner: QueryPlannerPort | None = None,
        planning_enabled: bool = False,
    ) -> None:
        self._runtime = runtime
        self._runner = runner
        self._planner = planner
        self._planning_enabled = planning_enabled

    async def retrieve_context(
        self,
        request: RetrievalRequest,
    ) -> RetrievalContext:
        if self._planner is None or not self._planning_enabled:
            return await self._runner.run(partial(self._runtime.retrieve, request))

        prepared = await self._runner.run(partial(self._runtime.prepare, request))
        plan: UnlinkedSemanticPlan | None = None
        if prepared.routing.decision.intent is IntentType.MULTI_HOP:
            plan = await self._plan(request.query)
        return await self._runner.run(
            partial(self._runtime.execute, prepared, plan=plan)
        )

    async def _plan(self, query: str) -> UnlinkedSemanticPlan:
        """Plan on the event loop; surface planner infra failures as typed errors.

        A produced-but-unbindable plan is handled downstream (fail-closed generic
        retrieval + cannot-answer at the generation gate). Provider infra failures
        instead become typed backend errors so the API distinguishes them from a
        legitimate no-results or plan-failed outcome, and never leak provider payload.
        """
        assert self._planner is not None
        try:
            return await self._planner.plan(query)
        except asyncio.CancelledError:
            raise
        except QueryPlannerTimeoutError as exc:
            raise BackendPlanningTimeoutError(
                "Lập kế hoạch truy vấn vượt quá thời gian cho phép."
            ) from exc
        except QueryPlannerDependencyError as exc:
            raise BackendPlanningUnavailableError(
                "Dịch vụ lập kế hoạch truy vấn hiện không khả dụng."
            ) from exc
        except QueryPlannerInvalidPlanError as exc:
            raise BackendPlanningOutputError(
                "Bộ lập kế hoạch truy vấn trả về kế hoạch không hợp lệ."
            ) from exc


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
