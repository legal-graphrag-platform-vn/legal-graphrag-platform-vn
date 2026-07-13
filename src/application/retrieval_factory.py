"""The only concrete assembly point for the retrieval runtime."""

from __future__ import annotations

import importlib.util
import logging
from collections.abc import Callable
from datetime import date
from typing import Any, Protocol

from neo4j import GraphDatabase
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.infrastructure.embedding.embedding_generator import EmbeddingGenerator
from src.infrastructure.neo4j.retriever_repo import Neo4jRetrieverRepo
from src.retrieval.config import RetrievalConfig
from src.retrieval.context.context_builder import ContextBuilder
from src.retrieval.context.temporal_filter import TemporalFilter
from src.retrieval.errors import RetrievalDependencyError
from src.retrieval.evidence.verifier import EvidenceVerifier
from src.retrieval.fusion.reciprocal_rank_fusion import ReciprocalRankFusion
from src.retrieval.reranking.bge_reranker import BGEReranker
from src.retrieval.retriever.fulltext import FULLTEXT_INDEX, FullTextRetriever
from src.retrieval.retriever.graph import GraphRetriever
from src.retrieval.retriever.hybrid import SeedChannelExecutor
from src.retrieval.retriever.vector import VECTOR_INDEXES, VectorRetriever
from src.retrieval.routing.router import IntentRouter
from src.retrieval.runtime.lifecycle import RetrievalRuntimeHandle
from src.retrieval.runtime.runtime import RetrievalRuntime
from src.shared.retrieval_contract import RetrievalFilters


logger = logging.getLogger(__name__)


class DriverProtocol(Protocol):
    def verify_connectivity(self) -> None: ...

    def session(self) -> Any: ...

    def close(self) -> None: ...


class RetrievalApplicationSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", frozen=True
    )

    neo4j_uri: str = Field(validation_alias="NEO4J_URI")
    neo4j_user: str = Field(default="neo4j", validation_alias="NEO4J_USER")
    neo4j_password: str = Field(default="", validation_alias="NEO4J_PASSWORD")
    embedding_model: str | None = Field(
        default="BAAI/bge-m3", validation_alias="EMBEDDING_MODEL"
    )
    embedding_provider: str | None = Field(
        default="flag_embedding", validation_alias="EMBEDDING_PROVIDER"
    )
    embedding_dimension: int | None = Field(
        default=1024, validation_alias="EMBEDDING_DIM"
    )


DriverFactory = Callable[[str, tuple[str, str]], DriverProtocol]


def inspect_retrieval_capabilities(
    filters: RetrievalFilters,
    application_settings: RetrievalApplicationSettings | None = None,
    *,
    driver_factory: DriverFactory | None = None,
) -> dict[str, object]:
    """Read scoped Neo4j capabilities without constructing retrieval models."""
    settings = application_settings or RetrievalApplicationSettings()
    factory = driver_factory or _default_driver_factory
    driver = factory(
        settings.neo4j_uri,
        (settings.neo4j_user, settings.neo4j_password),
    )
    try:
        driver.verify_connectivity()
        repo = Neo4jRetrieverRepo(driver)  # type: ignore[arg-type]
        return repo.inspect_capabilities(filters)
    finally:
        driver.close()


def inspect_retrieval_artifact_runtime(
    filters: RetrievalFilters,
    temporal_unit_ids: list[str],
    application_settings: RetrievalApplicationSettings | None = None,
    *,
    driver_factory: DriverFactory | None = None,
) -> dict[str, object]:
    """Read capability, temporal-subject, and Neo4j identity evidence."""
    settings = application_settings or RetrievalApplicationSettings()
    factory = driver_factory or _default_driver_factory
    driver = factory(
        settings.neo4j_uri,
        (settings.neo4j_user, settings.neo4j_password),
    )
    try:
        driver.verify_connectivity()
        repo = Neo4jRetrieverRepo(driver)  # type: ignore[arg-type]
        return {
            "capabilities": repo.inspect_capabilities(filters),
            "temporal_units": repo.inspect_temporal_units(temporal_unit_ids),
            "runtime_identity": repo.inspect_runtime_identity(),
        }
    finally:
        driver.close()


class SystemClock:
    def today(self) -> date:
        return date.today()


def create_retrieval_runtime(
    config: RetrievalConfig | None = None,
    application_settings: RetrievalApplicationSettings | None = None,
    *,
    driver_factory: DriverFactory | None = None,
    embedding_factory: Callable[..., Any] = EmbeddingGenerator,
    reranker_factory: Callable[..., Any] = BGEReranker,
) -> RetrievalRuntimeHandle:
    runtime_config = config or RetrievalConfig()
    settings = application_settings or RetrievalApplicationSettings()
    factory = driver_factory or _default_driver_factory
    driver: DriverProtocol | None = None
    callbacks: list[Callable[[], None]] = []
    try:
        driver = factory(
            settings.neo4j_uri,
            (settings.neo4j_user, settings.neo4j_password),
        )
        callbacks.append(driver.close)
        driver.verify_connectivity()
        repo = Neo4jRetrieverRepo(driver)  # type: ignore[arg-type]
        _verify_enabled_dependencies(runtime_config, settings, repo)

        vector = None
        if runtime_config.vector_enabled:
            generator = embedding_factory(
                model_name=settings.embedding_model,
                provider=settings.embedding_provider,
                expected_dimension=settings.embedding_dimension,
                normalize_embeddings=True,
            )
            vector = VectorRetriever(repo, generator)
        fulltext = FullTextRetriever(repo) if runtime_config.fulltext_enabled else None
        graph = GraphRetriever(repo) if runtime_config.graph_enabled else None
        reranker = None
        if runtime_config.reranker_enabled:
            reranker = reranker_factory(
                runtime_config.reranker_model,
                use_fp16=runtime_config.reranker_fp16,
                max_length=runtime_config.reranker_max_length,
                normalize=runtime_config.reranker_normalize,
            )

        runtime = RetrievalRuntime(
            router=IntentRouter(runtime_config, clock=SystemClock()),
            seed_executor=SeedChannelExecutor(
                vector=vector,
                fulltext=fulltext,
            ),
            graph_retriever=graph,
            capability_inspector=repo,
            fusion=ReciprocalRankFusion(runtime_config.rrf_k),
            temporal_filter=TemporalFilter(),
            context_builder=ContextBuilder(EvidenceVerifier()),
            reranker=reranker,
        )
        return RetrievalRuntimeHandle(runtime, close_callbacks=callbacks)
    except Exception:
        for callback in reversed(callbacks):
            try:
                callback()
            except Exception as cleanup_error:
                logger.error(
                    "Retrieval factory cleanup failed: error_type=%s",
                    type(cleanup_error).__name__,
                )
        raise


def _verify_enabled_dependencies(
    config: RetrievalConfig,
    settings: RetrievalApplicationSettings,
    repo: Neo4jRetrieverRepo,
) -> None:
    inspection = repo.inspect_dependencies()
    indexes = inspection.get("indexes")
    if not isinstance(indexes, dict):
        raise RetrievalDependencyError("Neo4j returned an invalid index inventory")

    required_indexes: list[str] = []
    if config.vector_enabled:
        required_indexes.extend(VECTOR_INDEXES)
        _verify_embedding_settings(settings)
    if config.fulltext_enabled:
        required_indexes.append(FULLTEXT_INDEX)
    missing = [name for name in required_indexes if name not in indexes]
    offline = [
        name
        for name in required_indexes
        if name in indexes and indexes[name].get("state") != "ONLINE"
    ]
    if missing:
        raise RetrievalDependencyError(
            f"Missing enabled retrieval indexes: {sorted(missing)}"
        )
    if offline:
        raise RetrievalDependencyError(
            f"Enabled retrieval indexes are not ONLINE: {sorted(offline)}"
        )
    if config.vector_enabled:
        _verify_vector_indexes(indexes, settings)
    if config.fulltext_enabled and indexes[FULLTEXT_INDEX].get("type") != "FULLTEXT":
        raise RetrievalDependencyError(
            f"Enabled full-text index has wrong type: {FULLTEXT_INDEX}"
        )


def _verify_embedding_settings(settings: RetrievalApplicationSettings) -> None:
    if not settings.embedding_model or not settings.embedding_provider:
        raise RetrievalDependencyError(
            "Vector retrieval requires EMBEDDING_MODEL and EMBEDDING_PROVIDER"
        )
    if settings.embedding_dimension is None or settings.embedding_dimension < 1:
        raise RetrievalDependencyError("Vector retrieval requires EMBEDDING_DIM")
    packages = {
        "flag_embedding": "FlagEmbedding",
        "sentence_transformers": "sentence_transformers",
    }
    package = packages.get(settings.embedding_provider)
    if package is None:
        raise RetrievalDependencyError(
            f"Unsupported embedding provider: {settings.embedding_provider}"
        )
    if importlib.util.find_spec(package) is None:
        raise RetrievalDependencyError(
            f"Embedding provider package is not installed: {package}"
        )


def _verify_vector_indexes(
    indexes: dict[str, Any], settings: RetrievalApplicationSettings
) -> None:
    expected_dimension = settings.embedding_dimension
    for name in VECTOR_INDEXES:
        index = indexes[name]
        if index.get("type") != "VECTOR":
            raise RetrievalDependencyError(
                f"Enabled vector index has wrong type: {name}"
            )
        options = index.get("options") or {}
        index_config = options.get("indexConfig") or {}
        actual_dimension = index_config.get("vector.dimensions")
        if actual_dimension != expected_dimension:
            raise RetrievalDependencyError(
                f"Vector index {name} dimension {actual_dimension!r} does not match "
                f"configured EMBEDDING_DIM={expected_dimension}"
            )


def _default_driver_factory(uri: str, auth: tuple[str, str]) -> DriverProtocol:
    return GraphDatabase.driver(uri, auth=auth)
