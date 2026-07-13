"""Versioned public contracts shared by retrieval and infrastructure adapters."""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


RETRIEVAL_CONTRACT_VERSION = "retrieval-runtime-v1"


class IntentType(str, Enum):
    FACTUAL = "factual"
    VALIDITY = "validity"
    HIERARCHY = "hierarchy"
    COMPARISON = "comparison"
    DEFINITION = "definition"
    MULTI_HOP = "multi_hop"


class RetrievalChannel(str, Enum):
    VECTOR = "vector"
    FULLTEXT = "fulltext"
    GRAPH = "graph"


class RetrievalStrategyType(str, Enum):
    FACTUAL_HYBRID = "factual_hybrid"
    DEFINITION_GRAPH = "definition_graph"
    VALIDITY_TEMPORAL = "validity_temporal"
    HIERARCHY_GRAPH = "hierarchy_graph"
    COMPARISON_TEMPORAL = "comparison_temporal"
    MULTI_HOP_HYBRID = "multi_hop_hybrid"


class RetrievalCapability(str, Enum):
    HYBRID_SEED_AND_SEMANTIC_GRAPH = "hybrid_seed_and_semantic_graph"
    LEXICAL_DEFINITION = "lexical_definition"
    SEMANTIC_MULTI_HOP_GRAPH = "semantic_multi_hop_graph"
    SCOPED_TEMPORAL_METADATA = "scoped_temporal_metadata"
    CORPUS_COMPLETE_CURRENT_VALIDITY = "corpus_complete_current_validity"
    VERSION_CHAIN_VALIDITY = "version_chain_validity"
    STRUCTURAL_HIERARCHY = "structural_hierarchy"
    GUIDES_RELATIONS = "guides_relations"
    MULTIPLE_VERSIONS = "multiple_versions"


class TemporalSource(str, Enum):
    NONE = "none"
    REQUEST = "request"
    QUERY_EXPRESSION = "query_expression"
    INJECTED_CURRENT_DATE = "injected_current_date"


class RetrievalDecisionReasonCode(str, Enum):
    FACTUAL_DEFAULT = "FACTUAL_DEFAULT"
    DEFINITION_EXPLICIT = "DEFINITION_EXPLICIT"
    VALIDITY_EXPLICIT_DATE = "VALIDITY_EXPLICIT_DATE"
    VALIDITY_CURRENT_DATE = "VALIDITY_CURRENT_DATE"
    HIERARCHY_EXPLICIT = "HIERARCHY_EXPLICIT"
    COMPARISON_EXPLICIT = "COMPARISON_EXPLICIT"
    MULTI_HOP_EXPLICIT = "MULTI_HOP_EXPLICIT"
    FORCED_INTENT = "FORCED_INTENT"


class RetrievalFilters(BaseModel):
    model_config = ConfigDict(frozen=True)

    document_ids: list[str] = Field(default_factory=list)
    doc_types: list[str] = Field(default_factory=list)
    legal_statuses: list[str] = Field(default_factory=list)
    query_date: date | None = None

    @field_validator("document_ids", "doc_types", "legal_statuses")
    @classmethod
    def validate_filter_values(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("Retrieval filter values must not be blank")
        if len(normalized) != len(set(normalized)):
            raise ValueError("Retrieval filter values must be unique")
        return normalized


class RetrievalRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    contract_version: Literal["retrieval-runtime-v1"] = RETRIEVAL_CONTRACT_VERSION
    query: str = Field(min_length=1, max_length=4000)
    filters: RetrievalFilters = Field(default_factory=RetrievalFilters)
    top_k: int | None = Field(default=None, ge=1, le=200)
    final_k: int | None = Field(default=None, ge=1, le=200)
    force_intent: IntentType | None = None
    enable_reranker: bool | None = None

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Retrieval query must not be blank")
        return normalized
