from __future__ import annotations

from datetime import date
from unittest.mock import patch

from src.pipeline.extraction.models import ExtractionResult
from src.pipeline.parser.models import Article, DocumentInfo, ParsedDocument
from src.pipeline.pipeline.orchestrator import run_pipeline


def test_run_pipeline_writes_decision_files_under_raw_doc_code(tmp_path) -> None:
    parsed = ParsedDocument(
        document=DocumentInfo(
            id="ldn_2020",
            title="Luật Doanh nghiệp",
            number="59/2020/QH14",
            doc_type="Law",
            normative=True,
            legal_status="ACTIVE",
            effective_from=date(2021, 1, 1),
            issuer_name="Quốc hội",
        ),
        articles=[Article(number=17, title="Quyền", content_raw="Nội dung điều 17")],
    )

    with patch(
        "src.pipeline.pipeline.orchestrator.extract_article",
        return_value=ExtractionResult(article_number=17, entities=[], relations=[]),
    ):
        run_pipeline(parsed, tmp_path, raw_doc_code="LDN2020")

    assert (tmp_path / "LDN2020" / "accepted.jsonl").exists()
    assert (tmp_path / "LDN2020" / "entity_index.json").exists()
    assert not (tmp_path / "ldn_2020" / "accepted.jsonl").exists()
