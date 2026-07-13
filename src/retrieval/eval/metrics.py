import math
from typing import List


def calculate_recall_at_k(
    retrieved_ids: List[str], relevant_ids: List[str], k: int
) -> float:
    """
    Tính Recall@K: Tỉ lệ số lượng tài liệu liên quan được tìm thấy trong top K trên tổng số tài liệu liên quan.
    """
    if not relevant_ids:
        return 0.0

    top_k_retrieved = retrieved_ids[:k]
    hits = sum(1 for rid in relevant_ids if rid in top_k_retrieved)
    return hits / len(relevant_ids)


def calculate_mrr(retrieved_ids: List[str], relevant_ids: List[str]) -> float:
    """
    Tính MRR (Mean Reciprocal Rank): Dựa trên thứ hạng của tài liệu liên quan ĐẦU TIÊN xuất hiện trong kết quả.
    """
    if not relevant_ids:
        return 0.0

    for rank, doc_id in enumerate(retrieved_ids, start=1):
        if doc_id in relevant_ids:
            return 1.0 / rank

    return 0.0


def calculate_ndcg_at_k(
    retrieved_ids: List[str], relevant_ids: List[str], k: int
) -> float:
    """
    Tính nDCG@K (Normalized Discounted Cumulative Gain).
    Giả định relevance_score = 1 nếu tài liệu nằm trong relevant_ids, ngược lại = 0.
    """
    if not relevant_ids:
        return 0.0

    top_k_retrieved = retrieved_ids[:k]

    dcg = 0.0
    for i, doc_id in enumerate(top_k_retrieved):
        rel = 1.0 if doc_id in relevant_ids else 0.0
        dcg += rel / math.log2(i + 2)  # i=0 -> log2(2)=1

    # Tính IDCG (Ideal DCG)
    idcg = 0.0
    ideal_retrieved = relevant_ids[:k]
    for i, _ in enumerate(ideal_retrieved):
        idcg += 1.0 / math.log2(i + 2)

    if idcg == 0.0:
        return 0.0

    return dcg / idcg


def calculate_graded_ndcg_at_k(
    retrieved_ids: list[str], relevance_by_id: dict[str, int], k: int
) -> float:
    """Calculate nDCG@K from explicit integer relevance judgements."""
    if not relevance_by_id:
        return 0.0

    gains = [relevance_by_id.get(unit_id, 0) for unit_id in retrieved_ids[:k]]
    dcg = sum(
        ((2**relevance) - 1) / math.log2(index + 2)
        for index, relevance in enumerate(gains)
    )
    ideal = sorted(relevance_by_id.values(), reverse=True)[:k]
    idcg = sum(
        ((2**relevance) - 1) / math.log2(index + 2)
        for index, relevance in enumerate(ideal)
    )
    return dcg / idcg if idcg else 0.0


def calculate_grouped_graded_ndcg_at_k(
    retrieved_group_ids: list[str],
    returned_relevance_by_group: dict[str, int],
    ideal_relevance_by_group: dict[str, int],
    k: int,
) -> float:
    """Calculate grouped nDCG using grades of units actually retrieved."""
    if not ideal_relevance_by_group:
        return 0.0

    gains = [
        returned_relevance_by_group.get(group_id, 0)
        for group_id in retrieved_group_ids[:k]
    ]
    dcg = sum(
        ((2**relevance) - 1) / math.log2(index + 2)
        for index, relevance in enumerate(gains)
    )
    ideal = sorted(ideal_relevance_by_group.values(), reverse=True)[:k]
    idcg = sum(
        ((2**relevance) - 1) / math.log2(index + 2)
        for index, relevance in enumerate(ideal)
    )
    return dcg / idcg if idcg else 0.0
