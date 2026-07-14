"""Build and own backend application-level dependencies."""

from __future__ import annotations

from collections.abc import Callable

from services.graphrag_retrieval_service import (
    GraphRAGRetrievalService,
    RetrievalQueryService,
)
from services.interfaces import (
    AsyncRetrievalRunner,
    QueryService,
    RAGService,
    SyncRetrievalRuntime,
)
from services.mock_rag_service import MockRAGService
from services.retrieval_runner import BoundedRetrievalRunner
from settings import Settings


class Container:
    def __init__(
        self,
        *,
        query_service: QueryService,
        rag_service: RAGService | None,
        retrieval_runtime: SyncRetrievalRuntime | None = None,
        retrieval_runner: AsyncRetrievalRunner | None = None,
    ) -> None:
        self.query_service = query_service
        self.rag_service = rag_service
        self._retrieval_runtime = retrieval_runtime
        self._retrieval_runner = retrieval_runner
        self._closed = False

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        first_error: Exception | None = None
        if self._retrieval_runner is not None:
            try:
                await self._retrieval_runner.aclose()
            except Exception as exc:
                first_error = exc
        if self._retrieval_runtime is not None:
            try:
                self._retrieval_runtime.close()
            except Exception as exc:
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error


def build_container(
    settings: Settings,
    *,
    runtime_factory: Callable[..., SyncRetrievalRuntime] | None = None,
    runner_factory: Callable[..., AsyncRetrievalRunner] = BoundedRetrievalRunner,
) -> Container:
    """Build mock or retrieval-only GraphRAG dependencies."""
    if settings.app_mode == "mock":
        mock = MockRAGService()
        return Container(query_service=mock, rag_service=mock)

    # Retrieval-only pilot integration; no answer generation or mock fallback.
    from src.application.retrieval_factory import (
        RetrievalApplicationSettings,
        create_retrieval_runtime,
    )
    from src.retrieval.config import RetrievalConfig

    factory = runtime_factory or create_retrieval_runtime
    runtime = factory(
        RetrievalConfig(),
        RetrievalApplicationSettings(
            NEO4J_URI=settings.neo4j_uri,
            NEO4J_USER=settings.neo4j_user,
            NEO4J_PASSWORD=settings.neo4j_password,
        ),
    )
    try:
        runner = runner_factory(
            max_concurrency=settings.backend_retrieval_max_concurrency,
            timeout_seconds=settings.backend_retrieval_timeout_seconds,
            shutdown_grace_seconds=(settings.backend_retrieval_shutdown_grace_seconds),
        )
    except Exception:
        runtime.close()
        raise
    retrieval = GraphRAGRetrievalService(runtime, runner)
    return Container(
        query_service=RetrievalQueryService(retrieval),
        rag_service=None,
        retrieval_runtime=runtime,
        retrieval_runner=runner,
    )
