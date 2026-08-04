from __future__ import annotations

import pytest

from src.generation.sufficiency import EvidenceSufficiencyPolicy
from src.generation.tests.factories import graph_path, retrieval_context
from src.retrieval.models import IntentType


@pytest.mark.parametrize("intent", [IntentType.FACTUAL, IntentType.DEFINITION])
def test_basic_intents_require_sufficient_evidence(intent: IntentType) -> None:
    context = retrieval_context(intent=intent)
    assert EvidenceSufficiencyPolicy().evaluate(context).sufficient is True
    context.evidence[0].is_eligible = False
    result = EvidenceSufficiencyPolicy().evaluate(context)
    assert result.sufficient is False
    assert result.reason_code == "NO_SUFFICIENT_EVIDENCE"


def test_no_results_is_insufficient() -> None:
    result = EvidenceSufficiencyPolicy().evaluate(retrieval_context(no_results=True))
    assert result.reason_code == "NO_RESULTS"


def test_hierarchy_requires_contains_path() -> None:
    missing = retrieval_context(intent=IntentType.HIERARCHY)
    present = retrieval_context(
        intent=IntentType.HIERARCHY,
        path_relations=["CONTAINS"],
    )
    assert EvidenceSufficiencyPolicy().evaluate(missing).sufficient is False
    assert EvidenceSufficiencyPolicy().evaluate(present).sufficient is True


def test_multi_hop_requires_trusted_requirement_and_two_edge_path() -> None:
    missing = retrieval_context(intent=IntentType.MULTI_HOP)
    present = retrieval_context(
        intent=IntentType.MULTI_HOP,
        path_relations=["REFERS_TO", "REFERS_TO"],
    )
    missing_result = EvidenceSufficiencyPolicy().evaluate(missing)
    assert missing_result.sufficient is False
    assert missing_result.reason_code == "MULTI_HOP_REQUIREMENT_UNRESOLVED"
    assert EvidenceSufficiencyPolicy().evaluate(present).sufficient is True


def test_multi_hop_rejects_matching_relations_outside_satisfied_set() -> None:
    context = retrieval_context(
        intent=IntentType.MULTI_HOP,
        path_relations=["REFERS_TO", "REQUIRES"],
    )
    context.graph_paths = [
        graph_path(
            ["doc_art9", "doc_art2", "doc_art3"],
            ["REFERS_TO", "REQUIRES"],
        )
    ]

    result = EvidenceSufficiencyPolicy().evaluate(context)

    assert result.sufficient is False
    assert result.reason_code == "MISSING_MULTI_HOP_PATH"


def test_multi_hop_rejects_flipped_direction_outside_satisfied_set() -> None:
    context = retrieval_context(
        intent=IntentType.MULTI_HOP,
        path_relations=["REFERS_TO", "REQUIRES"],
    )
    original = context.graph_paths[0]
    context.graph_paths = [
        original.model_copy(
            update={
                "edges": tuple(
                    edge.model_copy(
                        update={
                            "source_id": edge.target_id,
                            "target_id": edge.source_id,
                        }
                    )
                    for edge in original.edges
                )
            }
        )
    ]

    result = EvidenceSufficiencyPolicy().evaluate(context)

    assert result.sufficient is False
    assert result.reason_code == "MISSING_MULTI_HOP_PATH"


def test_validity_requires_resolved_date_and_interval() -> None:
    missing = retrieval_context(intent=IntentType.VALIDITY)
    present = retrieval_context(intent=IntentType.VALIDITY, temporal=True)
    assert EvidenceSufficiencyPolicy().evaluate(missing).sufficient is False
    assert EvidenceSufficiencyPolicy().evaluate(present).sufficient is True


def test_comparison_requires_distinct_versions() -> None:
    context = retrieval_context(intent=IntentType.COMPARISON)
    result = EvidenceSufficiencyPolicy().evaluate(context)
    assert result.reason_code == "COMPARISON_RELATION_UNVERIFIED"
