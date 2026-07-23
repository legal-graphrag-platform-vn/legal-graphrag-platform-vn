from __future__ import annotations

from datetime import date

import pytest

from src.retrieval.errors import RetrievalOutputError
from src.retrieval.models import RetrievalFilters
from src.retrieval.planning.executor import PlannedPathExecutor
from src.retrieval.planning.models import (
    AnchorMention,
    BoundEndpoint,
    BoundSemanticPlan,
    PathStepConstraint,
    PlanReasonCode,
    TargetMention,
    UnlinkedSemanticPlan,
)


class FakeExactPathLookup:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.calls: list[dict] = []

    def lookup_exact_paths(self, **kwargs):
        self.calls.append(kwargs)
        return list(self.rows)


def _plan(*, target_label: str = "Clause") -> BoundSemanticPlan:
    unlinked = UnlinkedSemanticPlan(
        anchor=AnchorMention(text="Khoản 3 Điều 145", expected_label="Clause"),
        target=TargetMention(text="đích"),
        steps=(
            PathStepConstraint(
                relation="REFERS_TO", direction="outgoing", next_label="Clause"
            ),
            PathStepConstraint(
                relation="REFERS_TO",
                direction="outgoing",
                next_label=target_label,
            ),
        ),
    )
    return BoundSemanticPlan(
        unlinked=unlinked,
        bound_anchor=BoundEndpoint(
            mention_text=unlinked.anchor.text,
            node_id="anchor",
            label="Clause",
            resolution_method="STRUCTURAL",
        ),
        bound_target=BoundEndpoint(
            mention_text=unlinked.target.text,
            node_id="target",
            label=target_label,
            resolution_method="STRUCTURAL",
        ),
    )


def _node(node_id: str, label: str = "Clause", *, citable: str | None = None):
    return {
        "node_id": node_id,
        "labels": [label],
        "effective_from": date(2021, 1, 1) if label in {"Article", "Clause"} else None,
        "effective_to": None,
        "legal_status": "ACTIVE" if label in {"Article", "Clause"} else None,
        "citable_unit_id": citable
        if citable is not None
        else (node_id if label in {"Article", "Clause"} else None),
    }


def _edge(
    relation_id: str,
    source_id: str,
    target_id: str,
    *,
    relation_type: str = "REFERS_TO",
    effective_from: date | None = None,
    effective_to: date | None = None,
):
    return {
        "relation_id": relation_id,
        "relation_type": relation_type,
        "source_id": source_id,
        "target_id": target_id,
        "effective_from": effective_from,
        "effective_to": effective_to,
    }


def _row(*, middle: str = "middle", target_label: str = "Clause") -> dict:
    return {
        "path_node_refs": [
            _node("anchor"),
            _node(middle),
            _node("target", target_label),
        ],
        "path_edge_refs": [
            _edge("edge-1", "anchor", middle),
            _edge("edge-2", middle, "target"),
        ],
    }


def test_unique_exact_path_is_satisfied_with_stable_fingerprint_and_evidence() -> None:
    lookup = FakeExactPathLookup([_row()])
    execution = PlannedPathExecutor(lookup).execute(
        _plan(), filters=RetrievalFilters(document_ids=["ldn_2020"])
    )

    assert execution.result.reason_code is PlanReasonCode.SATISFIED
    assert execution.result.satisfied_path_fingerprints == (
        execution.path_fingerprints[0],
    )
    assert execution.citable_unit_ids == ("anchor", "middle", "target")
    assert execution.paths[0].nodes[0].node_id == "anchor"
    assert execution.paths[0].nodes[-1].node_id == "target"
    assert lookup.calls[0]["limit"] == 21


def test_incoming_step_preserves_canonical_edge_source_and_target() -> None:
    unlinked = UnlinkedSemanticPlan(
        anchor=AnchorMention(text="Khoản neo", expected_label="Clause"),
        target=TargetMention(text="đích"),
        steps=(
            PathStepConstraint(
                relation="CONTAINS", direction="incoming", next_label="Article"
            ),
            PathStepConstraint(
                relation="REFERS_TO", direction="outgoing", next_label="Clause"
            ),
        ),
    )
    plan = BoundSemanticPlan(
        unlinked=unlinked,
        bound_anchor=BoundEndpoint(
            mention_text="Khoản neo",
            node_id="anchor",
            label="Clause",
            resolution_method="STRUCTURAL",
        ),
        bound_target=BoundEndpoint(
            mention_text="đích",
            node_id="target",
            label="Clause",
            resolution_method="STRUCTURAL",
        ),
    )
    row = _row()
    row["path_node_refs"][1] = _node("middle", "Article")
    row["path_edge_refs"][0] = _edge(
        "edge-1", "middle", "anchor", relation_type="CONTAINS"
    )

    execution = PlannedPathExecutor(FakeExactPathLookup([row])).execute(
        plan, filters=RetrievalFilters()
    )

    edge = execution.paths[0].edges[0]
    assert (edge.source_id, edge.target_id) == ("middle", "anchor")
    assert execution.paths[0].path_description.startswith("anchor <-[CONTAINS]- middle")


@pytest.mark.parametrize(
    ("rows", "reason"),
    [
        ([], PlanReasonCode.NO_PATH),
        ([_row(middle="one"), _row(middle="two")], PlanReasonCode.AMBIGUOUS_PATH),
    ],
)
def test_empty_and_multiple_topologies_have_distinct_failure_reasons(
    rows: list[dict], reason: PlanReasonCode
) -> None:
    execution = PlannedPathExecutor(FakeExactPathLookup(rows)).execute(
        _plan(), filters=RetrievalFilters()
    )

    assert execution.result.reason_code is reason
    assert execution.paths == ()


def test_limit_plus_one_result_reports_path_budget_exceeded() -> None:
    rows = [_row(middle=f"middle-{index}") for index in range(3)]
    execution = PlannedPathExecutor(FakeExactPathLookup(rows), max_paths=2).execute(
        _plan(), filters=RetrievalFilters()
    )

    assert execution.result.reason_code is PlanReasonCode.PATH_BUDGET_EXCEEDED
    assert execution.paths == ()


def test_temporally_invalid_exact_path_has_typed_reason() -> None:
    row = _row()
    row["path_node_refs"][1]["effective_to"] = date(2025, 1, 1)
    execution = PlannedPathExecutor(FakeExactPathLookup([row])).execute(
        _plan(), filters=RetrievalFilters(query_date=date(2025, 1, 1))
    )

    assert execution.result.reason_code is PlanReasonCode.TEMPORAL_REJECTED


def test_temporal_edge_uses_half_open_validity_interval() -> None:
    row = _row()
    row["path_edge_refs"][0].update(
        relation_type="REFERS_TO",
        effective_from=date(2024, 1, 1),
        effective_to=date(2025, 1, 1),
    )
    execution = PlannedPathExecutor(FakeExactPathLookup([row])).execute(
        _plan(), filters=RetrievalFilters(query_date=date(2025, 1, 1))
    )

    assert execution.result.reason_code is PlanReasonCode.TEMPORAL_REJECTED


def test_point_evidence_is_lifted_to_parent_clause_from_satisfied_path() -> None:
    unlinked = UnlinkedSemanticPlan(
        anchor=AnchorMention(text="Khoản neo", expected_label="Clause"),
        target=TargetMention(text="điểm đích"),
        steps=(
            PathStepConstraint(
                relation="CONTAINS", direction="incoming", next_label="Article"
            ),
            PathStepConstraint(
                relation="REFERS_TO", direction="outgoing", next_label="Point"
            ),
        ),
    )
    plan = BoundSemanticPlan(
        unlinked=unlinked,
        bound_anchor=BoundEndpoint(
            mention_text=unlinked.anchor.text,
            node_id="anchor",
            label="Clause",
            resolution_method="STRUCTURAL",
        ),
        bound_target=BoundEndpoint(
            mention_text=unlinked.target.text,
            node_id="target",
            label="Point",
            resolution_method="STRUCTURAL",
        ),
    )
    row = _row(target_label="Point")
    row["path_node_refs"][1] = _node("middle", "Article")
    row["path_node_refs"][2] = _node("target", "Point", citable="parent-clause")
    row["path_edge_refs"] = [
        _edge("edge-1", "middle", "anchor", relation_type="CONTAINS"),
        _edge("edge-2", "middle", "target"),
    ]

    execution = PlannedPathExecutor(FakeExactPathLookup([row])).execute(
        plan, filters=RetrievalFilters()
    )

    assert execution.result.reason_code is PlanReasonCode.SATISFIED
    assert execution.citable_unit_ids == ("anchor", "middle", "parent-clause")


def test_parallel_rows_with_same_topology_collapse_deterministically() -> None:
    first = _row()
    second = _row()
    second["path_edge_refs"][0]["relation_id"] = "parallel-citation"
    execution = PlannedPathExecutor(FakeExactPathLookup([second, first])).execute(
        _plan(), filters=RetrievalFilters()
    )

    assert execution.result.reason_code is PlanReasonCode.SATISFIED
    assert len(execution.paths) == 1


def test_semantic_target_without_citable_article_or_clause_on_path_is_rejected() -> (
    None
):
    unlinked = UnlinkedSemanticPlan(
        anchor=AnchorMention(text="Khoản neo", expected_label="Clause"),
        target=TargetMention(text="khái niệm đích"),
        steps=(
            PathStepConstraint(
                relation="REGULATES",
                direction="outgoing",
                next_label="LegalSubject",
            ),
            PathStepConstraint(
                relation="REQUIRES",
                direction="outgoing",
                next_label="LegalConcept",
            ),
        ),
    )
    plan = BoundSemanticPlan(
        unlinked=unlinked,
        bound_anchor=BoundEndpoint(
            mention_text=unlinked.anchor.text,
            node_id="anchor",
            label="Clause",
            resolution_method="STRUCTURAL",
        ),
        bound_target=BoundEndpoint(
            mention_text=unlinked.target.text,
            node_id="target",
            label="LegalConcept",
            resolution_method="FULLTEXT",
        ),
    )
    row = _row(target_label="LegalConcept")
    row["path_node_refs"] = [
        _node("anchor", "Clause"),
        _node("middle", "LegalSubject"),
        _node("target", "LegalConcept"),
    ]
    row["path_node_refs"][0]["citable_unit_id"] = None
    row["path_edge_refs"] = [
        _edge("edge-1", "anchor", "middle", relation_type="REGULATES"),
        _edge("edge-2", "middle", "target", relation_type="REQUIRES"),
    ]
    execution = PlannedPathExecutor(FakeExactPathLookup([row])).execute(
        plan, filters=RetrievalFilters()
    )

    assert execution.result.reason_code is PlanReasonCode.EVIDENCE_UNLIFTABLE
    assert execution.citable_unit_ids == ()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda row: row["path_node_refs"].append(_node("extra")),
        lambda row: row["path_node_refs"].__setitem__(2, _node("wrong-target")),
        lambda row: row["path_node_refs"].__setitem__(1, _node("middle", "Article")),
        lambda row: row["path_edge_refs"].__setitem__(
            0, _edge("edge-1", "middle", "anchor")
        ),
        lambda row: row["path_node_refs"].__setitem__(1, _node("anchor")),
    ],
)
def test_malformed_or_nonconforming_repository_path_is_rejected(mutate) -> None:
    row = _row()
    mutate(row)

    with pytest.raises(RetrievalOutputError):
        PlannedPathExecutor(FakeExactPathLookup([row])).execute(
            _plan(), filters=RetrievalFilters()
        )
