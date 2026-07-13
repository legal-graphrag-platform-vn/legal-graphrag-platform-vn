"""Explicit ownership for retrieval runtime resources."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from types import TracebackType

from src.retrieval.models import RetrievalContext, RetrievalRequest
from src.retrieval.runtime.runtime import RetrievalRuntime


class RetrievalRuntimeHandle:
    def __init__(
        self,
        runtime: RetrievalRuntime,
        *,
        close_callbacks: Sequence[Callable[[], None]] = (),
    ) -> None:
        self._runtime = runtime
        self._close_callbacks = list(close_callbacks)
        self._closed = False

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
        self, request: RetrievalRequest | str, **kwargs: object
    ) -> RetrievalContext:
        return self._runtime.retrieve(request, **kwargs)

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
