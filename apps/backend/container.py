"""Build and own backend application-level dependencies."""

from __future__ import annotations

import logging
from collections.abc import Callable

from services.graphrag_retrieval_service import (
    GraphRAGRetrievalService,
    RetrievalQueryService,
)
from services.interfaces import (
    AnswerGeneratorPort,
    AsyncRetrievalRunner,
    ChatService,
    QueryService,
    RAGService,
    SyncRetrievalRuntime,
)
from services.mock_rag_service import MockRAGService
from services.retrieval_runner import BoundedRetrievalRunner
from settings import Settings


logger = logging.getLogger(__name__)


class Container:
    def __init__(
        self,
        *,
        query_service: QueryService,
        chat_service: ChatService | None,
        rag_service: RAGService | None,
        answer_generator: AnswerGeneratorPort | None = None,
        retrieval_runtime: SyncRetrievalRuntime | None = None,
        retrieval_runner: AsyncRetrievalRunner | None = None,
    ) -> None:
        self.query_service = query_service
        self.chat_service = chat_service
        self.rag_service = rag_service
        self._answer_generator = answer_generator
        self._retrieval_runtime = retrieval_runtime
        self._retrieval_runner = retrieval_runner
        self._closed = False

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        first_error: Exception | None = None
        if self._answer_generator is not None:
            try:
                await self._answer_generator.aclose()
            except Exception as exc:
                first_error = exc
        if self._retrieval_runner is not None:
            try:
                await self._retrieval_runner.aclose()
            except Exception as exc:
                if first_error is None:
                    first_error = exc
        if self._retrieval_runtime is not None:
            try:
                self._retrieval_runtime.close()
            except Exception as exc:
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error


async def build_container(
    settings: Settings,
    *,
    runtime_factory: Callable[..., SyncRetrievalRuntime] | None = None,
    runner_factory: Callable[..., AsyncRetrievalRunner] = BoundedRetrievalRunner,
    answer_factory: Callable[..., AnswerGeneratorPort] | None = None,
) -> Container:
    """Build mock or explicitly enabled GraphRAG dependencies."""
    if settings.app_mode == "mock":
        mock = MockRAGService()
        return Container(query_service=mock, chat_service=mock, rag_service=mock)

    # Pilot GraphRAG integration; no mock fallback.
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
        _close_runtime_after_startup_failure(runtime)
        raise
    retrieval = GraphRAGRetrievalService(runtime, runner)
    answer_generator: AnswerGeneratorPort | None = None
    chat_service: ChatService | None = None
    if settings.answer_generation_enabled:
        from services.graphrag_answer_service import GraphRAGAnswerService
        from src.application.answer_factory import (
            AnswerApplicationSettings,
            create_answer_generator,
        )
        from src.generation.config import GenerationConfig

        generator_factory = answer_factory or create_answer_generator
        try:
            answer_generator = generator_factory(
                GenerationConfig(
                    timeout_seconds=settings.answer_timeout_seconds,
                    max_concurrency=settings.answer_max_concurrency,
                    max_retries=settings.answer_max_retries,
                    max_output_tokens=settings.answer_max_output_tokens,
                    temperature=settings.answer_temperature,
                    context_max_chars=settings.answer_context_max_chars,
                    history_max_messages=settings.answer_history_max_messages,
                    history_max_chars=settings.answer_history_max_chars,
                    stream_chunk_chars=settings.answer_stream_chunk_chars,
                ),
                AnswerApplicationSettings(
                    ANSWER_PROVIDER=settings.answer_provider,
                    ANSWER_MODEL=settings.answer_model,
                    GEMINI_API_KEY=settings.gemini_api_key,
                ),
            )
        except Exception:
            await _cleanup_retrieval_after_startup_failure(runner, runtime)
            raise
        chat_service = GraphRAGAnswerService(
            retrieval=retrieval,
            generator=answer_generator,
            stream_chunk_chars=settings.answer_stream_chunk_chars,
        )
    return Container(
        query_service=RetrievalQueryService(retrieval),
        chat_service=chat_service,
        rag_service=None,
        answer_generator=answer_generator,
        retrieval_runtime=runtime,
        retrieval_runner=runner,
    )


async def _cleanup_retrieval_after_startup_failure(
    runner: AsyncRetrievalRunner,
    runtime: SyncRetrievalRuntime,
) -> None:
    try:
        await runner.aclose()
    except Exception as exc:
        logger.error(
            "Retrieval runner cleanup failed during startup rollback: error_type=%s",
            type(exc).__name__,
        )
    _close_runtime_after_startup_failure(runtime)


def _close_runtime_after_startup_failure(runtime: SyncRetrievalRuntime) -> None:
    try:
        runtime.close()
    except Exception as exc:
        logger.error(
            "Retrieval runtime cleanup failed during startup rollback: error_type=%s",
            type(exc).__name__,
        )
