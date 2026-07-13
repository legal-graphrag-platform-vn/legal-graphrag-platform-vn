import json
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.retrieval.errors import RetrievalCapabilityError
from src.retrieval.config import RetrievalConfig
from src.retrieval.eval.development import (
    DevelopmentEvaluationDataset,
    DevelopmentEvaluationMetadata,
    DevelopmentEvaluationRunner,
    _collapse_retrieved_relevance_groups,
    _graph_path_hit,
    _structural_relevance_group,
    load_development_dataset,
)
from src.retrieval.models import (
    IntentType,
    GraphPath,
    RetrievalContext,
    RetrievedUnit,
    TemporalQuery,
)
from src.retrieval.models import RetrievalRequest
from src.retrieval.routing.router import IntentRouter


class SupportedRuntime:
    def retrieve(self, request):
        return RetrievalContext(
            query=request.query,
            intent=IntentType.FACTUAL,
            temporal=TemporalQuery(has_temporal=False),
            force_intent_used=request.force_intent is not None,
            retrieved_units=[
                RetrievedUnit(
                    id="expected",
                    label="Article",
                    content_raw="content",
                    document_id="doc",
                    citation_label="Điều 1",
                )
            ],
            graph_paths=[],
            evidence=[],
            metrics={},
            retrieval_mode="vector_only",
        )


class UnsupportedRuntime:
    def retrieve(self, request):
        raise RetrievalCapabilityError(
            "not available",
            required_capability="guides_relations",
            available_capability="none",
        )


class RankedRuntime:
    def retrieve(self, request):
        return RetrievalContext(
            query=request.query,
            intent=IntentType.FACTUAL,
            temporal=TemporalQuery(has_temporal=False),
            force_intent_used=False,
            retrieved_units=[
                _retrieved_unit("irrelevant"),
                _retrieved_unit("expected"),
            ],
            graph_paths=[],
            evidence=[],
            metrics={},
            retrieval_mode="vector_only",
        )


def test_development_evaluation_separates_unsupported_cases(tmp_path) -> None:
    dataset = tmp_path / "dataset.json"
    dataset.write_text(
        json.dumps(
            _dataset_payload(
                [
                    _case_payload(
                        query_id="q1",
                        intent="factual",
                        expected_status="supported",
                        capability="hybrid_seed_and_semantic_graph",
                        gold_ids=["expected"],
                    )
                ]
            )
        ),
        encoding="utf-8",
    )
    report = DevelopmentEvaluationRunner(
        {"supported": SupportedRuntime(), "unsupported": UnsupportedRuntime()}
    ).run(
        dataset,
        metadata=DevelopmentEvaluationMetadata(
            source_commit="abc",
            working_tree_state="dirty",
            router_config_hash="router",
            embedding_contract="embedding",
            reranker_contract="disabled",
            neo4j_graph_snapshot_hash="graph",
        ),
    )
    assert report["evaluation_scope"] == "pilot_development"
    assert report["Gate 7"] == "OPEN"
    assert report["dataset_schema_version"] == "retrieval-evaluation-dataset-v1"
    assert report["profiles"]["supported"]["metrics"]["MRR"] == 1.0
    unsupported = report["profiles"]["unsupported"]
    assert unsupported["metrics"] == {"sample_size": 0}
    assert unsupported["cases"][0]["status"] == "unsupported"
    assert unsupported["cases"][0]["expectation_match"] is False


def test_expected_unsupported_capability_matches_runtime_error(tmp_path) -> None:
    dataset = tmp_path / "dataset.json"
    dataset.write_text(
        json.dumps(
            _dataset_payload(
                [
                    _case_payload(
                        query_id="q1",
                        intent="hierarchy",
                        expected_status="unsupported",
                        capability="guides_relations",
                        gold_ids=[],
                    )
                ]
            )
        ),
        encoding="utf-8",
    )
    report = DevelopmentEvaluationRunner({"unsupported": UnsupportedRuntime()}).run(
        dataset,
        metadata=_metadata(),
    )

    profile = report["profiles"]["unsupported"]
    assert profile["expectation_mismatch_count"] == 0
    assert profile["outcomes_by_intent"]["hierarchy"] == {
        "supported": 0,
        "unsupported": 1,
    }


def test_non_gold_results_keep_their_rank_in_grouped_metrics(tmp_path) -> None:
    dataset = tmp_path / "dataset.json"
    dataset.write_text(
        json.dumps(
            _dataset_payload(
                [
                    _case_payload(
                        query_id="q1",
                        intent="factual",
                        expected_status="supported",
                        capability="hybrid_seed_and_semantic_graph",
                        gold_ids=["expected"],
                    )
                ]
            )
        ),
        encoding="utf-8",
    )

    report = DevelopmentEvaluationRunner({"ranked": RankedRuntime()}).run(
        dataset, metadata=_metadata()
    )

    assert report["profiles"]["ranked"]["metrics"]["MRR"] == 0.5


def test_supported_case_requires_gold_relevance() -> None:
    payload = _dataset_payload(
        [
            _case_payload(
                query_id="q1",
                intent="factual",
                expected_status="supported",
                capability="hybrid_seed_and_semantic_graph",
                gold_ids=[],
            )
        ]
    )

    with pytest.raises(ValidationError, match="require gold_relevance"):
        DevelopmentEvaluationDataset.model_validate(payload)


def test_parent_article_and_clause_share_one_metric_group() -> None:
    assert _structural_relevance_group("ldn_2020_art17") == (
        _structural_relevance_group("ldn_2020_art17_cl2")
    )


def test_structural_group_uses_grade_of_units_actually_returned() -> None:
    article_id = "ldn_2020_art17"
    clause_id = "ldn_2020_art17_cl2"
    group_id = _structural_relevance_group(article_id)
    relevance = {article_id: 2, clause_id: 3}
    groups = {article_id: group_id, clause_id: group_id}

    parent_groups, parent_grades = _collapse_retrieved_relevance_groups(
        [article_id], relevance_by_id=relevance, group_by_id=groups
    )
    clause_groups, clause_grades = _collapse_retrieved_relevance_groups(
        [clause_id], relevance_by_id=relevance, group_by_id=groups
    )
    both_groups, both_grades = _collapse_retrieved_relevance_groups(
        [article_id, clause_id], relevance_by_id=relevance, group_by_id=groups
    )

    assert parent_groups == [group_id]
    assert parent_grades == {group_id: 2}
    assert clause_groups == [group_id]
    assert clause_grades == {group_id: 3}
    assert both_groups == [group_id]
    assert both_grades == {group_id: 3}


def test_approved_thirty_query_dataset_has_balanced_intents() -> None:
    dataset = load_development_dataset(
        Path("configs/evaluation/retrieval_pilot_l59_2020.json")
    )

    assert len(dataset.cases) == 30
    assert dataset.review.status == "approved"
    assert dataset.review.reviewer == "lamdx4"
    distribution = {
        intent.value: sum(case.intent is intent for case in dataset.cases)
        for intent in IntentType
    }
    assert distribution == {
        "factual": 5,
        "validity": 5,
        "hierarchy": 5,
        "comparison": 5,
        "definition": 5,
        "multi_hop": 5,
    }
    assert all(case.review.status == "approved" for case in dataset.cases)
    assert all(case.review.reviewer == "lamdx4" for case in dataset.cases)
    graph_case_types = {
        case.query_id: case.graph_case_type
        for case in dataset.cases
        if case.intent is IntentType.MULTI_HOP
    }
    assert list(graph_case_types.values()).count("multi_edge_traversal") == 4
    assert graph_case_types["multi_hop_05"] == "branching_reference"


def test_approved_thirty_query_dataset_routes_to_declared_intents() -> None:
    dataset = load_development_dataset(
        Path("configs/evaluation/retrieval_pilot_l59_2020.json")
    )
    router = IntentRouter(RetrievalConfig(), clock=FixedClock())

    for case in dataset.cases:
        routing = router.route(RetrievalRequest(query=case.query))
        assert routing.decision.intent == case.intent, case.query_id


def test_thirty_query_gold_ids_resolve_in_pilot_hierarchy() -> None:
    dataset = load_development_dataset(
        Path("configs/evaluation/retrieval_pilot_l59_2020.json")
    )
    hierarchy = json.loads(
        Path("data/processed/L59_2020/hierarchy.json").read_text(encoding="utf-8")
    )
    canonical_ids = {"ldn_2020"}
    for article in hierarchy["articles"]:
        article_id = f"ldn_2020_art{article['number']}"
        canonical_ids.add(article_id)
        canonical_ids.update(
            f"{article_id}_cl{clause['number']}"
            for clause in article.get("clauses", [])
        )

    missing = {
        gold.unit_id
        for case in dataset.cases
        for gold in case.gold_relevance
        if gold.unit_id not in canonical_ids
    }
    assert missing == set()


def test_thirty_query_capabilities_and_gold_paths_match_pilot_artifacts() -> None:
    dataset = load_development_dataset(
        Path("configs/evaluation/retrieval_pilot_l59_2020.json")
    )
    hierarchy = json.loads(
        Path("data/processed/L59_2020/hierarchy.json").read_text(encoding="utf-8")
    )
    relation_triples: set[tuple[str, str, str]] = set()
    relation_properties: dict[tuple[str, str, str], dict] = {}
    relation_types: set[str] = set()
    for line in (
        Path("data/processed/L59_2020/accepted.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ):
        relation = json.loads(line).get("relation") or {}
        relation_type = relation.get("relation") or relation.get("type")
        if relation_type:
            relation_types.add(relation_type)
            triple = (relation["head"], relation_type, relation["tail"])
            relation_triples.add(triple)
            relation_properties[triple] = relation.get("properties") or {}

    for article in hierarchy["articles"]:
        article_id = f"ldn_2020_art{article['number']}"
        for clause in article.get("clauses", []):
            clause_id = f"{article_id}_cl{clause['number']}"
            relation_triples.add((article_id, "CONTAINS", clause_id))
            for point in clause.get("points", []):
                point_label = "dd" if point["label"] == "đ" else point["label"]
                relation_triples.add(
                    (clause_id, "CONTAINS", f"{clause_id}_p{point_label}")
                )

    available = {
        "hybrid_seed_and_semantic_graph": True,
        "lexical_definition": True,
        "semantic_multi_hop_graph": "REFERS_TO" in relation_types,
        "scoped_temporal_metadata": bool(
            hierarchy["document"].get("effective_from")
            and hierarchy["document"].get("legal_status")
        ),
        "corpus_complete_current_validity": False,
        "structural_hierarchy": bool(hierarchy.get("articles")),
        "guides_relations": "GUIDES" in relation_types,
        "multiple_versions": bool(relation_types & {"AMENDS", "REPEALS", "REPLACES"}),
    }

    for case in dataset.cases:
        requirement = case.capability_requirement
        assert available[requirement.name.value] is requirement.expected_available, (
            case.query_id
        )
        for path in case.gold_paths:
            frontier = {path.source_id}
            traversed: list[tuple[str, str, str]] = []
            for relation_type in path.relation_types:
                matches = [
                    triple
                    for triple in relation_triples
                    if triple[0] in frontier and triple[1] == relation_type
                ]
                traversed.extend(matches)
                frontier = {triple[2] for triple in matches}
            assert path.target_id in frontier, case.query_id
            for triple in traversed:
                if triple[1] != "REFERS_TO":
                    continue
                properties = relation_properties[triple]
                assert properties.get("citation_text"), case.query_id
                assert properties.get("citation_type"), case.query_id
                assert properties.get("confidence") is not None, case.query_id
                assert properties.get("llm_model"), case.query_id
                assert properties.get("created_at"), case.query_id

        if case.gold_temporal is not None:
            evidence = case.gold_temporal.temporal_evidence
            assert evidence.source_type == "document_metadata", case.query_id
            assert evidence.source_id == hierarchy["document"]["id"], case.query_id
            for field in evidence.required_fields:
                if field == "effective_to":
                    continue
                assert hierarchy["document"].get(field) is not None, case.query_id


def test_multi_hop_legal_gold_matches_reviewed_targets() -> None:
    dataset = load_development_dataset(
        Path("configs/evaluation/retrieval_pilot_l59_2020.json")
    )
    cases = {case.query_id: case for case in dataset.cases}

    assert cases["multi_hop_01"].gold_paths[0].target_id == ("ldn_2020_art41_cl2")
    assert cases["multi_hop_01"].gold_relevance[-1].unit_id == ("ldn_2020_art41_cl2")
    assert all(
        cases[query_id].minimum_hops >= 2
        for query_id in ("multi_hop_01", "multi_hop_02", "multi_hop_03", "multi_hop_04")
    )
    assert cases["multi_hop_05"].minimum_hops == 1
    assert len(cases["multi_hop_05"].gold_paths) == 2


def test_branching_reference_requires_every_gold_branch() -> None:
    dataset = load_development_dataset(
        Path("configs/evaluation/retrieval_pilot_l59_2020.json")
    )
    case = next(item for item in dataset.cases if item.query_id == "multi_hop_05")
    first_path = GraphPath(
        nodes=["ldn_2020_art52_cl1", "ldn_2020_art53_cl6"],
        relations=["REFERS_TO"],
        path_description="first branch",
        is_temporal_valid=True,
    )
    second_path = GraphPath(
        nodes=["ldn_2020_art52_cl1", "ldn_2020_art53_cl7"],
        relations=["REFERS_TO"],
        path_description="second branch",
        is_temporal_valid=True,
    )
    context = SupportedRuntime().retrieve(RetrievalRequest(query=case.query))

    assert not _graph_path_hit(
        case, context.model_copy(update={"graph_paths": [first_path]})
    )
    assert _graph_path_hit(
        case,
        context.model_copy(update={"graph_paths": [first_path, second_path]}),
    )


def test_official_evaluation_rejects_pending_dataset(tmp_path) -> None:
    dataset = tmp_path / "dataset.json"
    dataset.write_text(
        json.dumps(
            _dataset_payload(
                [
                    _case_payload(
                        query_id="q1",
                        intent="factual",
                        expected_status="supported",
                        capability="hybrid_seed_and_semantic_graph",
                        gold_ids=["expected"],
                    )
                ]
            )
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="requires approved dataset"):
        DevelopmentEvaluationRunner({"supported": SupportedRuntime()}).run(
            dataset,
            metadata=_metadata(),
            require_approved_dataset=True,
        )


def _metadata() -> DevelopmentEvaluationMetadata:
    return DevelopmentEvaluationMetadata(
        source_commit="abc",
        working_tree_state="dirty",
        router_config_hash="router",
        embedding_contract="embedding",
        reranker_contract="disabled",
        neo4j_graph_snapshot_hash="graph",
    )


class FixedClock:
    def today(self) -> date:
        return date(2026, 7, 13)


def _dataset_payload(cases: list[dict]) -> dict:
    return {
        "schema_version": "retrieval-evaluation-dataset-v1",
        "evaluation_scope": "pilot_development",
        "name": "test dataset",
        "document_ids": ["doc"],
        "target_query_count": len(cases),
        "review": {
            "reviewer": "test reviewer",
            "status": "pending_human_sign_off",
            "reviewed_at": None,
        },
        "cases": cases,
    }


def _case_payload(
    *,
    query_id: str,
    intent: str,
    expected_status: str,
    capability: str,
    gold_ids: list[str],
) -> dict:
    return {
        "query_id": query_id,
        "query": "query",
        "intent": intent,
        "expected_status": expected_status,
        "capability_requirement": {
            "name": capability,
            "expected_available": expected_status == "supported",
            "reason": "test capability",
        },
        "gold_relevance": [
            {"unit_id": unit_id, "relevance": 3, "reason": "gold"}
            for unit_id in gold_ids
        ],
        "review": {
            "reviewer": "test reviewer",
            "status": "pending_human_sign_off",
            "reviewed_at": None,
        },
    }


def _retrieved_unit(unit_id: str) -> RetrievedUnit:
    return RetrievedUnit(
        id=unit_id,
        label="Article",
        content_raw="content",
        document_id="doc",
        citation_label="Điều 1",
    )
