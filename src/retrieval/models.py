"""Internal retrieval DTOs built on the versioned shared contract."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from src.shared.retrieval_contract import (
    IntentType,
    RetrievalChannel,
    RetrievalCapability,
    RetrievalDecisionReasonCode,
    RetrievalFilters,
    RetrievalRequest,
    RetrievalStrategyType,
    TemporalSource,
)

__all__ = [
    "IntentType",
    "RetrievalChannel",
    "RetrievalCapability",
    "RetrievalDecisionReasonCode",
    "RetrievalFilters",
    "RetrievalRequest",
    "RetrievalStrategyType",
    "TemporalSource",
]


class TemporalQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    has_temporal: bool
    expression: str | None = None
    resolved_from: date | None = None
    resolved_to: date | None = None
    granularity: str | None = None
    parse_error: str | None = None
    requests_current_validity: bool = False


class RetrievedUnit(BaseModel):
    id: str
    label: Literal["Article", "Clause", "Point"]
    content_raw: str
    title: str | None = None
    document_id: str
    document_number: str | None = None
    document_title: str | None = None
    source_url: str | None = None
    article_id: str | None = None
    clause_id: str | None = None
    article_number: str | None = None
    clause_number: str | None = None
    version_family_id: str | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    legal_status: str | None = None
    vector_score: float | None = None
    bm25_score: float | None = None
    graph_score: float | None = None
    rerank_score: float | None = None
    final_score: float | None = None
    citation_label: str
    deep_link: str = ""
    retrieval_sources: list[Literal["vector", "fulltext", "graph"]] = Field(
        default_factory=list
    )


class GraphNodeRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    node_id: str
    labels: tuple[str, ...]
    effective_from: date | None = None
    effective_to: date | None = None
    legal_status: str | None = None
    citable_unit_id: str | None = None


class GraphEdge(BaseModel):
    model_config = ConfigDict(frozen=True)

    relation_id: str
    relation_type: str
    source_id: str
    target_id: str
    effective_from: date | None = None
    effective_to: date | None = None


class GraphPath(BaseModel):
    model_config = ConfigDict(frozen=True)

    nodes: tuple[GraphNodeRef, ...]
    edges: tuple[GraphEdge, ...]
    path_description: str


class GraphExpansionDiagnostics(BaseModel):
    accepted_path_count: int = 0
    temporal_rejected_path_count: int = 0
    malformed_path_count: int = 0


class GraphReasoningRequirement(BaseModel):
    model_config = ConfigDict(frozen=True)

    minimum_edges: int = Field(ge=2, le=5)
    required_relation_types: tuple[str, ...] = ()
    require_all_citable_intermediates: bool = True


class GraphExpansion(BaseModel):
    paths: list[GraphPath] = Field(default_factory=list)
    units: list[RetrievedUnit] = Field(default_factory=list)
    diagnostics: GraphExpansionDiagnostics = Field(
        default_factory=GraphExpansionDiagnostics
    )


class EvidenceItem(BaseModel):
    unit_id: str
    evidence_type: Literal["vector", "bm25", "graph", "temporal", "rerank"]
    matched_text: str | None = None
    score: float | None = None
    source_path_id: str | None = None
    is_eligible: bool = False


class CapabilitySnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    vector_article_index_available: bool = False
    vector_clause_index_available: bool = False
    fulltext_index_available: bool = False
    scoped_temporal_metadata_available: bool = False
    corpus_complete_current_validity_available: bool = False
    temporal_relations_available: bool = False
    structural_hierarchy_available: bool = False
    guides_relations_available: bool = False
    multiple_versions_available: bool = False
    definition_relations_available: bool = False
    semantic_multi_hop_graph_available: bool = False
    canonical_relation_types_available: frozenset[str] = frozenset()


class RetrievalDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    contract_version: Literal["retrieval-runtime-v2"]
    intent: IntentType
    strategy: RetrievalStrategyType
    seed_channels: tuple[RetrievalChannel, ...]
    graph_enabled: bool
    graph_policy_intent: IntentType | None
    candidate_k: int
    graph_entry_k: int
    final_k: int
    apply_temporal_filter: bool
    preserve_versions: bool
    require_temporal_point: bool
    enable_reranker: bool
    force_intent_used: bool
    temporal_source: TemporalSource
    decision_reason_code: RetrievalDecisionReasonCode
    decision_reason: str
    required_capability: RetrievalCapability | None = None


class RoutingResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision: RetrievalDecision
    temporal: TemporalQuery
    filters: RetrievalFilters


class RetrievalContext(BaseModel):
    contract_version: Literal["retrieval-runtime-v2"] = "retrieval-runtime-v2"
    query: str
    intent: IntentType
    strategy: RetrievalStrategyType = RetrievalStrategyType.FACTUAL_HYBRID
    temporal: TemporalQuery
    temporal_source: TemporalSource = TemporalSource.NONE
    decision_reason_code: RetrievalDecisionReasonCode = (
        RetrievalDecisionReasonCode.FACTUAL_DEFAULT
    )
    decision_reason: str = "Legacy context without routing decision"
    force_intent_used: bool = False
    executed_channels: list[RetrievalChannel] = Field(default_factory=list)
    filters_applied: RetrievalFilters = Field(default_factory=RetrievalFilters)
    reranker_applied: bool = False
    capability_status: Literal["supported", "no_results"] = "supported"
    reasoning_requirement: GraphReasoningRequirement | None = None
    retrieved_units: list[RetrievedUnit]
    graph_paths: list[GraphPath]
    evidence: list[EvidenceItem]
    metrics: dict[str, Any]
    retrieval_mode: Literal[
        "vector_only",
        "vector_graph",
        "fulltext_only",
        "hybrid",
        "no_results",
    ]
    confidence_penalty: bool = False
