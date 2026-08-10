"""Backend application service for the existing synchronous retrieval runtime."""

from __future__ import annotations

import asyncio
import logging
import time
from functools import partial

from api.models import QueryRequest, RetrievalResponse
from observability import log_event, redact
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
from src.retrieval.resolved_reference import RetrievalExecutionContext


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

    async def warmup(self) -> None:
        """Pre-load and warm up embedding encoder and reranker at startup."""
        logger.info("Warming up GraphRAG embedding and retrieval models...")
        try:
            warmup_request = RetrievalRequest(query_text="khởi động hệ thống pháp luật")
            await self._runner.run(partial(self._runtime.retrieve, warmup_request))
            logger.info("GraphRAG model warm-up completed successfully.")
        except Exception as exc:
            logger.warning("GraphRAG model warm-up encountered a non-fatal error: %s", exc)

    async def retrieve_context(
        self,
        request: RetrievalRequest,
        *,
        execution_context: RetrievalExecutionContext | None = None,
    ) -> RetrievalContext:
        if self._planner is None or not self._planning_enabled:
            context = await self._runner.run(
                partial(
                    self._runtime.retrieve,
                    request,
                    execution_context=execution_context,
                )
            )
            context.metrics["planner_provider_calls"] = 0
            return context

        prepared = await self._runner.run(
            partial(
                self._runtime.prepare,
                request,
                execution_context=execution_context,
            )
        )
        plan: UnlinkedSemanticPlan | None = None
        planner_provider_calls = 0
        if prepared.routing.decision.intent is IntentType.MULTI_HOP:
            plan = await self._plan(request.query)
            planner_provider_calls = 1
        context = await self._runner.run(
            partial(self._runtime.execute, prepared, plan=plan)
        )
        context.metrics["planner_provider_calls"] = planner_provider_calls
        return context

    async def _plan(self, query: str) -> UnlinkedSemanticPlan:
        """Plan on the event loop; surface planner infra failures as typed errors.

        A produced-but-unbindable plan is handled downstream (fail-closed generic
        retrieval + cannot-answer at the generation gate). Provider infra failures
        instead become typed backend errors so the API distinguishes them from a
        legitimate no-results or plan-failed outcome, and never leak provider payload.
        """
        assert self._planner is not None
        started = time.perf_counter()
        try:
            plan = await self._planner.plan(query)
        except asyncio.CancelledError:
            log_event(
                "retrieval.planner",
                "cancelled",
                latency_ms=_elapsed_ms(started),
                provider=self._planner.provider_name,
                model=self._planner.model_name,
                query=redact(query),
            )
            raise
        except QueryPlannerTimeoutError as exc:
            self._log_planner_failure(query, started, exc)
            raise BackendPlanningTimeoutError(
                "Lập kế hoạch truy vấn vượt quá thời gian cho phép."
            ) from exc
        except QueryPlannerDependencyError as exc:
            self._log_planner_failure(query, started, exc)
            raise BackendPlanningUnavailableError(
                "Dịch vụ lập kế hoạch truy vấn hiện không khả dụng."
            ) from exc
        except QueryPlannerInvalidPlanError as exc:
            self._log_planner_failure(query, started, exc)
            raise BackendPlanningOutputError(
                "Bộ lập kế hoạch truy vấn trả về kế hoạch không hợp lệ."
            ) from exc
        log_event(
            "retrieval.planner",
            "ok",
            latency_ms=_elapsed_ms(started),
            provider=self._planner.provider_name,
            model=self._planner.model_name,
            query=redact(query),
            plan_depth=len(plan.steps),
            relations=[step.relation for step in plan.steps],
            directions=[step.direction for step in plan.steps],
            next_labels=[step.next_label for step in plan.steps],
        )
        return plan

    def _log_planner_failure(
        self,
        query: str,
        started: float,
        error: Exception,
    ) -> None:
        assert self._planner is not None
        log_event(
            "retrieval.planner",
            "error",
            latency_ms=_elapsed_ms(started),
            provider=self._planner.provider_name,
            model=self._planner.model_name,
            query=redact(query),
            error_type=type(error).__name__,
        )


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


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
