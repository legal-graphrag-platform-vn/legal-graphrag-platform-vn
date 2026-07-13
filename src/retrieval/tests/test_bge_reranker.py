import pytest

from src.retrieval.models import RetrievedUnit
from src.retrieval.reranking.bge_reranker import BGEReranker


class StubFlagReranker:
    def __init__(self, scores: list[float]) -> None:
        self.scores = scores
        self.calls: list[tuple[list[list[str]], dict[str, object]]] = []

    def compute_score(
        self,
        pairs: list[list[str]],
        **kwargs: object,
    ) -> list[float]:
        self.calls.append((pairs, kwargs))
        return self.scores


def _unit(unit_id: str, content: str) -> RetrievedUnit:
    return RetrievedUnit(
        id=unit_id,
        label="Article",
        title=None,
        content_raw=content,
        document_id="ldn_2020",
        citation_label=unit_id,
    )


def test_reranker_uses_flag_reranker_pairs_and_orders_scores() -> None:
    flag_reranker = StubFlagReranker([0.2, 0.9])
    reranker = BGEReranker("unused", reranker=flag_reranker)
    units = [_unit("article_b", "second"), _unit("article_a", "first")]

    result = reranker.rerank("query", units, top_n=2)

    assert [unit.id for unit in result] == ["article_a", "article_b"]
    assert [unit.final_score for unit in result] == [0.9, 0.2]
    assert flag_reranker.calls == [
        (
            [["query", "second"], ["query", "first"]],
            {},
        )
    ]


def test_reranker_uses_unit_id_as_stable_tie_break() -> None:
    reranker = BGEReranker("unused", reranker=StubFlagReranker([0.5, 0.5]))
    units = [_unit("article_b", "second"), _unit("article_a", "first")]

    result = reranker.rerank("query", units, top_n=2)

    assert [unit.id for unit in result] == ["article_a", "article_b"]


def test_reranker_rejects_score_count_mismatch() -> None:
    reranker = BGEReranker("unused", reranker=StubFlagReranker([0.5]))
    units = [_unit("article_a", "first"), _unit("article_b", "second")]

    with pytest.raises(RuntimeError, match="score count"):
        reranker.rerank("query", units)


def test_reranker_rejects_invalid_max_length() -> None:
    with pytest.raises(ValueError, match="max_length"):
        BGEReranker("unused", max_length=0, reranker=StubFlagReranker([]))
