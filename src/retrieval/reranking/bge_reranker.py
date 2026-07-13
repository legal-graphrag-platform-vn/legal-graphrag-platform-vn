"""Optional BGE cross-encoder reranker adapter."""

from typing import Any

from src.retrieval.models import RetrievedUnit
from src.retrieval.reranking.base import BaseReranker


class BGEReranker(BaseReranker):
    def __init__(
        self,
        model_name: str,
        *,
        use_fp16: bool = False,
        reranker: Any | None = None,
    ) -> None:
        if reranker is None:
            try:
                from FlagEmbedding import FlagReranker
            except ImportError as exc:
                raise RuntimeError(
                    "Install the embedding dependency group to use BGE reranking"
                ) from exc
            reranker = FlagReranker(model_name, use_fp16=use_fp16)
        self._reranker = reranker

    def rerank(
        self, query: str, units: list[RetrievedUnit], top_n: int = 10
    ) -> list[RetrievedUnit]:
        if top_n < 1:
            raise ValueError("top_n must be positive")
        if not units:
            return []

        scores = self._reranker.compute_score(
            [[query, unit.content_raw] for unit in units]
        )
        normalized_scores = [scores] if isinstance(scores, (float, int)) else scores
        if len(normalized_scores) != len(units):
            raise RuntimeError(
                "Reranker returned a score count that does not match inputs"
            )

        for unit, score in zip(units, normalized_scores, strict=True):
            unit.rerank_score = float(score)
            unit.final_score = unit.rerank_score
        return sorted(
            units,
            key=lambda unit: (
                -(unit.final_score if unit.final_score is not None else float("-inf")),
                unit.id,
            ),
        )[:top_n]
