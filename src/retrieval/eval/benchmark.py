"""Deterministic retrieval benchmark and ablation runner."""

import json
from pathlib import Path
from typing import Protocol

from src.retrieval.eval.metrics import (
    calculate_mrr,
    calculate_ndcg_at_k,
    calculate_recall_at_k,
)
from src.retrieval.models import RetrievalContext


class RetrieverProtocol(Protocol):
    def retrieve(self, query: str, *, top_k: int, final_k: int) -> RetrievalContext: ...


class BenchmarkDatasetError(ValueError):
    """Raised when retrieval benchmark data does not satisfy the evaluation contract."""


class BenchmarkRunner:
    def __init__(self, retrievers: dict[str, RetrieverProtocol]):
        if not retrievers:
            raise ValueError("At least one retrieval variant is required")
        self._retrievers = retrievers

    def run(
        self, dataset_path: str | Path, top_k: int = 5
    ) -> dict[str, dict[str, float]]:
        dataset = _load_dataset(dataset_path)
        return {
            variant: _evaluate(retriever, dataset, top_k)
            for variant, retriever in sorted(self._retrievers.items())
        }


def _load_dataset(dataset_path: str | Path) -> list[dict[str, object]]:
    with Path(dataset_path).open(encoding="utf-8") as stream:
        payload = json.load(stream)
    if not isinstance(payload, list) or not payload:
        raise BenchmarkDatasetError("Benchmark dataset must be a non-empty JSON list")
    for index, item in enumerate(payload):
        if not isinstance(item, dict) or not str(item.get("query", "")).strip():
            raise BenchmarkDatasetError(f"Benchmark item {index} has no query")
        expected_ids = item.get("expected_ids")
        if not isinstance(expected_ids, list) or not expected_ids:
            raise BenchmarkDatasetError(f"Benchmark item {index} has no expected_ids")
    return payload


def _evaluate(
    retriever: RetrieverProtocol,
    dataset: list[dict[str, object]],
    top_k: int,
) -> dict[str, float]:
    totals = {"recall": 0.0, "mrr": 0.0, "ndcg": 0.0}
    for item in dataset:
        query = str(item["query"])
        expected_ids = [str(value) for value in item["expected_ids"]]
        context = retriever.retrieve(query, top_k=max(top_k, 20), final_k=top_k)
        retrieved_ids = [unit.id for unit in context.retrieved_units]
        totals["recall"] += calculate_recall_at_k(retrieved_ids, expected_ids, k=top_k)
        totals["mrr"] += calculate_mrr(retrieved_ids, expected_ids)
        totals["ndcg"] += calculate_ndcg_at_k(retrieved_ids, expected_ids, k=top_k)
    count = len(dataset)
    return {
        f"Recall@{top_k}": totals["recall"] / count,
        "MRR": totals["mrr"] / count,
        f"nDCG@{top_k}": totals["ndcg"] / count,
        "Total_Queries": float(count),
    }
