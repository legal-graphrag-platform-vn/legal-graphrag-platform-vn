from __future__ import annotations

import json
from pathlib import Path

from src.retrieval.config import EndpointLinkerConfig
from src.retrieval.eval.linker_calibration import calibrate_role
from src.retrieval.models import RetrievalFilters, RetrievedUnit
from src.retrieval.planning.linker import (
    EndpointLinker,
    EndpointResolutionStatus,
    EndpointRole,
    SemanticEndpointResolver,
    StructuralEndpointResolver,
)
from src.retrieval.planning.models import PlanReasonCode


class FakeChannel:
    def __init__(self, units: list[RetrievedUnit]) -> None:
        self.units = units
        self.calls = 0

    def retrieve(self, query, *, filters, top_k):
        self.calls += 1
        return self.units[:top_k]


class FakeStructuralLookup:
    def __init__(self, rows: list[dict] | None = None) -> None:
        self.rows = rows or []
        self.calls = 0

    def lookup_structural_endpoints(self, **kwargs):
        self.calls += 1
        return self.rows


def test_semantic_resolver_resolves_candidate_present_in_both_channels() -> None:
    top = _unit("target", vector_score=0.9, bm25_score=8.0)
    runner_up = _unit("runner-up", vector_score=0.8)
    resolver = _resolver(vector=[top, runner_up], fulltext=[top])

    result = resolver.resolve(
        mention_text="trình tự chào bán phần vốn góp",
        role=EndpointRole.TARGET,
        expected_label="Clause",
        filters=RetrievalFilters(document_ids=["ldn_2020"]),
    )

    assert result.status is EndpointResolutionStatus.RESOLVED
    assert result.bound_endpoint is not None
    assert result.bound_endpoint.node_id == "target"
    assert result.bound_endpoint.resolution_method.value == "VECTOR_RRF"


def test_semantic_candidate_tie_is_deterministic_and_ambiguous() -> None:
    a = _unit("a-id")
    z = _unit("z-id")
    resolver = _resolver(vector=[z, a], fulltext=[a, z])

    result = resolver.resolve(
        mention_text="nội dung mục tiêu",
        role=EndpointRole.TARGET,
        expected_label="Clause",
        filters=RetrievalFilters(document_ids=["ldn_2020"]),
    )

    assert result.status is EndpointResolutionStatus.AMBIGUOUS
    assert result.reason_code is PlanReasonCode.AMBIGUOUS_TARGET
    assert [candidate.node_id for candidate in result.candidates] == ["a-id", "z-id"]


def test_article_channel_hit_supports_clause_in_same_hierarchy_family() -> None:
    clause = _unit("ldn_2020_art52_cl1", vector_score=0.9)
    article = _unit("ldn_2020_art52", bm25_score=8.0, label="Article")
    resolver = _resolver(vector=[clause], fulltext=[article])

    result = resolver.resolve(
        mention_text="trình tự chào bán phần vốn góp",
        role=EndpointRole.TARGET,
        expected_label="Clause",
        filters=RetrievalFilters(document_ids=["ldn_2020"]),
    )

    assert result.status is EndpointResolutionStatus.RESOLVED
    assert result.bound_endpoint is not None
    assert result.bound_endpoint.node_id == "ldn_2020_art52_cl1"
    assert set(result.candidates[0].retrieval_sources) == {"fulltext", "vector"}


def test_below_role_threshold_returns_typed_unbound() -> None:
    resolver = _resolver(
        vector=[_unit("weak")],
        fulltext=[],
        config=EndpointLinkerConfig(
            anchor_min_score=0.02,
            target_min_score=0.02,
            anchor_min_margin=0.001,
            target_min_margin=0.001,
            anchor_candidate_k=5,
            target_candidate_k=5,
        ),
    )

    anchor = resolver.resolve(
        mention_text="chủ thể cần tìm",
        role=EndpointRole.ANCHOR,
        expected_label="Clause",
        filters=RetrievalFilters(document_ids=["ldn_2020"]),
    )
    target = resolver.resolve(
        mention_text="đích cần tìm",
        role=EndpointRole.TARGET,
        expected_label="Clause",
        filters=RetrievalFilters(document_ids=["ldn_2020"]),
    )

    assert anchor.reason_code is PlanReasonCode.UNBOUND_ANCHOR
    assert target.reason_code is PlanReasonCode.UNBOUND_TARGET


def test_structural_reference_never_falls_back_to_semantic_ranking() -> None:
    structural_lookup = FakeStructuralLookup(
        [{"node_id": "clause-3", "label": "Clause", "document_id": "ldn_2020"}]
    )
    vector = FakeChannel([_unit("semantic-other")])
    fulltext = FakeChannel([_unit("semantic-other")])
    linker = EndpointLinker(
        structural=StructuralEndpointResolver(structural_lookup),
        semantic=SemanticEndpointResolver(
            vector=vector,
            fulltext=fulltext,
            config=_config(),
        ),
    )

    result = linker.resolve(
        mention_text="Khoản 3 Điều 145",
        role=EndpointRole.ANCHOR,
        expected_label="Clause",
        filters=RetrievalFilters(document_ids=["ldn_2020"]),
    )

    assert result.bound_endpoint is not None
    assert result.bound_endpoint.node_id == "clause-3"
    assert vector.calls == 0
    assert fulltext.calls == 0


def test_pinned_calibration_reproduces_role_thresholds_and_separate_metrics() -> None:
    artifact = json.loads(
        Path("configs/evaluation/query_graph_linker_calibration.json").read_text(
            encoding="utf-8"
        )
    )

    anchor = calibrate_role(artifact["cases"], role="anchor")
    target = calibrate_role(artifact["cases"], role="target")
    defaults = EndpointLinkerConfig()

    assert (anchor.min_score, anchor.min_margin) == (0.063, 0.001)
    assert (target.min_score, target.min_margin) == (0.063, 0.001)
    assert (defaults.anchor_min_score, defaults.anchor_min_margin) == (
        anchor.min_score,
        anchor.min_margin,
    )
    assert (defaults.target_min_score, defaults.target_min_margin) == (
        target.min_score,
        target.min_margin,
    )
    assert anchor.false_resolution_count == target.false_resolution_count == 0
    assert anchor.accuracy == 1 / 3
    assert target.accuracy == 2 / 3
    assert artifact["path_execution"]["accuracy"] == 1.0


def _resolver(
    *,
    vector: list[RetrievedUnit],
    fulltext: list[RetrievedUnit],
    config: EndpointLinkerConfig | None = None,
) -> SemanticEndpointResolver:
    return SemanticEndpointResolver(
        vector=FakeChannel(vector),
        fulltext=FakeChannel(fulltext),
        config=config or _config(),
    )


def _config() -> EndpointLinkerConfig:
    return EndpointLinkerConfig(
        anchor_min_score=0.015,
        target_min_score=0.015,
        anchor_min_margin=0.001,
        target_min_margin=0.001,
        anchor_candidate_k=5,
        target_candidate_k=5,
    )


def _unit(
    unit_id: str,
    *,
    vector_score: float | None = None,
    bm25_score: float | None = None,
    label: str = "Clause",
) -> RetrievedUnit:
    article_id = unit_id if label == "Article" else unit_id.rsplit("_cl", 1)[0]
    return RetrievedUnit(
        id=unit_id,
        label=label,
        content_raw="Nội dung pháp lý",
        document_id="ldn_2020",
        article_id=article_id,
        clause_id=unit_id if label == "Clause" else None,
        citation_label="Khoản thử nghiệm",
        vector_score=vector_score,
        bm25_score=bm25_score,
        retrieval_sources=[],
    )
