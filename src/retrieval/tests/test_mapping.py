from datetime import date

import pytest

from src.retrieval.mapping import RetrievalRecordError, map_retrieved_unit


def test_clause_mapping_builds_attribution_citation_and_deep_link() -> None:
    unit = map_retrieved_unit(
        {
            "id": "law_art5_cl1",
            "label": "Clause",
            "content_raw": "Nội dung",
            "article_id": "law_art5",
            "clause_id": "law_art5_cl1",
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
    assert unit.article_id == "law_art5"
    assert unit.clause_id == "law_art5_cl1"
    assert unit.retrieval_sources == ["vector"]


def test_appendix_mapping_does_not_require_article_ancestry() -> None:
    unit = map_retrieved_unit(
        {
            "id": "tt_demo_appi",
            "label": "Appendix",
            "appendix_number": "I",
            "content_raw": "Nội dung Phụ lục",
            "document_id": "tt_demo",
            "document_number": "01/2026/TT-DEMO",
            "effective_from": date(2026, 1, 1),
            "score": 0.8,
        },
        score_field="vector_score",
    )

    assert unit.article_id is None
    assert unit.citation_label == "Phụ lục I, 01/2026/TT-DEMO"
    assert unit.deep_link == "/documents/tt_demo/units/tt_demo_appi"


def test_document_mapping_supports_canonical_temporal_evidence() -> None:
    unit = map_retrieved_unit(
        {
            "id": "l_68_2014",
            "label": "Document",
            "content_raw": "Luật Doanh nghiệp số 68/2014/QH13",
            "document_id": "l_68_2014",
            "document_number": "68/2014/QH13",
            "effective_from": date(2015, 7, 1),
            "effective_to": date(2021, 1, 1),
            "legal_status": "EXPIRED",
            "score": 1.0,
        },
        score_field="graph_score",
    )

    assert unit.article_id is None
    assert unit.citation_label == "Văn bản, 68/2014/QH13"
    assert unit.deep_link == "/documents/l_68_2014/units/l_68_2014"
    assert unit.effective_to == date(2021, 1, 1)


def test_mapping_rejects_missing_document_attribution() -> None:
    with pytest.raises(RetrievalRecordError, match="document_id"):
        map_retrieved_unit({"id": "x", "label": "Article"})
