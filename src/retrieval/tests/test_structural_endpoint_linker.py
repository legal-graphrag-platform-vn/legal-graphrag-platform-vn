from __future__ import annotations

import pytest

from src.retrieval.errors import RetrievalOutputError
from src.retrieval.models import RetrievalFilters
from src.retrieval.planning.linker import (
    EndpointRole,
    EndpointResolutionStatus,
    StructuralEndpointResolver,
    parse_structural_reference,
)
from src.retrieval.planning.models import PlanReasonCode


class FakeLookup:
    def __init__(self, rows: list[dict] | None = None) -> None:
        self.rows = rows or []
        self.calls: list[dict] = []

    def lookup_structural_endpoints(self, **kwargs):
        self.calls.append(kwargs)
        return list(self.rows)


@pytest.mark.parametrize(
    ("mention", "label", "document_number", "article", "clause", "point"),
    [
        ("Luật số 59/2020/QH14", "Document", "59/2020/QH14", None, None, None),
        ("Điều 145", "Article", None, "145", None, None),
        ("Khoản 3 Điều 145", "Clause", None, "145", "3", None),
        ("điểm đ khoản 2 Điều 5", "Point", None, "5", "2", "đ"),
    ],
)
def test_parse_structural_reference_uses_controlled_grammar(
    mention: str,
    label: str,
    document_number: str | None,
    article: str | None,
    clause: str | None,
    point: str | None,
) -> None:
    parsed = parse_structural_reference(mention)

    assert parsed is not None
    assert parsed.label == label
    assert parsed.document_number == document_number
    assert parsed.article_number == article
    assert parsed.clause_number == clause
    assert parsed.point_label == point


def test_unique_structural_match_returns_database_candidate_without_inferring_id() -> (
    None
):
    lookup = FakeLookup(
        [
            {
                "node_id": "canonical-id-returned-by-database",
                "label": "Clause",
                "document_id": "ldn_2020",
            }
        ]
    )
    resolver = StructuralEndpointResolver(lookup)

    result = resolver.resolve(
        mention_text="Khoản 3 Điều 145",
        role=EndpointRole.ANCHOR,
        expected_label="Clause",
        filters=RetrievalFilters(document_ids=["ldn_2020"]),
    )

    assert result.status is EndpointResolutionStatus.RESOLVED
    assert result.reason_code is None
    assert result.bound_endpoint is not None
    assert result.bound_endpoint.node_id == "canonical-id-returned-by-database"
    assert result.bound_endpoint.resolution_method.value == "STRUCTURAL"
    assert lookup.calls[0]["article_number"] == "145"
    assert lookup.calls[0]["clause_number"] == "3"


@pytest.mark.parametrize(
    ("role", "reason_code"),
    [
        (EndpointRole.ANCHOR, PlanReasonCode.AMBIGUOUS_ANCHOR),
        (EndpointRole.TARGET, PlanReasonCode.AMBIGUOUS_TARGET),
    ],
)
def test_missing_document_scope_is_typed_ambiguous_without_lookup(
    role: EndpointRole,
    reason_code: PlanReasonCode,
) -> None:
    lookup = FakeLookup()

    result = StructuralEndpointResolver(lookup).resolve(
        mention_text="Điều 145",
        role=role,
        expected_label="Article",
        filters=RetrievalFilters(),
    )

    assert result.status is EndpointResolutionStatus.AMBIGUOUS
    assert result.reason_code is reason_code
    assert result.candidates == ()
    assert lookup.calls == []


@pytest.mark.parametrize(
    ("role", "reason_code"),
    [
        (EndpointRole.ANCHOR, PlanReasonCode.UNBOUND_ANCHOR),
        (EndpointRole.TARGET, PlanReasonCode.UNBOUND_TARGET),
    ],
)
def test_no_match_is_typed_unbound_for_endpoint_role(
    role: EndpointRole,
    reason_code: PlanReasonCode,
) -> None:
    result = StructuralEndpointResolver(FakeLookup()).resolve(
        mention_text="Điều 999",
        role=role,
        expected_label="Article",
        filters=RetrievalFilters(document_ids=["ldn_2020"]),
    )

    assert result.status is EndpointResolutionStatus.UNBOUND
    assert result.reason_code is reason_code
    assert result.bound_endpoint is None


def test_string_role_is_normalized_before_reason_code_selection() -> None:
    result = StructuralEndpointResolver(FakeLookup()).resolve(
        mention_text="Điều 999",
        role="anchor",
        expected_label="Article",
        filters=RetrievalFilters(document_ids=["ldn_2020"]),
    )

    assert result.role is EndpointRole.ANCHOR
    assert result.reason_code is PlanReasonCode.UNBOUND_ANCHOR


def test_unknown_role_is_rejected_at_contract_boundary() -> None:
    with pytest.raises(ValueError, match="not a valid EndpointRole"):
        StructuralEndpointResolver(FakeLookup()).resolve(
            mention_text="Điều 1",
            role="source",
            expected_label="Article",
            filters=RetrievalFilters(document_ids=["doc"]),
        )


def test_multiple_matches_are_ambiguous_and_candidates_have_stable_id_order() -> None:
    lookup = FakeLookup(
        [
            {"node_id": "z-id", "label": "Article", "document_id": "doc-b"},
            {"node_id": "a-id", "label": "Article", "document_id": "doc-a"},
        ]
    )

    result = StructuralEndpointResolver(lookup).resolve(
        mention_text="Điều 1",
        role=EndpointRole.TARGET,
        expected_label="Article",
        filters=RetrievalFilters(document_ids=["doc-b", "doc-a"]),
    )

    assert result.status is EndpointResolutionStatus.AMBIGUOUS
    assert result.reason_code is PlanReasonCode.AMBIGUOUS_TARGET
    assert [candidate.node_id for candidate in result.candidates] == ["a-id", "z-id"]


def test_duplicate_database_rows_for_same_node_collapse_to_unique_match() -> None:
    row = {"node_id": "article-1", "label": "Article", "document_id": "doc"}
    result = StructuralEndpointResolver(FakeLookup([row, dict(row)])).resolve(
        mention_text="Điều 1",
        role=EndpointRole.ANCHOR,
        expected_label="Article",
        filters=RetrievalFilters(document_ids=["doc"]),
    )

    assert result.status is EndpointResolutionStatus.RESOLVED
    assert len(result.candidates) == 1


def test_grammar_or_expected_label_mismatch_is_unbound_without_lookup() -> None:
    lookup = FakeLookup()
    resolver = StructuralEndpointResolver(lookup)

    semantic = resolver.resolve(
        mention_text="quyền yêu cầu triệu tập họp",
        role=EndpointRole.TARGET,
        expected_label="Clause",
        filters=RetrievalFilters(document_ids=["doc"]),
    )
    wrong_label = resolver.resolve(
        mention_text="Điều 49",
        role=EndpointRole.TARGET,
        expected_label="Clause",
        filters=RetrievalFilters(document_ids=["doc"]),
    )

    assert semantic.reason_code is PlanReasonCode.UNBOUND_TARGET
    assert wrong_label.reason_code is PlanReasonCode.UNBOUND_TARGET
    assert lookup.calls == []


def test_malformed_lookup_row_is_rejected_at_adapter_boundary() -> None:
    lookup = FakeLookup(
        [{"node_id": "article-1", "label": "Clause", "document_id": "doc"}]
    )

    with pytest.raises(RetrievalOutputError, match="label"):
        StructuralEndpointResolver(lookup).resolve(
            mention_text="Điều 1",
            role=EndpointRole.ANCHOR,
            expected_label="Article",
            filters=RetrievalFilters(document_ids=["doc"]),
        )
