"""Explicit ownership for retrieval runtime resources."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from types import TracebackType

from src.retrieval.models import (
    PreparedRetrievalRequest,
    RetrievalContext,
    RetrievalRequest,
)
from src.retrieval.planning.binder import PlanBinder, PlanBindingFailure
from src.retrieval.planning.models import BoundSemanticPlan, UnlinkedSemanticPlan
from src.retrieval.ports import EmbeddingPort
from src.retrieval.runtime.runtime import RetrievalRuntime
from src.retrieval.resolved_reference import RetrievalExecutionContext


class RetrievalRuntimeHandle:
    def __init__(
        self,
        runtime: RetrievalRuntime,
        *,
        binder: PlanBinder | None = None,
        close_callbacks: Sequence[Callable[[], None]] = (),
        # Encoder dùng riêng cho warmup — không qua Neo4j.
        warmup_encoder: EmbeddingPort | None = None,
    ) -> None:
        self._runtime = runtime
        self._binder = binder
        self._close_callbacks = list(close_callbacks)
        self._closed = False
        self.warmup_encoder: EmbeddingPort | None = warmup_encoder

    def __enter__(self) -> "RetrievalRuntimeHandle":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def retrieve(
        self,
        request: RetrievalRequest | str,
        *,
        execution_context: RetrievalExecutionContext | None = None,
        **kwargs: object,
    ) -> RetrievalContext:
        return self._runtime.retrieve(
            request,
            execution_context=execution_context,
            **kwargs,
        )

    def prepare(
        self,
        request: RetrievalRequest | str,
        *,
        execution_context: RetrievalExecutionContext | None = None,
        **kwargs: object,
    ) -> PreparedRetrievalRequest:
        return self._runtime.prepare(
            request,
            execution_context=execution_context,
            **kwargs,
        )

    def execute(
        self,
        prepared: PreparedRetrievalRequest,
        *,
        plan: UnlinkedSemanticPlan | None = None,
    ) -> RetrievalContext:
        """Bind an unlinked plan then execute; fail closed on any binding gap."""
        if plan is None or self._binder is None:
            return self._runtime.execute(prepared)
        outcome = self._binder.bind(plan, prepared.routing.filters)
        if isinstance(outcome, PlanBindingFailure):
            return self._runtime.execute(
                prepared, binding_reason_code=outcome.reason_code
            )
        assert isinstance(outcome, BoundSemanticPlan)
        return self._runtime.execute(prepared, bound_plan=outcome)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        first_error: Exception | None = None
        for callback in reversed(self._close_callbacks):
            try:
                callback()
            except (
                Exception
            ) as exc:  # cleanup continues, then reports the first failure
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error
