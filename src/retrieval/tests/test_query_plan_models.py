from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from src.retrieval.models import GraphReasoningRequirement
from src.retrieval.planning.models import (
    AnchorMention,
    BoundEndpoint,
    BoundSemanticPlan,
    PathStepConstraint,
    PlanExecutionResult,
    PlanReasonCode,
    TargetMention,
    UnlinkedSemanticPlan,
)
from src.shared.ontology.contract import (
    LEGACY_RELATION_ALIASES,
    PHASE1_RELATION_ENUM,
    RUNTIME_ONLY_LABELS,
)


def _depth_two_plan() -> UnlinkedSemanticPlan:
    return UnlinkedSemanticPlan(
        anchor=AnchorMention(text="  Khoản 3 Điều 145  ", expected_label="Clause"),
        target=TargetMention(text="  điều kiện của lần họp thứ nhất  "),
        steps=(
            PathStepConstraint(
                relation="REFERS_TO",
                direction="outgoing",
                next_label="Clause",
            ),
            PathStepConstraint(
                relation="REFERS_TO",
                direction="outgoing",
                next_label="Clause",
            ),
        ),
    )


def test_unlinked_plan_normalizes_mentions_and_derives_target_label() -> None:
    plan = _depth_two_plan()

    assert plan.anchor.text == "Khoản 3 Điều 145"
    assert plan.target.text == "điều kiện của lần họp thứ nhất"
    assert plan.target_label == "Clause"
    assert plan.model_dump(mode="json").keys() == {"anchor", "target", "steps"}


def test_planning_contracts_are_immutable() -> None:
    plan = _depth_two_plan()

    with pytest.raises(ValidationError, match="frozen"):
        plan.anchor.text = "Điều khác"
    with pytest.raises(ValidationError, match="frozen"):
        plan.steps = ()


def test_unlinked_plan_accepts_depth_three_and_incoming_steps() -> None:
    plan = UnlinkedSemanticPlan(
        anchor=AnchorMention(text="Khoản 2 Điều 5", expected_label="Clause"),
        target=TargetMention(text="khái niệm được định nghĩa"),
        steps=(
            PathStepConstraint(
                relation="CONTAINS", direction="incoming", next_label="Article"
            ),
            PathStepConstraint(
                relation="CONTAINS", direction="incoming", next_label="Document"
            ),
            PathStepConstraint(
                relation="CONTAINS", direction="outgoing", next_label="Article"
            ),
        ),
    )

    assert len(plan.steps) == 3
    assert plan.target_label == "Article"


@pytest.mark.parametrize("depth", [1, 4])
def test_unlinked_plan_rejects_depth_outside_v1(depth: int) -> None:
    steps = tuple(
        PathStepConstraint(
            relation="REFERS_TO", direction="outgoing", next_label="Clause"
        )
        for _ in range(depth)
    )

    with pytest.raises(ValidationError, match="2 and 3"):
        UnlinkedSemanticPlan(
            anchor=AnchorMention(text="Khoản 1 Điều 1"),
            target=TargetMention(text="Khoản đích"),
            steps=steps,
        )


@pytest.mark.parametrize("mention_type", [AnchorMention, TargetMention])
def test_mentions_reject_blank_text(mention_type: type) -> None:
    with pytest.raises(ValidationError, match="must not be blank"):
        mention_type(text=" \t ")


def test_unlinked_plan_rejects_node_ids_and_unknown_fields() -> None:
    payload = _depth_two_plan().model_dump(mode="json")
    payload["anchor"]["node_id"] = "ldn_2020_art145_cl3"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        UnlinkedSemanticPlan.model_validate(payload)


@pytest.mark.parametrize(
    "step",
    [
        {"relation": "REFERENCES", "direction": "outgoing", "next_label": "Clause"},
        {
            "relation": "HAS_EXCEPTION",
            "direction": "outgoing",
            "next_label": "Exception",
        },
        {"relation": "CONTAINS", "direction": "incoming", "next_label": "Clause"},
        {"relation": "REFERS_TO", "direction": "sideways", "next_label": "Clause"},
    ],
)
def test_unlinked_plan_rejects_invalid_relation_label_or_direction(step: dict) -> None:
    payload = _depth_two_plan().model_dump(mode="json")
    payload["steps"][0] = step

    with pytest.raises(ValidationError):
        UnlinkedSemanticPlan.model_validate(payload)


def test_unlinked_plan_rejects_wrong_anchor_and_final_label_roles() -> None:
    with pytest.raises(ValidationError):
        AnchorMention(text="Quốc hội", expected_label="Issuer")

    with pytest.raises(ValidationError, match="Final"):
        UnlinkedSemanticPlan(
            anchor=AnchorMention(text="Điều 1", expected_label="Article"),
            target=TargetMention(text="đích"),
            steps=(
                PathStepConstraint(
                    relation="CONTAINS", direction="incoming", next_label="Document"
                ),
                PathStepConstraint(
                    relation="ISSUED_BY", direction="outgoing", next_label="Issuer"
                ),
            ),
        )


def test_bound_plan_requires_unique_matching_endpoints() -> None:
    plan = _depth_two_plan()
    bound = BoundSemanticPlan(
        unlinked=plan,
        bound_anchor=BoundEndpoint(
            mention_text=plan.anchor.text,
            node_id="ldn_2020_art145_cl3",
            label="Clause",
            resolution_method="STRUCTURAL",
        ),
        bound_target=BoundEndpoint(
            mention_text=plan.target.text,
            node_id="ldn_2020_art145_cl1",
            label="Clause",
            resolution_method="VECTOR_RRF",
            score=0.91,
        ),
    )

    assert bound.bound_anchor.node_id == "ldn_2020_art145_cl3"
    assert bound.bound_target.node_id == "ldn_2020_art145_cl1"


def test_bound_plan_rejects_candidate_lists() -> None:
    plan = _depth_two_plan()
    payload = {
        "unlinked": plan.model_dump(mode="json"),
        "bound_anchor": {
            "mention_text": plan.anchor.text,
            "node_id": "ldn_2020_art145_cl3",
            "label": "Clause",
            "resolution_method": "STRUCTURAL",
            "candidates": ["ldn_2020_art145_cl3"],
        },
        "bound_target": {
            "mention_text": plan.target.text,
            "node_id": "ldn_2020_art145_cl1",
            "label": "Clause",
            "resolution_method": "FULLTEXT",
        },
    }

    with pytest.raises(ValidationError) as exc_info:
        BoundSemanticPlan.model_validate(payload)

    assert "Extra inputs are not permitted" in str(exc_info.value)


def test_bound_plan_rejects_target_label_mismatch() -> None:
    plan = _depth_two_plan()

    with pytest.raises(ValidationError, match="target label"):
        BoundSemanticPlan(
            unlinked=plan,
            bound_anchor=BoundEndpoint(
                mention_text=plan.anchor.text,
                node_id="ldn_2020_art145_cl3",
                label="Clause",
                resolution_method="STRUCTURAL",
            ),
            bound_target=BoundEndpoint(
                mention_text=plan.target.text,
                node_id="ldn_2020_art145",
                label="Article",
                resolution_method="FULLTEXT",
            ),
        )


def test_bound_plan_is_not_a_trusted_execution_result() -> None:
    schema = BoundSemanticPlan.model_json_schema()
    serialized = json.dumps(schema)

    assert "execution_status" not in serialized
    assert "satisfied_path_fingerprints" not in serialized


def test_plan_execution_result_enforces_satisfied_invariant() -> None:
    result = PlanExecutionResult(
        plan_fingerprint="plan-1",
        satisfied_path_fingerprints=("path-1",),
        bound_anchor_id="ldn_2020_art145_cl3",
        bound_target_id="ldn_2020_art145_cl1",
        execution_status="satisfied",
        reason_code=PlanReasonCode.SATISFIED,
        derived_reasoning_requirement=GraphReasoningRequirement(minimum_edges=2),
    )

    assert result.execution_status.value == "satisfied"


def test_plan_execution_result_accepts_failed_state_without_trusted_paths() -> None:
    result = PlanExecutionResult(
        plan_fingerprint="plan-1",
        satisfied_path_fingerprints=(),
        bound_anchor_id="anchor-1",
        bound_target_id="target-1",
        execution_status="failed",
        reason_code="NO_PATH",
        message="No exact ordered path exists",
        derived_reasoning_requirement=None,
    )

    assert result.execution_status.value == "failed"
    assert result.satisfied_path_fingerprints == ()


@pytest.mark.parametrize(
    "overrides",
    [
        {"reason_code": "NO_PATH"},
        {"satisfied_path_fingerprints": ()},
        {"satisfied_path_fingerprints": ("path-1", "path-2")},
        {"derived_reasoning_requirement": None},
    ],
)
def test_plan_execution_result_rejects_inconsistent_satisfied_state(
    overrides: dict,
) -> None:
    payload = {
        "plan_fingerprint": "plan-1",
        "satisfied_path_fingerprints": ("path-1",),
        "bound_anchor_id": "anchor-1",
        "bound_target_id": "target-1",
        "execution_status": "satisfied",
        "reason_code": "SATISFIED",
        "derived_reasoning_requirement": {"minimum_edges": 2},
        **overrides,
    }

    with pytest.raises(ValidationError, match="satisfied execution"):
        PlanExecutionResult.model_validate(payload)


@pytest.mark.parametrize(
    "overrides",
    [
        {"reason_code": "SATISFIED"},
        {"satisfied_path_fingerprints": ("path-1",)},
        {"derived_reasoning_requirement": {"minimum_edges": 2}},
    ],
)
def test_plan_execution_result_rejects_inconsistent_failed_state(
    overrides: dict,
) -> None:
    payload = {
        "plan_fingerprint": "plan-1",
        "satisfied_path_fingerprints": (),
        "bound_anchor_id": "anchor-1",
        "bound_target_id": "target-1",
        "execution_status": "failed",
        "reason_code": "NO_PATH",
        "derived_reasoning_requirement": None,
        **overrides,
    }

    with pytest.raises(ValidationError, match="failed execution"):
        PlanExecutionResult.model_validate(payload)


def test_provider_schema_exposes_only_query_plannable_contract_values() -> None:
    schema = UnlinkedSemanticPlan.model_json_schema()
    schema_text = json.dumps(schema)
    relation_values = set(schema["$defs"]["QueryPlannableRelation"]["enum"])

    assert relation_values == set(PHASE1_RELATION_ENUM)
    assert all(alias not in schema_text for alias in LEGACY_RELATION_ALIASES)
    assert all(label not in schema_text for label in RUNTIME_ONLY_LABELS)
    assert "node_id" not in schema_text
