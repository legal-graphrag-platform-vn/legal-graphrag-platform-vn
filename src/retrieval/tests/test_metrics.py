from src.retrieval.eval.metrics import (
    calculate_graded_ndcg_at_k,
    calculate_grouped_graded_ndcg_at_k,
)


def test_calculate_graded_ndcg_at_k_respects_relevance_grade() -> None:
    relevance = {"direct": 3, "supporting": 1}

    ideal = calculate_graded_ndcg_at_k(["direct", "supporting"], relevance, k=2)
    reversed_ranking = calculate_graded_ndcg_at_k(
        ["supporting", "direct"], relevance, k=2
    )

    assert ideal == 1.0
    assert reversed_ranking < ideal


def test_grouped_ndcg_does_not_promote_parent_to_clause_grade() -> None:
    group_id = "legal_basis:ldn_2020_art17"
    ideal_relevance = {group_id: 3}

    parent_only = calculate_grouped_graded_ndcg_at_k(
        [group_id], {group_id: 2}, ideal_relevance, k=5
    )
    clause_only = calculate_grouped_graded_ndcg_at_k(
        [group_id], {group_id: 3}, ideal_relevance, k=5
    )

    assert parent_only < clause_only
    assert clause_only == 1.0
