"""Versioned dataset contract for pilot answer evaluation."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.shared.retrieval_contract import IntentType


class ReviewState(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    reviewer: str | None = None
    status: Literal["pending", "approved"]
    reviewed_at: datetime | None = None

    @model_validator(mode="after")
    def approved_review_is_attributed(self) -> "ReviewState":
        if self.status == "approved" and (
            not self.reviewer or self.reviewed_at is None
        ):
            raise ValueError("Approved review requires reviewer and reviewed_at")
        return self


class AnswerEvaluationCase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    query_id: str = Field(pattern=r"^[a-z0-9_]+$")
    query: str = Field(min_length=1)
    intent: IntentType
    expected_outcome: Literal["answered", "unsupported_capability"]
    required_capability: str | None = None
    query_date: date | None = None
    required_citation_groups: tuple[tuple[str, ...], ...] = ()
    gold_key_claims: tuple[str, ...] = ()
    expected_temporal_valid: bool | None = None
    review: ReviewState

    @model_validator(mode="after")
    def validate_expected_evidence(self) -> "AnswerEvaluationCase":
        if self.expected_outcome == "answered":
            if not self.required_citation_groups or not self.gold_key_claims:
                raise ValueError(
                    "Answered cases require citation groups and reviewed key claims"
                )
            if self.required_capability is not None:
                raise ValueError(
                    "Answered cases must not declare unavailable capability"
                )
        elif self.required_capability is None:
            raise ValueError("Unsupported cases require required_capability")
        if any(
            not group or len(group) != len(set(group))
            for group in self.required_citation_groups
        ):
            raise ValueError("Citation groups must be non-empty and unique")
        return self


class AnswerEvaluationDataset(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["answer-evaluation-dataset-v1"]
    evaluation_scope: Literal["pilot_development"]
    name: str = Field(min_length=1)
    source_retrieval_dataset: str = Field(min_length=1)
    document_ids: tuple[str, ...] = Field(min_length=1)
    review: ReviewState
    cases: tuple[AnswerEvaluationCase, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def cases_are_unique(self) -> "AnswerEvaluationDataset":
        query_ids = [case.query_id for case in self.cases]
        if len(query_ids) != len(set(query_ids)):
            raise ValueError("Answer evaluation query IDs must be unique")
        if len(self.document_ids) != len(set(self.document_ids)):
            raise ValueError("Document IDs must be unique")
        return self
