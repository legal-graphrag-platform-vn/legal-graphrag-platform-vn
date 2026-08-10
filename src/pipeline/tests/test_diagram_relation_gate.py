from __future__ import annotations

from datetime import date
import json
from unittest.mock import patch

from src.pipeline.config import settings
from src.pipeline.extraction.document_relation_resolver import (
    ResolvedDiagramRelation,
    UnresolvedDiagramRelation,
    build_diagram_records,
)
from src.pipeline.extraction.models import ExtractionResult
from src.pipeline.extraction.structural_context import DocumentRegistry
from src.pipeline.parser.models import Article, DocumentInfo, ParsedDocument
from src.pipeline.pipeline.orchestrator import (
    _apply_decision_gate,
    _validate_diagram_records,
    run_pipeline,
)


def _diagram_record(
    *,
    head: str,
    relation: str,
    tail: str,
    category: str = "Văn bản được thay thế",
    current_document_id: str = "ldn_2020",
) -> dict:
    records = build_diagram_records(
        [
            ResolvedDiagramRelation(
                head_id=head,
                relation_type=relation,
                tail_id=tail,
                source_category=category,
                raw_target=tail,
                resolved=True,
            )
        ],
        [],
        current_document_id,
    )
    return records[0]


def test_diagram_temporal_relation_from_current_document_is_validated() -> None:
    document = DocumentInfo(
        id="ldn_2020",
        title="Luật Doanh nghiệp",
        number="59/2020/QH14",
        doc_type="Law",
        effective_from=date(2021, 1, 1),
    )
    registry = DocumentRegistry({"ldn2014": ("ldn_2014", "Law")})
    record = _diagram_record(head="ldn_2020", relation="REPLACES", tail="ldn_2014")

    validated = _validate_diagram_records(
        [record], current_document=document, registry=registry
    )[0]
    decided = _apply_decision_gate(validated)

    assert validated["relation"]["properties"]["effective_from"] == "2021-01-01"
    assert validated["schema_valid"] is True
    assert validated["ontology_valid"] is True
    assert validated["consistency_valid"] is True
    assert decided["decision"] == "accepted"


def test_diagram_temporal_relation_from_external_document_requires_review() -> None:
    document = DocumentInfo(
        id="ldn_2020",
        title="Luật Doanh nghiệp",
        number="59/2020/QH14",
        doc_type="Law",
        effective_from=date(2021, 1, 1),
    )
    registry = DocumentRegistry({"ldn2025": ("ldn_2025", "Law")})
    record = _diagram_record(head="ldn_2025", relation="AMENDS", tail="ldn_2020")

    validated = _validate_diagram_records(
        [record], current_document=document, registry=registry
    )[0]
    decided = _apply_decision_gate(validated)

    assert "effective_from" not in validated["relation"]["properties"]
    assert validated["ontology_valid"] is False
    assert validated["review_reason"] == "temporal_metadata_incomplete"
    assert validated["blocking"] is True
    assert decided["decision"] == "review"


def test_diagram_guides_relation_still_enforces_document_type_whitelist() -> None:
    document = DocumentInfo(
        id="tt_01_2021",
        title="Thông tư 01/2021",
        number="01/2021/TT-BKHDT",
        doc_type="Circular",
    )
    registry = DocumentRegistry({"ldn2020": ("ldn_2020", "Law")})
    record = _diagram_record(
        head="tt_01_2021",
        relation="GUIDES",
        tail="ldn_2020",
        category="Văn bản quy định chi tiết, hướng dẫn thi hành",
        current_document_id="tt_01_2021",
    )

    validated = _validate_diagram_records(
        [record], current_document=document, registry=registry
    )[0]
    decided = _apply_decision_gate(validated)

    assert validated["ontology_valid"] is False
    assert validated["ontology_error"] == "GUIDES does not allow Circular -> Law"
    assert decided["decision"] == "rejected"


def test_unresolved_diagram_target_is_reviewed_but_never_accepted() -> None:
    unresolved = UnresolvedDiagramRelation(
        raw_target="Luật chưa biết",
        source_category="Văn bản được thay thế",
        relation_type="REPLACES",
        direction="CURRENT_TO_TARGET",
        current_document_id="ldn_2020",
    )
    record = build_diagram_records([], [unresolved], "ldn_2020")[0]
    document = DocumentInfo(
        id="ldn_2020",
        title="Luật Doanh nghiệp",
        number="59/2020/QH14",
        doc_type="Law",
    )

    validated = _validate_diagram_records(
        [record], current_document=document, registry=DocumentRegistry({})
    )[0]
    decided = _apply_decision_gate(validated)

    assert validated["ontology_valid"] is False
    assert decided["decision"] == "review"
    assert decided["blocking"] is True


def test_diagram_record_with_invalid_schema_is_rejected_before_review() -> None:
    record = _diagram_record(head="ldn_2020", relation="REPLACES", tail="ldn_2014")
    record["relation"] = {**record["relation"], "head": None}
    document = DocumentInfo(
        id="ldn_2020",
        title="Luật Doanh nghiệp",
        number="59/2020/QH14",
        doc_type="Law",
        effective_from=date(2021, 1, 1),
    )
    registry = DocumentRegistry({"ldn2014": ("ldn_2014", "Law")})

    validated = _validate_diagram_records(
        [record], current_document=document, registry=registry
    )[0]
    decided = _apply_decision_gate(validated)

    assert validated["schema_valid"] is False
    assert validated["ontology_error"] == "diagram_schema_invalid"
    assert decided["decision"] == "rejected"


def test_run_pipeline_persists_only_validated_diagram_relation(tmp_path) -> None:
    manifest = tmp_path / "curated.json"
    manifest.write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "raw_doc_code": "L68_2014",
                        "graph_id": "ldn_2014",
                        "number": "68/2014/QH13",
                        "doc_type": "Law",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    parsed = ParsedDocument(
        document=DocumentInfo(
            id="ldn_2020",
            title="Luật Doanh nghiệp",
            number="59/2020/QH14",
            doc_type="Law",
            effective_from=date(2021, 1, 1),
        ),
        articles=[Article(number="1", content_raw="Điều 1")],
    )
    extraction = ExtractionResult(article_number="1", entities=[], relations=[])

    with (
        patch.object(settings, "curated_manifest_path", manifest),
        patch.object(settings, "extraction_max_workers", 1),
        patch(
            "src.pipeline.pipeline.orchestrator.extract_article",
            return_value=extraction,
        ),
    ):
        run_pipeline(
            parsed,
            tmp_path,
            raw_doc_code="L59_2020",
            diagram={"Văn bản được thay thế (1)": ["68/2014/QH13"]},
        )

    accepted = [
        json.loads(line)
        for line in (tmp_path / "L59_2020" / "accepted.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    diagram_record = next(
        record for record in accepted if record["extraction_method"] == "DIAGRAM"
    )
    assert diagram_record["relation"]["relation"] == "REPLACES"
    assert diagram_record["relation"]["properties"]["effective_from"] == "2021-01-01"
    assert diagram_record["ontology_valid"] is True
    assert diagram_record["consistency_valid"] is True
