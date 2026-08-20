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
    DocumentBrowserService,
    QueryPlannerPort,
    QueryProcessorPort,
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
        document_service: DocumentBrowserService,
        rag_service: RAGService | None,
        answer_generator: AnswerGeneratorPort | None = None,
        query_planner: QueryPlannerPort | None = None,
        retrieval_runtime: SyncRetrievalRuntime | None = None,
        retrieval_runner: AsyncRetrievalRunner | None = None,
        conversation_engine: object | None = None,
        canonical_lookup_driver: object | None = None,
        principal_signer: object | None = None,
        conversation_repo: object | None = None,
        debug_trace_store: object | None = None,
    ) -> None:
        self.query_service = query_service
        self.chat_service = chat_service
        self.document_service = document_service
        self.rag_service = rag_service
        self.principal_signer = principal_signer
        self.conversation_repo = conversation_repo
        self.debug_trace_store = debug_trace_store
        self._answer_generator = answer_generator
        self._query_planner = query_planner
        self._retrieval_runtime = retrieval_runtime
        self._retrieval_runner = retrieval_runner
        self.conversation_engine = conversation_engine
        self._canonical_lookup_driver = canonical_lookup_driver
        self._closed = False

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        first_error: Exception | None = None
        if self.conversation_engine is not None:
            try:
                await self.conversation_engine.dispose()
            except Exception as exc:
                first_error = exc
        if self._canonical_lookup_driver is not None:
            try:
                self._canonical_lookup_driver.close()
            except Exception as exc:
                if first_error is None:
                    first_error = exc
        if self._answer_generator is not None:
            try:
                await self._answer_generator.aclose()
            except Exception as exc:
                if first_error is None:
                    first_error = exc
        if self._query_planner is not None:
            try:
                await self._query_planner.aclose()
            except Exception as exc:
                if first_error is None:
                    first_error = exc
        try:
            await self.document_service.aclose()
        except Exception as exc:
            if first_error is None:
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
    planner_factory: Callable[..., QueryPlannerPort] | None = None,
    browser_factory: Callable[[Settings, AsyncRetrievalRunner], DocumentBrowserService]
    | None = None,
) -> Container:
    """Build mock or explicitly enabled GraphRAG dependencies."""
    if settings.app_mode == "mock":
        mock = MockRAGService()
        return Container(
            query_service=mock,
            chat_service=mock,
            document_service=mock,
            rag_service=mock,
        )

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
        planning_enabled=settings.query_planning_enabled,
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

    query_planner: QueryPlannerPort | None = None
    if settings.query_planning_enabled:
        try:
            query_planner = _create_query_planner(settings, planner_factory)
        except Exception:
            await _cleanup_retrieval_after_startup_failure(runner, runtime)
            raise

    retrieval = GraphRAGRetrievalService(
        runtime,
        runner,
        planner=query_planner,
        planning_enabled=settings.query_planning_enabled,
        warmup_encoder=getattr(runtime, "warmup_encoder", None),
    )
    create_browser = browser_factory or _create_document_browser_service
    try:
        document_service = create_browser(settings, runner)
    except Exception:
        await _cleanup_planner_after_startup_failure(query_planner, runner, runtime)
        raise
    answer_generator: AnswerGeneratorPort | None = None
    chat_service: ChatService | None = None
    conversation_engine: object | None = None
    lookup_driver: object | None = None
    principal_signer: object | None = None
    conversation_repo: object | None = None
    if settings.answer_generation_enabled:
        from src.application.answer_factory import (
            AnswerApplicationSettings,
            create_answer_generator,
        )
        from src.generation.config import GenerationConfig

        try:
            generation_config = GenerationConfig(
                timeout_seconds=settings.answer_timeout_seconds,
                max_concurrency=settings.answer_max_concurrency,
                max_retries=settings.answer_max_retries,
                max_output_tokens=settings.answer_max_output_tokens,
                temperature=settings.answer_temperature,
                thinking_level=settings.answer_thinking_level,
                context_max_chars=settings.answer_context_max_chars,
                context_safety_reserve_chars=(
                    settings.answer_context_safety_reserve_chars
                ),
                history_max_messages=settings.answer_history_max_messages,
                history_max_chars=settings.answer_history_max_chars,
                stream_chunk_chars=settings.answer_stream_chunk_chars,
            )
            application_settings = AnswerApplicationSettings(
                ANSWER_PROVIDER=settings.answer_provider,
                ANSWER_MODEL=settings.answer_model,
                GEMINI_API_KEY=settings.gemini_api_key,
            )
            from observability import TracedAnswerGenerator, TracedAnswerProvider

            if answer_factory is None:
                answer_generator = create_answer_generator(
                    generation_config,
                    application_settings,
                    provider_decorator=TracedAnswerProvider,
                )
            else:
                answer_generator = answer_factory(
                    generation_config,
                    application_settings,
                )

            answer_generator = TracedAnswerGenerator(answer_generator)
        except Exception:
            await _cleanup_after_answer_startup_failure(
                document_service,
                query_planner,
                runner,
                runtime,
            )
            raise
        try:
            (
                conversation_engine,
                chat_service,
                lookup_driver,
                principal_signer,
                conversation_repo,
            ) = _build_conversation_chat(settings, retrieval, answer_generator, runner)
        except Exception:
            await _cleanup_after_answer_startup_failure(
                document_service,
                query_planner,
                runner,
                runtime,
            )
            if answer_generator is not None:
                await answer_generator.aclose()
            raise
    debug_trace_store: object | None = None
    if conversation_engine is not None:
        from persistence.debug_trace import TurnDebugTraceStore

        debug_trace_store = TurnDebugTraceStore(conversation_engine)
    return Container(
        query_service=RetrievalQueryService(retrieval),
        chat_service=chat_service,
        document_service=document_service,
        rag_service=retrieval,
        answer_generator=answer_generator,
        query_planner=query_planner,
        retrieval_runtime=runtime,
        retrieval_runner=runner,
        conversation_engine=conversation_engine,
        canonical_lookup_driver=lookup_driver,
        principal_signer=principal_signer,
        conversation_repo=conversation_repo,
        debug_trace_store=debug_trace_store,
    )


def _build_conversation_chat(
    settings: Settings,
    retrieval: object,
    answer_generator: AnswerGeneratorPort,
    runner: AsyncRetrievalRunner,
) -> tuple[object, ChatService, object, object, object]:
    """Compose the grounded conversation chat service (Plan 19 §4)."""
    from neo4j import GraphDatabase

    from auth.principal import PrincipalSigner
    from conversation.service import ConversationChatService
    from persistence.engine import EngineConfig, create_engine
    from persistence.repository import SqlAlchemyConversationStore
    from resolution.canonical_lookup import (
        Neo4jCanonicalLookup,
        Neo4jCanonicalLookupRepo,
    )
    from resolution.resolver import ReferenceResolver
    from resolution.rewriter import StructuredRewriter

    engine = create_engine(
        EngineConfig(
            database_url=settings.database_url,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout_seconds=settings.db_pool_timeout_seconds,
        )
    )
    lookup_driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
    store = SqlAlchemyConversationStore(
        engine,
        lock_timeout_seconds=settings.conversation_lock_timeout_seconds,
        lock_poll_interval_seconds=settings.conversation_lock_poll_interval_seconds,
    )
    resolver = ReferenceResolver(
        Neo4jCanonicalLookup(Neo4jCanonicalLookupRepo(lookup_driver), runner)
    )
    # The Gemini structured-output fallback is a pluggable RewriterLLMPort; the
    # rule fast path covers explicit references and anchored anaphora today.
    rewriter = StructuredRewriter(llm=None)
    signer = PrincipalSigner(
        settings.anonymous_principal_signing_key or "",
        ttl_seconds=settings.anonymous_principal_cookie_ttl_days * 86400,
    )
    query_processor = _build_query_processor(settings, runner)
    chat_service = ConversationChatService(
        store=store,
        resolver=resolver,
        rewriter=rewriter,
        retrieval=retrieval,
        generator=answer_generator,
        stream_chunk_chars=settings.answer_stream_chunk_chars,
        query_processor=query_processor,
    )
    return engine, chat_service, lookup_driver, signer, store


def _build_query_processor(
    settings: Settings,
    runner: AsyncRetrievalRunner,
) -> QueryProcessorPort | None:
    """Build the five-field query processor when enabled (provider-swappable)."""
    if not settings.query_processor_enabled:
        return None

    from observability import TracedTextGenerator
    from query_processing.adapter import QueryProcessorAdapter
    from src.infrastructure.llm.text_generation_factory import build_text_generator
    from src.retrieval.nlu.prompts import (
        QUERY_PROCESSING_SYSTEM_PROMPT,
        QUERY_PROCESSING_SYSTEM_PROMPT_ZERO_SHOT,
    )
    from src.retrieval.nlu.query_processor import QueryProcessor

    text_generator = build_text_generator(
        env={
            "LLM_PROVIDER": settings.llm_provider,
            "GEMINI_API_KEY": settings.gemini_api_key or "",
            "GEMINI_QUERY_MODEL": settings.query_processor_model,
            "OLLAMA_MODEL": settings.llm_model,
            "OLLAMA_HOST": settings.ollama_base_url,
        }
    )
    # Trace the LLM I/O (prompt + raw output) of the query processor (Plan 21).
    traced_generator = TracedTextGenerator(text_generator, stage="query_processor")
    # The fine-tuned Qwen adapter (served via Ollama) was trained on the terser
    # QUERY_PROCESSING_SYSTEM_PROMPT and must keep receiving it unchanged;
    # Gemini has no such fine-tuning and needs the zero-shot variant with
    # explicit intent definitions to classify borderline questions
    # (factual vs validity) consistently.
    system_prompt = (
        QUERY_PROCESSING_SYSTEM_PROMPT
        if settings.llm_provider == "ollama"
        else QUERY_PROCESSING_SYSTEM_PROMPT_ZERO_SHOT
    )
    return QueryProcessorAdapter(
        QueryProcessor(traced_generator, system_prompt=system_prompt), runner
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


async def _cleanup_after_answer_startup_failure(
    document_service: DocumentBrowserService,
    query_planner: QueryPlannerPort | None,
    runner: AsyncRetrievalRunner,
    runtime: SyncRetrievalRuntime,
) -> None:
    try:
        await document_service.aclose()
    except Exception as exc:
        logger.error(
            "Document browser cleanup failed during startup rollback: error_type=%s",
            type(exc).__name__,
        )
    await _cleanup_planner_after_startup_failure(query_planner, runner, runtime)


async def _cleanup_planner_after_startup_failure(
    query_planner: QueryPlannerPort | None,
    runner: AsyncRetrievalRunner,
    runtime: SyncRetrievalRuntime,
) -> None:
    if query_planner is not None:
        try:
            await query_planner.aclose()
        except Exception as exc:
            logger.error(
                "Query planner cleanup failed during startup rollback: error_type=%s",
                type(exc).__name__,
            )
    await _cleanup_retrieval_after_startup_failure(runner, runtime)


def _create_query_planner(
    settings: Settings,
    planner_factory: Callable[..., QueryPlannerPort] | None,
) -> QueryPlannerPort:
    if planner_factory is not None:
        return planner_factory(settings)

    from src.application.gemini_query_planner import GeminiQueryPlanner
    from src.retrieval.planning.config import QueryPlannerConfig

    return GeminiQueryPlanner(
        api_key=settings.gemini_api_key or "",
        model=settings.query_planner_model,
        config=QueryPlannerConfig(
            timeout_seconds=settings.query_planner_timeout_seconds,
            max_concurrency=settings.query_planner_max_concurrency,
            max_retries=settings.query_planner_max_retries,
            max_output_tokens=settings.query_planner_max_output_tokens,
            temperature=settings.query_planner_temperature,
        ),
    )


def _create_document_browser_service(
    settings: Settings,
    runner: AsyncRetrievalRunner,
) -> DocumentBrowserService:
    from neo4j import GraphDatabase

    from services.document_browser_service import Neo4jDocumentBrowserService
    from src.infrastructure.neo4j.document_browser_repo import (
        Neo4jDocumentBrowserRepo,
    )

    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
    )
    return Neo4jDocumentBrowserService(Neo4jDocumentBrowserRepo(driver), runner)


def _close_runtime_after_startup_failure(runtime: SyncRetrievalRuntime) -> None:
    try:
        runtime.close()
    except Exception as exc:
        logger.error(
            "Retrieval runtime cleanup failed during startup rollback: error_type=%s",
            type(exc).__name__,
        )
