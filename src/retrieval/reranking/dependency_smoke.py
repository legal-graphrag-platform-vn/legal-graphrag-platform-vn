"""Real-model dependency smoke test for the configured BGE reranker stack."""

from __future__ import annotations

import json
import math
from importlib.metadata import version

from FlagEmbedding import FlagReranker

from src.retrieval.models import RetrievedUnit
from src.retrieval.reranking.bge_reranker import BGEReranker


MODEL_NAME = "BAAI/bge-reranker-v2-m3"
EXPECTED_FLAG_EMBEDDING_VERSION = "1.4.0"
EXPECTED_TRANSFORMERS_VERSION = "4.57.6"
MAX_LENGTH = 512


def run_smoke() -> dict[str, object]:
    flag_embedding_version = version("FlagEmbedding")
    transformers_version = version("transformers")
    if flag_embedding_version != EXPECTED_FLAG_EMBEDDING_VERSION:
        raise RuntimeError(
            "Unexpected FlagEmbedding version: "
            f"{flag_embedding_version}; expected {EXPECTED_FLAG_EMBEDDING_VERSION}"
        )
    if transformers_version != EXPECTED_TRANSFORMERS_VERSION:
        raise RuntimeError(
            "Unexpected Transformers version: "
            f"{transformers_version}; expected {EXPECTED_TRANSFORMERS_VERSION}"
        )

    backend = FlagReranker(
        MODEL_NAME,
        use_fp16=False,
        max_length=MAX_LENGTH,
        normalize=True,
        devices="cpu",
    )
    pairs = [
        [
            "quyền thành lập doanh nghiệp",
            "Tổ chức, cá nhân có quyền thành lập và quản lý doanh nghiệp.",
        ],
        [
            "quyền thành lập doanh nghiệp",
            "Doanh nghiệp phải đăng ký thay đổi địa chỉ trụ sở.",
        ],
    ]
    single_scores = _score_list(backend.compute_score(pairs[0]))
    scores = _score_list(backend.compute_score(pairs))
    _validate_scores(single_scores, expected_count=1)
    _validate_scores(scores, expected_count=len(pairs))

    adapter = BGEReranker(MODEL_NAME, reranker=backend)
    units = [
        _unit("less_relevant", pairs[1][1]),
        _unit("more_relevant", pairs[0][1]),
    ]
    ranked = adapter.rerank(pairs[0][0], units, top_n=2)
    if [unit.id for unit in ranked] != ["more_relevant", "less_relevant"]:
        raise RuntimeError("Real-model reranker ordering did not match score order")

    return {
        "status": "PASS",
        "model": MODEL_NAME,
        "FlagEmbedding": flag_embedding_version,
        "transformers": transformers_version,
        "sentence_transformers": version("sentence-transformers"),
        "use_fp16": backend.use_fp16,
        "precision": "fp16" if backend.use_fp16 else "fp32",
        "max_length": backend.max_length,
        "normalize": backend.normalize,
        "single_score": single_scores[0],
        "pair_scores": scores,
        "ranked_ids": [unit.id for unit in ranked],
    }


def _score_list(scores: object) -> list[float]:
    if isinstance(scores, (float, int)):
        return [float(scores)]
    try:
        return [float(score) for score in scores]  # type: ignore[union-attr]
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Reranker returned an invalid score payload") from exc


def _validate_scores(scores: list[float], *, expected_count: int) -> None:
    if len(scores) != expected_count:
        raise RuntimeError(
            f"Expected {expected_count} reranker scores, received {len(scores)}"
        )
    if not all(math.isfinite(score) for score in scores):
        raise RuntimeError("Reranker returned a non-finite score")
    if not all(0.0 <= score <= 1.0 for score in scores):
        raise RuntimeError("Normalized reranker scores must be within [0, 1]")


def _unit(unit_id: str, content: str) -> RetrievedUnit:
    return RetrievedUnit(
        id=unit_id,
        label="Article",
        title=None,
        content_raw=content,
        document_id="smoke_document",
        citation_label=unit_id,
    )


def main() -> int:
    print(json.dumps(run_smoke(), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
