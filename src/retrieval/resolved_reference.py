"""Server-owned canonical reference handoff into retrieval execution.

These models are deliberately absent from the public ``RetrievalRequest``.
Only the conversation resolver may construct them; clients cannot inject graph
node IDs through the chat or query APIs.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ResolutionMethod(str, Enum):
    EXACT_STRUCTURAL_LOOKUP = "EXACT_STRUCTURAL_LOOKUP"
    GROUNDED_HISTORY_FOCUS = "GROUNDED_HISTORY_FOCUS"


class ReferenceSource(str, Enum):
    CURRENT_MESSAGE = "CURRENT_MESSAGE"
    GROUNDED_HISTORY = "GROUNDED_HISTORY"
    PENDING_CLARIFICATION = "PENDING_CLARIFICATION"


class RelationGoal(str, Enum):
    REFERS_TO = "REFERS_TO"
    DEFINES = "DEFINES"
    REGULATES = "REGULATES"
    GUIDES = "GUIDES"


class ResolvedReference(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    mention: str = Field(min_length=1, max_length=4000)
    node_id: str = Field(min_length=1)
    node_type: Literal["Document", "Article", "Clause", "Point"]
    label: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    resolution_method: ResolutionMethod
    source: ReferenceSource


class RetrievalExecutionContext(BaseModel):
    """Internal execution hints derived from deterministic server state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    resolved_references: tuple[ResolvedReference, ...] = Field(
        default=(), max_length=5
    )
    relation_goal: RelationGoal | None = None

    @model_validator(mode="after")
    def validate_relation_goal(self) -> "RetrievalExecutionContext":
        if self.relation_goal is not None and not self.resolved_references:
            raise ValueError("A relation goal requires at least one resolved reference")
        return self

    @property
    def anchor_node_ids(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(reference.node_id for reference in self.resolved_references)
        )


EMPTY_RETRIEVAL_EXECUTION_CONTEXT = RetrievalExecutionContext()
