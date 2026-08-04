"""Bind an unlinked semantic plan to canonical endpoints, fail-closed."""

from __future__ import annotations

from typing import TypeAlias

from pydantic import BaseModel, ConfigDict, ValidationError

from src.retrieval.execution_contract import PlanReasonCode
from src.retrieval.models import RetrievalFilters
from src.retrieval.planning.linker import (
    EndpointLinker,
    EndpointResolution,
    EndpointResolutionStatus,
    EndpointRole,
)
from src.retrieval.planning.models import (
    BoundEndpoint,
    BoundSemanticPlan,
    UnlinkedSemanticPlan,
)


class PlanBindingFailure(BaseModel):
    """Typed reason an unlinked plan could not become a bound plan."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    reason_code: PlanReasonCode
    message: str


BindingOutcome: TypeAlias = BoundSemanticPlan | PlanBindingFailure


class PlanBinder:
    """Resolve anchor and target independently into one bound plan."""

    def __init__(self, linker: EndpointLinker) -> None:
        self._linker = linker

    def bind(
        self,
        unlinked: UnlinkedSemanticPlan,
        filters: RetrievalFilters,
    ) -> BindingOutcome:
        anchor = self._linker.resolve(
            mention_text=unlinked.anchor.text,
            role=EndpointRole.ANCHOR,
            expected_label=(
                unlinked.anchor.expected_label.value
                if unlinked.anchor.expected_label is not None
                else None
            ),
            filters=filters,
        )
        anchor_failure = _binding_failure(anchor, EndpointRole.ANCHOR)
        if anchor_failure is not None:
            return anchor_failure

        target = self._linker.resolve(
            mention_text=unlinked.target.text,
            role=EndpointRole.TARGET,
            expected_label=unlinked.target_label,
            filters=filters,
        )
        target_failure = _binding_failure(target, EndpointRole.TARGET)
        if target_failure is not None:
            return target_failure

        assert anchor.bound_endpoint is not None  # narrowed by _binding_failure
        assert target.bound_endpoint is not None
        try:
            return BoundSemanticPlan(
                unlinked=unlinked,
                bound_anchor=_rebind_mention(anchor.bound_endpoint, unlinked.anchor.text),
                bound_target=_rebind_mention(target.bound_endpoint, unlinked.target.text),
            )
        except ValidationError as exc:
            return PlanBindingFailure(
                reason_code=PlanReasonCode.INVALID_PLAN,
                message=f"Bound endpoints are inconsistent with the plan: {exc}",
            )


def _binding_failure(
    resolution: EndpointResolution,
    role: EndpointRole,
) -> PlanBindingFailure | None:
    if (
        resolution.status is EndpointResolutionStatus.RESOLVED
        and resolution.bound_endpoint is not None
    ):
        return None
    reason = resolution.reason_code or (
        PlanReasonCode.UNBOUND_ANCHOR
        if role is EndpointRole.ANCHOR
        else PlanReasonCode.UNBOUND_TARGET
    )
    return PlanBindingFailure(reason_code=reason, message=resolution.message)


def _rebind_mention(endpoint: BoundEndpoint, mention_text: str) -> BoundEndpoint:
    """Keep the plan's own mention text so plan invariants hold exactly."""
    return endpoint.model_copy(update={"mention_text": mention_text})
