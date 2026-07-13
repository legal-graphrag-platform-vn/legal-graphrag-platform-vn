from datetime import date

import pytest

from src.retrieval.mapping import RetrievalRecordError, map_retrieved_unit


def test_clause_mapping_builds_attribution_citation_and_deep_link() -> None:
    unit = map_retrieved_unit(
        {
            "id": "law_art5_cl1",
            "label": "Clause",
            "content_raw": "Nội dung",
            "article_number": "5",
            "clause_number": "1",
            "document_id": "law",
            "document_number": "59/2020/QH14",
            "effective_from": date(2021, 1, 1),
            "score": 0.8,
        },
        score_field="vector_score",
    )

    assert unit.citation_label == "Điều 5, Khoản 1, 59/2020/QH14"
    assert unit.deep_link == "/documents/law/units/law_art5_cl1"
    assert unit.retrieval_sources == ["vector"]


def test_mapping_rejects_missing_document_attribution() -> None:
    with pytest.raises(RetrievalRecordError, match="document_id"):
        map_retrieved_unit({"id": "x", "label": "Article"})
