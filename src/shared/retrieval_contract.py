"""Versioned public contracts shared by retrieval and infrastructure adapters."""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


RETRIEVAL_CONTRACT_VERSION = "retrieval-runtime-v2"

QUERY_PROCESSING_CONTRACT_VERSION = "query-processing-v1"


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
    INTENT_CLASSIFIER_LLM = "INTENT_CLASSIFIER_LLM"


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

    contract_version: Literal["retrieval-runtime-v2"] = RETRIEVAL_CONTRACT_VERSION
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


# ---------------------------------------------------------------------------
# Query-processing contract (upstream of retrieval)
#
# The query processor resolves conversation context, rewrites a standalone
# query, decomposes it into sub-queries and assigns a plan. Its output is the
# five-field JSON contract mirrored by ``experiments/legal-query-processor``.
# ---------------------------------------------------------------------------


class ProcessingStatus(str, Enum):
    READY = "ready"
    NEEDS_CLARIFICATION = "needs_clarification"


class PlanType(str, Enum):
    SINGLE = "single"
    PARALLEL = "parallel"
    COMPARISON = "comparison"
    MULTI_HOP = "multi_hop"


class SubqueryIntent(str, Enum):
    """The four intents a sub-query may carry (subset of ``IntentType``)."""

    FACTUAL = "factual"
    DEFINITION = "definition"
    VALIDITY = "validity"
    HIERARCHY = "hierarchy"


# Backward-compatible bridge from a sub-query intent to the router's IntentType.
_SUBQUERY_INTENT_TO_INTENT: dict["SubqueryIntent", IntentType] = {
    SubqueryIntent.FACTUAL: IntentType.FACTUAL,
    SubqueryIntent.DEFINITION: IntentType.DEFINITION,
    SubqueryIntent.VALIDITY: IntentType.VALIDITY,
    SubqueryIntent.HIERARCHY: IntentType.HIERARCHY,
}


class SubqueryDTO(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    intent: SubqueryIntent
    depends_on: list[str] = Field(default_factory=list)

    @field_validator("id", "query")
    @classmethod
    def validate_non_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Subquery id and query must not be blank")
        return normalized

    @field_validator("depends_on")
    @classmethod
    def validate_dependencies(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("depends_on entries must not be blank")
        if len(normalized) != len(set(normalized)):
            raise ValueError("depends_on entries must be unique")
        return normalized


class QueryProcessingResult(BaseModel):
    """The five-field query-processing contract.

    Invariants (mirrored from the fine-tuning system prompt):
    - ``ready``: standalone_query and plan_type are set, subqueries is non-empty,
      clarification_question is null.
    - ``needs_clarification``: standalone_query and plan_type are null,
      subqueries is empty, clarification_question is a non-empty question.
    - ``depends_on`` only references sub-queries that appear earlier in the list.
    """

    model_config = ConfigDict(frozen=True)

    status: ProcessingStatus
    standalone_query: str | None = None
    plan_type: PlanType | None = None
    subqueries: list[SubqueryDTO] = Field(default_factory=list)
    clarification_question: str | None = None

    @model_validator(mode="after")
    def validate_contract(self) -> "QueryProcessingResult":
        if self.status is ProcessingStatus.NEEDS_CLARIFICATION:
            if self.standalone_query is not None or self.plan_type is not None:
                raise ValueError(
                    "needs_clarification must have null standalone_query and plan_type"
                )
            if self.subqueries:
                raise ValueError("needs_clarification must have empty subqueries")
            if not (self.clarification_question and self.clarification_question.strip()):
                raise ValueError(
                    "needs_clarification requires a clarification_question"
                )
        else:  # ProcessingStatus.READY
            if not (self.standalone_query and self.standalone_query.strip()):
                raise ValueError("ready requires a non-empty standalone_query")
            if self.plan_type is None:
                raise ValueError("ready requires a plan_type")
            if not self.subqueries:
                raise ValueError("ready requires at least one subquery")
            if self.clarification_question is not None:
                raise ValueError("ready must have null clarification_question")

        seen: set[str] = set()
        for subquery in self.subqueries:
            if subquery.id in seen:
                raise ValueError(f"Duplicate subquery id: {subquery.id}")
            for dependency in subquery.depends_on:
                if dependency not in seen:
                    raise ValueError(
                        f"Subquery {subquery.id} depends_on '{dependency}' "
                        "which is not a preceding subquery"
                    )
            seen.add(subquery.id)
        return self

    def primary_intent(self) -> IntentType:
        """Map the plan to a single router ``IntentType`` (backward compat).

        ``comparison`` and ``multi_hop`` map to their dedicated ``IntentType``
        members; ``single``/``parallel`` fall back to the first sub-query intent.
        """
        if self.status is not ProcessingStatus.READY:
            raise ValueError("primary_intent is only defined for a ready result")
        if self.plan_type is PlanType.COMPARISON:
            return IntentType.COMPARISON
        if self.plan_type is PlanType.MULTI_HOP:
            return IntentType.MULTI_HOP
        return _SUBQUERY_INTENT_TO_INTENT[self.subqueries[0].intent]
