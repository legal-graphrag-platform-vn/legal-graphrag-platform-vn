import json

import pytest

from src.retrieval.eval.benchmark import BenchmarkDatasetError, BenchmarkRunner
from src.retrieval.models import (
    IntentType,
    RetrievalContext,
    RetrievedUnit,
    TemporalQuery,
)


class FakeRetriever:
    def __init__(self, ids: list[str]) -> None:
        self._ids = ids

    def retrieve(self, query: str, *, top_k: int, final_k: int) -> RetrievalContext:
        units = [
            RetrievedUnit(
                id=unit_id,
                label="Article",
                content_raw="content",
                document_id="doc",
                citation_label="Điều 1",
            )
            for unit_id in self._ids[:final_k]
        ]
        return RetrievalContext(
            query=query,
            intent=IntentType.FACTUAL,
            temporal=TemporalQuery(has_temporal=False),
            retrieved_units=units,
            graph_paths=[],
            evidence=[],
            metrics={},
            retrieval_mode="vector_only",
        )


def test_benchmark_runs_variants_deterministically(tmp_path) -> None:
    dataset = tmp_path / "benchmark.json"
    dataset.write_text(
        json.dumps([{"query": "q", "expected_ids": ["relevant"]}]),
        encoding="utf-8",
    )
    runner = BenchmarkRunner(
        {
            "hybrid": FakeRetriever(["miss", "relevant"]),
            "vector": FakeRetriever(["relevant"]),
        }
    )

    result = runner.run(dataset, top_k=2)

    assert list(result) == ["hybrid", "vector"]
    assert result["vector"]["Recall@2"] == 1.0
    assert result["vector"]["MRR"] == 1.0
    assert result["hybrid"]["MRR"] == 0.5


def test_benchmark_rejects_empty_dataset(tmp_path) -> None:
    dataset = tmp_path / "benchmark.json"
    dataset.write_text("[]", encoding="utf-8")

    with pytest.raises(BenchmarkDatasetError):
        BenchmarkRunner({"vector": FakeRetriever([])}).run(dataset)
