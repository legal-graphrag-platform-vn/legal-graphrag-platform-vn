"""Immutable contracts for exact query-specific graph planning."""

from __future__ import annotations

from enum import Enum
from math import isfinite
from typing import Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from src.retrieval.execution_contract import (
    PlanExecutionResult as PlanExecutionResult,
    PlanExecutionStatus as PlanExecutionStatus,
    PlanReasonCode as PlanReasonCode,
)
from src.retrieval.planning.patterns import (
    MAX_PLAN_DEPTH,
    MIN_PLAN_DEPTH,
    QUERY_ANCHOR_LABELS,
    QUERY_TARGET_LABELS,
    QUERY_TRAVERSAL_LABELS,
    QueryAnchorLabel,
    QueryDirection,
    QueryPlannableRelation,
    QueryTraversalLabel,
    validate_directed_step,
)


def _normalized_non_blank_text(value: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError("Mention text must not be blank")
    return normalized


def _normalized_non_blank_identifier(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("Identifier must not be blank")
    return normalized


class EndpointResolutionMethod(str, Enum):
    STRUCTURAL = "STRUCTURAL"
    FULLTEXT = "FULLTEXT"
    VECTOR_RRF = "VECTOR_RRF"


class _ImmutableContract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AnchorMention(_ImmutableContract):
    text: str
    expected_label: QueryAnchorLabel | None = None

    _normalize_text = field_validator("text")(_normalized_non_blank_text)


class TargetMention(_ImmutableContract):
    text: str

    _normalize_text = field_validator("text")(_normalized_non_blank_text)


class PathStepConstraint(_ImmutableContract):
    relation: QueryPlannableRelation
    direction: QueryDirection
    next_label: QueryTraversalLabel


class UnlinkedSemanticPlan(_ImmutableContract):
    anchor: AnchorMention
    target: TargetMention
    steps: tuple[PathStepConstraint, ...]

    @model_validator(mode="after")
    def validate_plan_shape(self) -> Self:
        depth = len(self.steps)
        if not MIN_PLAN_DEPTH <= depth <= MAX_PLAN_DEPTH:
            raise ValueError("Query plan depth must be between 2 and 3")

        for index, step in enumerate(self.steps[:-1], start=1):
            if step.next_label.value not in QUERY_TRAVERSAL_LABELS:
                raise ValueError(f"Step {index} has an unsupported intermediate label")
        if self.steps[-1].next_label.value not in QUERY_TARGET_LABELS:
            raise ValueError("Final step has an unsupported target label")

        current_labels = (
            {self.anchor.expected_label.value}
            if self.anchor.expected_label is not None
            else set(QUERY_ANCHOR_LABELS)
        )
        for index, step in enumerate(self.steps, start=1):
            errors = []
            for current_label in sorted(current_labels):
                try:
                    validate_directed_step(
                        current_label=current_label,
                        relation=step.relation.value,
                        direction=step.direction,
                        next_label=step.next_label.value,
                    )
                except ValueError as exc:
                    errors.append(str(exc))
                else:
                    break
            else:
                raise ValueError(
                    f"Step {index} has an invalid directed ontology pattern: "
                    + "; ".join(errors)
                )
            current_labels = {step.next_label.value}
        return self

    @property
    def target_label(self) -> str:
        return self.steps[-1].next_label.value


class BoundEndpoint(_ImmutableContract):
    mention_text: str
    node_id: str
    label: QueryTraversalLabel
    resolution_method: EndpointResolutionMethod
    score: float | None = None

    _normalize_mention = field_validator("mention_text")(_normalized_non_blank_text)
    _normalize_node_id = field_validator("node_id")(_normalized_non_blank_identifier)

    @field_validator("score")
    @classmethod
    def validate_finite_score(cls, value: float | None) -> float | None:
        if value is not None and not isfinite(value):
            raise ValueError("Endpoint resolution score must be finite")
        return value


class BoundSemanticPlan(_ImmutableContract):
    unlinked: UnlinkedSemanticPlan
    bound_anchor: BoundEndpoint
    bound_target: BoundEndpoint

    @model_validator(mode="after")
    def validate_bound_endpoints(self) -> Self:
        anchor_label = self.bound_anchor.label.value
        target_label = self.bound_target.label.value
        if anchor_label not in QUERY_ANCHOR_LABELS:
            raise ValueError("Bound anchor label is not query-anchor eligible")
        if (
            self.unlinked.anchor.expected_label is not None
            and anchor_label != self.unlinked.anchor.expected_label.value
        ):
            raise ValueError("Bound anchor label differs from expected anchor label")
        if target_label != self.unlinked.target_label:
            raise ValueError("Bound target label differs from final target label")
        if self.bound_anchor.mention_text != self.unlinked.anchor.text:
            raise ValueError("Bound anchor mention differs from the unlinked plan")
        if self.bound_target.mention_text != self.unlinked.target.text:
            raise ValueError("Bound target mention differs from the unlinked plan")

        current_label = anchor_label
        for step in self.unlinked.steps:
            validate_directed_step(
                current_label=current_label,
                relation=step.relation.value,
                direction=step.direction,
                next_label=step.next_label.value,
            )
            current_label = step.next_label.value
        return self
