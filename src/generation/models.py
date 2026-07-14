"""Versioned DTOs for structured, grounded answer generation."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.retrieval.models import RetrievalContext


ANSWER_CONTRACT_VERSION = "answer-generation-v1"


class GenerationHistoryMessage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class AnswerGenerationRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: Literal["answer-generation-v1"] = ANSWER_CONTRACT_VERSION
    query: str = Field(min_length=1, max_length=4000)
    retrieval_context: RetrievalContext
    conversation_history: tuple[GenerationHistoryMessage, ...] = ()
    language: Literal["vi"] = "vi"

    @model_validator(mode="after")
    def validate_query_matches_retrieval(self) -> "AnswerGenerationRequest":
        if self.query != self.retrieval_context.query:
            raise ValueError("Generation query must match retrieval context query")
        return self


class AnswerClaim(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_-]+$")
    text: str = Field(min_length=1)
    citation_ids: list[str] = Field(min_length=1)

    @field_validator("citation_ids")
    @classmethod
    def citations_are_unique(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("Citation IDs must not be blank")
        if len(values) != len(set(values)):
            raise ValueError("Citation IDs must be unique within a claim")
        return values


class TemporalAssertion(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    subject_unit_id: str = Field(min_length=1)
    query_date: date
    asserted_valid: bool
    scope: Literal["unit", "document", "scoped_pilot", "corpus_complete"]


class AnswerCandidate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    claims: list[AnswerClaim]
    reasoning_path_ids: list[str] = Field(default_factory=list)
    temporal_assertions: list[TemporalAssertion] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    cannot_answer: bool
    insufficiency_reason: str | None = None

    @model_validator(mode="after")
    def validate_answer_shape(self) -> "AnswerCandidate":
        if self.cannot_answer:
            if self.claims:
                raise ValueError("cannot_answer candidate must not contain claims")
            if not self.insufficiency_reason:
                raise ValueError(
                    "cannot_answer candidate requires insufficiency_reason"
                )
        elif not self.claims:
            raise ValueError("Supported candidate requires at least one claim")
        elif self.insufficiency_reason is not None:
            raise ValueError(
                "Supported candidate must not contain insufficiency_reason"
            )
        if len(self.reasoning_path_ids) != len(set(self.reasoning_path_ids)):
            raise ValueError("reasoning_path_ids must be unique")
        return self


class ProjectedEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    unit_id: str
    label: str
    citation_label: str
    document_id: str
    article_id: str | None
    clause_id: str | None
    deep_link: str
    content_raw: str
    effective_from: date | None
    effective_to: date | None
    legal_status: str | None


class ProjectedPath(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    path_id: str
    nodes: tuple[str, ...]
    relations: tuple[str, ...]
    relation_ids: tuple[str, ...]
    description: str
    is_temporal_valid: bool


class ProjectedAnswerContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    query: str
    intent: str
    strategy: str
    temporal_source: str
    resolved_from: date | None
    resolved_to: date | None
    evidence: tuple[ProjectedEvidence, ...]
    paths: tuple[ProjectedPath, ...]
    allowed_citation_ids: tuple[str, ...]
    truncated: bool


class ProviderAnswerRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: Literal["answer-generation-v1"] = ANSWER_CONTRACT_VERSION
    system_instruction: str
    prompt: str


class AnswerCitation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    unit_id: str
    citation_label: str
    document_id: str
    article_id: str | None
    clause_id: str | None
    deep_link: str
    quoted_text: str | None = None


class AnswerReasoningPath(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    path_id: str
    nodes: tuple[str, ...]
    relations: tuple[str, ...]
    relation_ids: tuple[str, ...]
    description: str


class AnswerResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: Literal["answer-generation-v1"] = ANSWER_CONTRACT_VERSION
    retrieval_contract_version: str
    query: str
    answer_text: str
    claims: tuple[AnswerClaim, ...]
    citations: tuple[AnswerCitation, ...]
    reasoning_paths: tuple[AnswerReasoningPath, ...]
    temporal_notes: tuple[str, ...]
    cannot_answer: bool
    insufficiency_reason: str | None
    confidence: float
    provider: str | None
    model: str | None
    intent: str
    strategy: str
