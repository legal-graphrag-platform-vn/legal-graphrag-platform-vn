from __future__ import annotations

from dataclasses import dataclass

from src.retrieval.execution_contract import PlanReasonCode
from src.retrieval.models import RetrievalFilters
from src.retrieval.planning.binder import PlanBinder, PlanBindingFailure
from src.retrieval.planning.linker import (
    EndpointResolutionStatus,
    EndpointRole,
)
from src.retrieval.planning.models import (
    AnchorMention,
    BoundEndpoint,
    BoundSemanticPlan,
    PathStepConstraint,
    TargetMention,
    UnlinkedSemanticPlan,
)


@dataclass
class _FakeResolution:
    status: EndpointResolutionStatus
    message: str
    bound_endpoint: BoundEndpoint | None = None
    reason_code: PlanReasonCode | None = None


class _FakeLinker:
    """Return canned resolutions in call order (anchor then target)."""

    def __init__(self, *resolutions: _FakeResolution) -> None:
        self._queue = list(resolutions)
        self.calls: list[tuple[str, str, str | None]] = []

    def resolve(self, *, mention_text, role, expected_label, filters):
        self.calls.append((mention_text, EndpointRole(role).value, expected_label))
        return self._queue.pop(0)


def _plan() -> UnlinkedSemanticPlan:
    return UnlinkedSemanticPlan(
        anchor=AnchorMention(text="Khoản 3 Điều 145", expected_label="Clause"),
        target=TargetMention(text="điều kiện của lần họp thứ nhất"),
        steps=(
            PathStepConstraint(
                relation="REFERS_TO", direction="outgoing", next_label="Clause"
            ),
            PathStepConstraint(
                relation="REFERS_TO", direction="outgoing", next_label="Clause"
            ),
        ),
    )


def _resolved(node_id: str) -> _FakeResolution:
    return _FakeResolution(
        status=EndpointResolutionStatus.RESOLVED,
        message="resolved",
        bound_endpoint=BoundEndpoint(
            mention_text="ignored-normalized-text",
            node_id=node_id,
            label="Clause",
            resolution_method="STRUCTURAL",
        ),
    )


def _filters() -> RetrievalFilters:
    return RetrievalFilters(document_ids=["ldn_2020"])


def test_bind_success_uses_plan_mention_text_and_both_endpoints() -> None:
    plan = _plan()
    linker = _FakeLinker(_resolved("anchor_node"), _resolved("target_node"))

    outcome = PlanBinder(linker).bind(plan, _filters())

    assert isinstance(outcome, BoundSemanticPlan)
    assert outcome.bound_anchor.node_id == "anchor_node"
    assert outcome.bound_target.node_id == "target_node"
    # mention text comes from the plan, not the resolver's normalized text
    assert outcome.bound_anchor.mention_text == plan.anchor.text
    assert outcome.bound_target.mention_text == plan.target.text
    # anchor resolved with expected label, target derives label from final step
    assert linker.calls[0] == (plan.anchor.text, "anchor", "Clause")
    assert linker.calls[1] == (plan.target.text, "target", "Clause")


def test_unbound_anchor_short_circuits_before_target() -> None:
    linker = _FakeLinker(
        _FakeResolution(
            status=EndpointResolutionStatus.UNBOUND,
            message="no anchor",
            reason_code=PlanReasonCode.UNBOUND_ANCHOR,
        ),
    )

    outcome = PlanBinder(linker).bind(_plan(), _filters())

    assert isinstance(outcome, PlanBindingFailure)
    assert outcome.reason_code is PlanReasonCode.UNBOUND_ANCHOR
    assert len(linker.calls) == 1  # target never resolved


def test_ambiguous_target_returns_target_reason() -> None:
    linker = _FakeLinker(
        _resolved("anchor_node"),
        _FakeResolution(
            status=EndpointResolutionStatus.AMBIGUOUS,
            message="two targets",
            reason_code=PlanReasonCode.AMBIGUOUS_TARGET,
        ),
    )

    outcome = PlanBinder(linker).bind(_plan(), _filters())

    assert isinstance(outcome, PlanBindingFailure)
    assert outcome.reason_code is PlanReasonCode.AMBIGUOUS_TARGET
    assert len(linker.calls) == 2


def test_inconsistent_bound_label_becomes_invalid_plan() -> None:
    mismatched = _FakeResolution(
        status=EndpointResolutionStatus.RESOLVED,
        message="resolved",
        bound_endpoint=BoundEndpoint(
            mention_text="x",
            node_id="anchor_node",
            label="Article",  # plan expects a Clause anchor
            resolution_method="STRUCTURAL",
        ),
    )
    linker = _FakeLinker(mismatched, _resolved("target_node"))

    outcome = PlanBinder(linker).bind(_plan(), _filters())

    assert isinstance(outcome, PlanBindingFailure)
    assert outcome.reason_code is PlanReasonCode.INVALID_PLAN
