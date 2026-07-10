from __future__ import annotations

from unittest.mock import MagicMock, patch
from datetime import date

from src.parser.models import Article, DocumentInfo
from src.extraction.models import ExtractedEntity, ExtractedRelation, ExtractionResult
from src.pipeline.orchestrator import process_article


def test_process_article_temporal_relations_properties() -> None:
    # 1.   Prepare mock data for the Article and DocumentInfo
    article = Article(
        number=17,
        title="Điều kiện thành lập doanh nghiệp",
        content_raw="Khoản 1. Không được thành lập doanh nghiệp...",
    )
    document = DocumentInfo(
        id="ldn_2020",
        title="Luật Doanh nghiệp",
        number="59/2020/QH14",
        doc_type="Law",
        effective_from=date(2021, 1, 1),
    )

    # 2.   Prepare mock extraction result containing a temporal relation and other relations
    mock_entities = [
        ExtractedEntity(id="dieu_17", type="Article", label="Điều 17"),
        ExtractedEntity(id="dieu_18", type="Article", label="Điều 18"),
        ExtractedEntity(id="entity_cong_ty", type="Entity", label="Công ty"),
        ExtractedEntity(id="concept_von", type="Concept", label="Vốn"),
    ]
    mock_relations = [
        ExtractedRelation(
            head="dieu_17",
            relation="AMENDS",
            tail="dieu_18",
            evidence="Điều 18 sửa đổi Điều 17",
            confidence=0.9,
        ),
        ExtractedRelation(
            head="entity_cong_ty",
            relation="REQUIRES",
            tail="concept_von",
            evidence="Công ty phải có vốn",
            confidence=0.8,
        ),
        ExtractedRelation(
            head="dieu_17",
            relation="REFERS_TO",
            tail="dieu_18",
            evidence="Theo Điều 18 của Luật này",
            confidence=0.7,
        ),
    ]
    mock_result = ExtractionResult(
        article_number=17,
        entities=mock_entities,
        relations=mock_relations,
    )

    # 3.   Execute process_article with extract_article mocked
    with patch("src.pipeline.orchestrator.extract_article", return_value=mock_result):
        all_records = []
        process_article(article, document, all_records)

        # 4.   Verify that all relations were processed and logged correctly
        assert len(all_records) == 3

        # 5.   Check AMENDS relation properties and validation state
        amended_record = next(r for r in all_records if r["relation"]["relation"] == "AMENDS")
        assert amended_record["schema_valid"] is True
        assert amended_record["ontology_valid"] is True
        assert amended_record["relation"]["properties"]["effective_from"] == "2021-01-01"
        assert amended_record["relation"]["properties"]["source_doc_id"] == "ldn_2020"

        # 6.   Check REQUIRES relation properties
        requires_record = next(r for r in all_records if r["relation"]["relation"] == "REQUIRES")
        assert requires_record["relation"]["properties"]["source_article"] == "ldn_2020_art17"
        assert requires_record["relation"]["properties"]["confidence"] == 0.8
        assert requires_record["relation"]["properties"]["llm_model"] == "gemini:gemini-2.5-flash"
        assert requires_record["relation"]["properties"]["created_at"]

        # 7.   Check REFERS_TO citation properties
        refers_record = next(r for r in all_records if r["relation"]["relation"] == "REFERS_TO")
        assert refers_record["ontology_valid"] is True
        assert refers_record["relation"]["properties"]["citation_text"] == "Theo Điều 18 của Luật này"
        assert refers_record["relation"]["properties"]["citation_type"] == "DIRECT"
