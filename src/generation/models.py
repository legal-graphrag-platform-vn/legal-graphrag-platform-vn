"""Versioned DTOs for structured, grounded answer generation."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.retrieval.models import RetrievalContext


ANSWER_CONTRACT_VERSION = "answer-generation-v2"
PROJECTION_CONTRACT_VERSION = "answer-context-v2"


class GenerationHistoryMessage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)


class AnswerCompositionOperand(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    operand_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_-]+$")
    query: str = Field(min_length=1, max_length=4000)
    evidence_unit_ids: tuple[str, ...] = ()

    @field_validator("evidence_unit_ids")
    @classmethod
    def evidence_ids_are_valid(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if any(not value.strip() for value in values):
            raise ValueError("Composition evidence IDs must not be blank")
        if len(values) != len(set(values)):
            raise ValueError("Composition evidence IDs must be unique per operand")
        return values


class AnswerCompositionPlan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: Literal["comparison"] = "comparison"
    operands: tuple[AnswerCompositionOperand, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def operand_ids_are_unique(self) -> "AnswerCompositionPlan":
        operand_ids = [operand.operand_id for operand in self.operands]
        if len(operand_ids) != len(set(operand_ids)):
            raise ValueError("Composition operand IDs must be unique")
        return self


class AnswerGenerationRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: Literal["answer-generation-v2"] = ANSWER_CONTRACT_VERSION
    query: str = Field(min_length=1, max_length=4000)
    retrieval_context: RetrievalContext
    conversation_history: tuple[GenerationHistoryMessage, ...] = ()
    language: Literal["vi"] = "vi"
    composition_plan: AnswerCompositionPlan | None = None

    @model_validator(mode="after")
    def validate_query_matches_retrieval(self) -> "AnswerGenerationRequest":
        if self.query != self.retrieval_context.query:
            raise ValueError("Generation query must match retrieval context query")
        if self.composition_plan is not None:
            retrieved_ids = {unit.id for unit in self.retrieval_context.retrieved_units}
            assigned_ids = {
                unit_id
                for operand in self.composition_plan.operands
                for unit_id in operand.evidence_unit_ids
            }
            if not assigned_ids.issubset(retrieved_ids):
                raise ValueError(
                    "Composition evidence IDs must exist in retrieval context"
                )
        return self


class StatementCitation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    citation_id: str = Field(min_length=1)
    quoted_text: str = Field(
        min_length=1,
        description=(
            "Verbatim substring copied from the cited evidence's content_raw "
            "that directly supports this statement. Must not be paraphrased."
        ),
    )


class GroundedStatement(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    statement_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_-]+$")
    text: str = Field(min_length=1)
    citations: list[StatementCitation] = Field(min_length=1)
    reasoning_path_ids: list[str] = Field(default_factory=list)
    temporal_assertion_ids: list[str] = Field(default_factory=list)

    @field_validator("citations")
    @classmethod
    def citations_are_unique(
        cls, values: list[StatementCitation]
    ) -> list[StatementCitation]:
        citation_ids = [item.citation_id for item in values]
        if len(citation_ids) != len(set(citation_ids)):
            raise ValueError("Statement citation IDs must be unique")
        return values

    @field_validator("reasoning_path_ids", "temporal_assertion_ids")
    @classmethod
    def linked_ids_are_unique(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("Statement linkage IDs must not be blank")
        if len(values) != len(set(values)):
            raise ValueError("Statement linkage IDs must be unique")
        return values


class AnswerParagraph(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    statements: list[GroundedStatement] = Field(min_length=1)


class AnswerBlock(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    paragraphs: list[AnswerParagraph] = Field(min_length=1)


class AnswerSection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    heading: str = Field(min_length=1)
    paragraphs: list[AnswerParagraph] = Field(min_length=1)


class TemporalAssertion(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    assertion_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_-]+$")
    subject_unit_id: str = Field(min_length=1)
    query_date: date
    asserted_valid: bool
    scope: Literal["unit", "document", "scoped_pilot", "corpus_complete"]


class AnswerCandidate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    direct_answer: AnswerBlock | None = None
    sections: list[AnswerSection] = Field(default_factory=list)
    caveats: list[AnswerParagraph] = Field(default_factory=list)
    temporal_assertions: list[TemporalAssertion] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    cannot_answer: bool
    insufficiency_reason: str | None = None

    @model_validator(mode="after")
    def validate_answer_shape(self) -> "AnswerCandidate":
        if self.cannot_answer:
            if self.direct_answer is not None or self.sections or self.caveats:
                raise ValueError("cannot_answer candidate must not contain statements")
            if self.temporal_assertions:
                raise ValueError(
                    "cannot_answer candidate must not contain temporal assertions"
                )
            if not self.insufficiency_reason:
                raise ValueError(
                    "cannot_answer candidate requires insufficiency_reason"
                )
            return self

        if self.direct_answer is None:
            raise ValueError("Supported candidate requires a direct_answer")
        if self.insufficiency_reason is not None:
            raise ValueError(
                "Supported candidate must not contain insufficiency_reason"
            )

        statement_ids = [
            statement.statement_id for statement in iter_candidate_statements(self)
        ]
        if len(statement_ids) != len(set(statement_ids)):
            raise ValueError("statement_id must be unique across the answer")
        assertion_ids = [item.assertion_id for item in self.temporal_assertions]
        if len(assertion_ids) != len(set(assertion_ids)):
            raise ValueError("assertion_id must be unique")
        return self


def iter_candidate_statements(
    candidate: AnswerCandidate,
) -> Iterator[GroundedStatement]:
    if candidate.direct_answer is not None:
        for paragraph in candidate.direct_answer.paragraphs:
            yield from paragraph.statements
    for section in candidate.sections:
        for paragraph in section.paragraphs:
            yield from paragraph.statements
    for paragraph in candidate.caveats:
        yield from paragraph.statements


class OmittedEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    unit_id: str = Field(min_length=1)
    reason: Literal[
        "hierarchical_duplicate",
        "content_duplicate",
        "context_budget_exceeded",
        "superseded_by_more_specific_unit",
    ]
    retained_unit_id: str | None = None


class ContextBudgetPlan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    total_chars: int = Field(ge=0)
    fixed_overhead_chars: int = Field(ge=0)
    evidence_budget_chars: int = Field(ge=0)
    safety_reserve_chars: int = Field(ge=0)
    used_evidence_chars: int = Field(ge=0)


class LegalEvidenceBlock(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    unit_id: str = Field(min_length=1)
    label: Literal["Appendix", "Article", "Clause", "Point"]
    citation_label: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    document_number: str | None
    document_title: str | None
    version_family_id: str | None
    article_id: str | None
    clause_id: str | None
    deep_link: str = Field(min_length=1)
    content_raw: str = Field(min_length=1)
    effective_from: date | None
    effective_to: date | None
    legal_status: str | None


class ProjectedCitationEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    relation_id: str
    citation_text: str | None = None
    citation_type: str | None = None
    extraction_method: str | None = None


class ProjectedGraphEdge(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    relation_id: str
    relation_type: str
    source_id: str
    target_id: str
    effective_from: date | None
    effective_to: date | None
    citation_evidence: tuple[ProjectedCitationEvidence, ...] = ()


class ProjectedPathBlock(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    path_id: str
    nodes: tuple[str, ...]
    edges: tuple[ProjectedGraphEdge, ...]
    description: str


class EvidenceRegistryEntry(LegalEvidenceBlock):
    pass


class EvidenceRegistry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    entries: tuple[EvidenceRegistryEntry, ...]
    allowed_citation_ids: tuple[str, ...]
    allowed_path_ids: tuple[str, ...]

    @model_validator(mode="after")
    def validate_registry(self) -> "EvidenceRegistry":
        entry_ids = tuple(entry.unit_id for entry in self.entries)
        if entry_ids != self.allowed_citation_ids:
            raise ValueError("Registry entries must equal allowed citation IDs")
        if len(entry_ids) != len(set(entry_ids)):
            raise ValueError("Registry citation IDs must be unique")
        if len(self.allowed_path_ids) != len(set(self.allowed_path_ids)):
            raise ValueError("Registry path IDs must be unique")
        return self


class ProjectedAnswerContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    query: str
    intent: str
    strategy: str
    temporal_source: str
    resolved_from: date | None
    resolved_to: date | None
    relation_goal: str | None = None
    anchor_node_ids: tuple[str, ...] = ()
    composition_plan: AnswerCompositionPlan | None = None
    evidence: tuple[LegalEvidenceBlock, ...]
    paths: tuple[ProjectedPathBlock, ...]
    admitted_bundle_ids: tuple[str, ...]
    selected_unit_ids: tuple[str, ...]
    omitted_evidence: tuple[OmittedEvidence, ...]
    budget: ContextBudgetPlan
    truncated: bool
    projection_contract_version: Literal["answer-context-v2"] = (
        PROJECTION_CONTRACT_VERSION
    )

    @model_validator(mode="after")
    def validate_projection(self) -> "ProjectedAnswerContext":
        evidence_ids = tuple(item.unit_id for item in self.evidence)
        if evidence_ids != self.selected_unit_ids:
            raise ValueError("selected_unit_ids must match projected evidence")
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("Projected evidence IDs must be unique")
        if len(self.admitted_bundle_ids) != len(set(self.admitted_bundle_ids)):
            raise ValueError("Admitted bundle IDs must be unique")
        if self.composition_plan is not None:
            selected_ids = set(self.selected_unit_ids)
            for operand in self.composition_plan.operands:
                if not operand.evidence_unit_ids:
                    raise ValueError(
                        "Projected composition operands require selected evidence"
                    )
                if not set(operand.evidence_unit_ids).issubset(selected_ids):
                    raise ValueError("Projected composition evidence must be selected")
        budget_omissions = any(
            item.reason == "context_budget_exceeded" for item in self.omitted_evidence
        )
        if self.truncated != budget_omissions:
            raise ValueError("truncated must reflect context budget omissions")
        return self


class ProviderAnswerRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: Literal["answer-generation-v2"] = ANSWER_CONTRACT_VERSION
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
    edges: tuple[ProjectedGraphEdge, ...]
    description: str


class AnswerResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_version: Literal["answer-generation-v2"] = ANSWER_CONTRACT_VERSION
    retrieval_contract_version: str
    query: str
    answer_text: str
    direct_answer: AnswerBlock | None
    sections: tuple[AnswerSection, ...]
    caveats: tuple[AnswerParagraph, ...]
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
