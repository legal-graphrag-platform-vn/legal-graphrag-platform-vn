"""Authority contracts shared by planning execution and retrieval context."""

from __future__ import annotations

from enum import Enum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _non_blank_identifier(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("Identifier must not be blank")
    return normalized


class PlanExecutionStatus(str, Enum):
    SATISFIED = "satisfied"
    FAILED = "failed"


class PlanReasonCode(str, Enum):
    SATISFIED = "SATISFIED"
    INVALID_PLAN = "INVALID_PLAN"
    OUT_OF_SCOPE_PLAN_SHAPE = "OUT_OF_SCOPE_PLAN_SHAPE"
    PLANNER_UNAVAILABLE = "PLANNER_UNAVAILABLE"
    PLANNER_TIMEOUT = "PLANNER_TIMEOUT"
    UNBOUND_ANCHOR = "UNBOUND_ANCHOR"
    AMBIGUOUS_ANCHOR = "AMBIGUOUS_ANCHOR"
    UNBOUND_TARGET = "UNBOUND_TARGET"
    AMBIGUOUS_TARGET = "AMBIGUOUS_TARGET"
    NO_PATH = "NO_PATH"
    AMBIGUOUS_PATH = "AMBIGUOUS_PATH"
    PATH_BUDGET_EXCEEDED = "PATH_BUDGET_EXCEEDED"
    TEMPORAL_REJECTED = "TEMPORAL_REJECTED"
    EVIDENCE_UNLIFTABLE = "EVIDENCE_UNLIFTABLE"


class GraphReasoningRequirement(BaseModel):
    model_config = ConfigDict(frozen=True)

    minimum_edges: int = Field(ge=2, le=5)
    required_relation_types: tuple[str, ...] = ()
    require_all_citable_intermediates: bool = True


class PlanExecutionResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    plan_fingerprint: str
    satisfied_path_fingerprints: tuple[str, ...]
    bound_anchor_id: str
    bound_target_id: str
    execution_status: PlanExecutionStatus
    reason_code: PlanReasonCode
    message: str | None = None
    derived_reasoning_requirement: GraphReasoningRequirement | None = None

    _normalize_plan_fingerprint = field_validator("plan_fingerprint")(
        _non_blank_identifier
    )
    _normalize_anchor_id = field_validator("bound_anchor_id")(_non_blank_identifier)
    _normalize_target_id = field_validator("bound_target_id")(_non_blank_identifier)

    @field_validator("satisfied_path_fingerprints")
    @classmethod
    def validate_path_fingerprints(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_non_blank_identifier(value) for value in values)
        if len(normalized) != len(set(normalized)):
            raise ValueError("Satisfied path fingerprints must be unique")
        return normalized

    @model_validator(mode="after")
    def validate_execution_state(self) -> Self:
        if self.execution_status is PlanExecutionStatus.SATISFIED:
            if (
                self.reason_code is not PlanReasonCode.SATISFIED
                or len(self.satisfied_path_fingerprints) != 1
                or self.derived_reasoning_requirement is None
            ):
                raise ValueError(
                    "A satisfied execution requires reason SATISFIED, exactly one "
                    "path fingerprint, and a derived reasoning requirement"
                )
        elif (
            self.reason_code is PlanReasonCode.SATISFIED
            or self.satisfied_path_fingerprints
            or self.derived_reasoning_requirement is not None
        ):
            raise ValueError(
                "A failed execution requires a failure reason, no satisfied path "
                "fingerprints, and no derived reasoning requirement"
            )
        return self
