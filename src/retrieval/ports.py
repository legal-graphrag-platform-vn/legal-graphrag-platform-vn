"""Structural ports that keep retrieval independent from concrete adapters."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, Any, Mapping, Protocol, Sequence

from src.retrieval.models import GraphExpansion, IntentType, RetrievedUnit
from src.shared.retrieval_contract import RetrievalFilters

if TYPE_CHECKING:
    from src.retrieval.planning.executor import PlannedPathExecution
    from src.retrieval.planning.linker import (
        EndpointResolution,
        EndpointRole,
        SemanticEndpointResolution,
        StructuralEndpointResolution,
    )
    from src.retrieval.planning.models import BoundSemanticPlan


class VectorSearchPort(Protocol):
    def vector_search(
        self,
        index_name: str,
        query_embedding: list[float],
        *,
        filters: RetrievalFilters,
        k: int,
    ) -> list[dict[str, Any]]: ...


class FullTextSearchPort(Protocol):
    def fulltext_search(
        self,
        index_name: str,
        text_query: str,
        *,
        filters: RetrievalFilters,
        k: int,
    ) -> list[dict[str, Any]]: ...


class GraphExpansionPort(Protocol):
    def graph_expansion(
        self,
        entry_ids: list[str],
        relations: tuple[str, ...],
        direction: str,
        max_depth: int,
        *,
        filters: RetrievalFilters,
        limit: int = 50,
    ) -> list[dict[str, Any]]: ...


class StructuralEndpointLookupPort(Protocol):
    def lookup_structural_endpoints(
        self,
        *,
        label: str,
        document_number: str | None,
        article_number: str | None,
        clause_number: str | None,
        point_label: str | None,
        filters: RetrievalFilters,
        limit: int = 20,
    ) -> list[Mapping[str, Any]]: ...


class StructuralEndpointResolverPort(Protocol):
    def resolve(
        self,
        *,
        mention_text: str,
        role: "EndpointRole | str",
        expected_label: str | None,
        filters: RetrievalFilters,
    ) -> "StructuralEndpointResolution": ...


class SemanticEndpointResolverPort(Protocol):
    def resolve(
        self,
        *,
        mention_text: str,
        role: "EndpointRole | str",
        expected_label: str | None,
        filters: RetrievalFilters,
    ) -> "SemanticEndpointResolution": ...


class EndpointResolverPort(Protocol):
    def resolve(
        self,
        *,
        mention_text: str,
        role: "EndpointRole | str",
        expected_label: str | None,
        filters: RetrievalFilters,
    ) -> "EndpointResolution": ...


class PlannedPathLookupPort(Protocol):
    def lookup_exact_paths(
        self,
        *,
        anchor_id: str,
        target_id: str,
        steps: Sequence[Mapping[str, str]],
        filters: RetrievalFilters,
        limit: int,
    ) -> list[Mapping[str, Any]]: ...


class PlannedPathExecutionPort(Protocol):
    def execute(
        self,
        plan: "BoundSemanticPlan",
        *,
        filters: RetrievalFilters,
    ) -> "PlannedPathExecution": ...


class EmbeddingPort(Protocol):
    def encode(self, texts: list[str]) -> list[list[float]]: ...


class IntentClassifierPort(Protocol):
    def classify(self, query: str) -> IntentType: ...


class TextGenerationPort(Protocol):
    def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
        response_format: str | None = None,
    ) -> str: ...


class RerankerPort(Protocol):
    def rerank(
        self, query: str, units: list[RetrievedUnit], top_n: int = 10
    ) -> list[RetrievedUnit]: ...


class CapabilityInspectionPort(Protocol):
    def inspect_capabilities(self, filters: RetrievalFilters) -> Mapping[str, Any]: ...

    def inspect_dependencies(self) -> Mapping[str, Any]: ...


class VectorChannelPort(Protocol):
    def retrieve(
        self,
        query: str,
        *,
        filters: RetrievalFilters | None = None,
        top_k: int = 10,
    ) -> list[RetrievedUnit]: ...


class FullTextChannelPort(VectorChannelPort, Protocol):
    pass


class GraphChannelPort(Protocol):
    def expand(
        self,
        entry_ids: list[str],
        intent: IntentType,
        *,
        filters: RetrievalFilters | None = None,
    ) -> GraphExpansion: ...


class Clock(Protocol):
    def today(self) -> date: ...


class ClosableResource(Protocol):
    def close(self) -> None: ...


class SupportsCloseCallbacks(Protocol):
    def close_callbacks(self) -> Sequence[object]: ...
