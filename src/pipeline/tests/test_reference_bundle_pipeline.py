import json

import pytest

from src.pipeline.extraction.structural_context import StructuralRegistry
from src.pipeline.extraction.structural_references import StructuralReferenceResolver
from src.pipeline.parser.hierarchy_parser import parse_text
from src.pipeline.parser.models import Article, DocumentInfo, ParsedDocument
from src.pipeline.pipeline.orchestrator import (
    _apply_atomic_bundle_decisions,
    _mark_llm_relations_superseded_by_rules,
    _rule_reference_records,
    _structural_type_from_id,
    _update_reference_checkpoints,
    run_pipeline,
)


def _fixture():
    text = """Điều 1. Trách nhiệm
1. Khoản
a) Nghĩa vụ a;
b) Nghĩa vụ b;
c) Theo các điểm a và b khoản này.
"""
    document = DocumentInfo(
        id="ldn_2020", title="Luật", number="59/2020/QH14", doc_type="Law"
    )
    parsed = parse_text(text, document)
    registry = StructuralRegistry.from_parsed_document(parsed, "L59_2020")
    references = StructuralReferenceResolver(registry, text).resolve_article(
        parsed.articles[0]
    )
    return registry, references


def test_rule_bundle_records_share_atomic_target_count(tmp_path) -> None:
    registry, references = _fixture()
    checkpoints = _update_reference_checkpoints(
        tmp_path / "references.jsonl",
        references,
        selected_article_ids={"ldn_2020_art1"},
    )

    records = _rule_reference_records(references, checkpoints, registry)

    assert len(records) == 2
    properties = [record["relation"]["properties"] for record in records]
    assert {item["reference_bundle_id"] for item in properties} == {
        references[0].mention.reference_bundle_id
    }
    assert {item["reference_target_count"] for item in properties} == {2}
    assert all(item["extraction_method"] == "RULE" for item in properties)


def test_atomic_decision_rejects_every_edge_when_one_edge_fails() -> None:
    bundle = "bundle-ab"
    records = [
        {
            "decision": "accepted",
            "relation": {
                "properties": {
                    "extraction_method": "RULE",
                    "reference_bundle_id": bundle,
                }
            },
        },
        {
            "decision": "rejected",
            "relation": {
                "properties": {
                    "extraction_method": "RULE",
                    "reference_bundle_id": bundle,
                }
            },
        },
    ]

    decided = _apply_atomic_bundle_decisions(records)

    assert {record["decision"] for record in decided} == {"rejected"}
    assert all(
        record["review_reason"] == "atomic_reference_bundle_validation_failed"
        for record in decided
    )


def test_deterministic_bundle_supersedes_broader_llm_target_for_same_mention() -> None:
    llm_record = {
        "relation": {
            "head": "ldn_2020_art57_cl1",
            "relation": "REFERS_TO",
            "tail": "ldn_2020_art49",
            "properties": {
                "extraction_method": "LLM",
                "citation_text": (
                    "Thành viên hoặc nhóm thành viên quy định tại khoản 2 và "
                    "khoản 3 Điều 49 của Luật này."
                ),
            },
        }
    }
    rule_records = [
        {
            "relation": {
                "head": "ldn_2020_art57_cl1",
                "relation": "REFERS_TO",
                "tail": target,
                "properties": {
                    "extraction_method": "RULE",
                    "citation_text": "khoản 2 và khoản 3 Điều 49",
                    "reference_bundle_id": "bundle-49",
                },
            }
        }
        for target in ("ldn_2020_art49_cl2", "ldn_2020_art49_cl3")
    ]

    _mark_llm_relations_superseded_by_rules([llm_record, *rule_records])

    assert llm_record["superseded_by_deterministic_resolution"] == "bundle-49"


def test_deterministic_reference_does_not_supersede_unrelated_llm_citation() -> None:
    llm_record = {
        "relation": {
            "head": "ldn_2020_art57_cl1",
            "relation": "REFERS_TO",
            "tail": "ldn_2020_art72",
            "properties": {
                "extraction_method": "LLM",
                "citation_text": "theo Điều 72 của Luật này",
            },
        }
    }
    rule_record = {
        "relation": {
            "head": "ldn_2020_art57_cl1",
            "relation": "REFERS_TO",
            "tail": "ldn_2020_art49_cl2",
            "properties": {
                "extraction_method": "RULE",
                "citation_text": "khoản 2 Điều 49",
                "reference_bundle_id": "bundle-49",
            },
        }
    }

    _mark_llm_relations_superseded_by_rules([llm_record, rule_record])

    assert "superseded_by_deterministic_resolution" not in llm_record


def test_deterministic_reference_does_not_match_empty_llm_citation() -> None:
    llm_record = {
        "relation": {
            "head": "ldn_2020_art57_cl1",
            "relation": "REFERS_TO",
            "tail": "ldn_2020_art49",
            "properties": {
                "extraction_method": "LLM",
                "citation_text": "",
            },
        }
    }
    rule_record = {
        "relation": {
            "head": "ldn_2020_art57_cl1",
            "relation": "REFERS_TO",
            "tail": "ldn_2020_art49_cl2",
            "properties": {
                "extraction_method": "RULE",
                "citation_text": "khoản 2 Điều 49",
                "reference_bundle_id": "bundle-49",
            },
        }
    }

    _mark_llm_relations_superseded_by_rules([llm_record, rule_record])

    assert "superseded_by_deterministic_resolution" not in llm_record


def test_run_pipeline_rejects_source_backed_hierarchy_without_spans(tmp_path) -> None:
    parsed = ParsedDocument(
        document=DocumentInfo(
            id="ldn_2020",
            title="Luật Doanh nghiệp",
            number="59/2020/QH14",
            doc_type="Law",
        ),
        articles=[Article(number="57", content_raw="Nội dung Điều 57")],
    )

    with pytest.raises(
        ValueError,
        match=(
            r"Hierarchy has no usable canonical source span for structural "
            r"unit\(s\): Article 57"
        ),
    ):
        run_pipeline(
            parsed,
            tmp_path,
            raw_doc_code="L59_2020",
            source_text="Điều 57. Triệu tập họp Hội đồng thành viên",
        )

    assert not (tmp_path / "L59_2020" / "article_extractions.jsonl").exists()


def test_run_pipeline_rejects_missing_nested_clause_span(tmp_path) -> None:
    text = "Điều 57. Triệu tập họp\n1. Nội dung khoản."
    document = DocumentInfo(
        id="ldn_2020",
        title="Luật Doanh nghiệp",
        number="59/2020/QH14",
        doc_type="Law",
    )
    parsed = parse_text(text, document)
    parsed.articles[0].clauses[0].source_end_char = 0

    with pytest.raises(ValueError, match=r"unit\(s\): Clause 57.1"):
        run_pipeline(
            parsed,
            tmp_path,
            raw_doc_code="L59_2020",
            source_text=text,
        )


def test_reference_checkpoint_reuses_created_at_for_unchanged_fingerprint(
    tmp_path,
) -> None:
    _, references = _fixture()
    path = tmp_path / "references.jsonl"
    first = _update_reference_checkpoints(
        path,
        references,
        selected_article_ids={"ldn_2020_art1"},
    )
    second = _update_reference_checkpoints(
        path,
        references,
        selected_article_ids={"ldn_2020_art1"},
    )

    bundle_id = references[0].mention.reference_bundle_id
    assert first[bundle_id].detected_at == second[bundle_id].detected_at
    assert first[bundle_id].mention_fingerprint == second[bundle_id].mention_fingerprint
    assert (
        len([line for line in path.read_text(encoding="utf-8").splitlines() if line])
        == 1
    )
    assert (
        json.loads(path.read_text(encoding="utf-8"))["reference_bundle_id"] == bundle_id
    )


def test_external_section_checkpoint_preserves_structured_candidate(tmp_path) -> None:
    text = (
        "Điều 1. Chuyển tiếp\n1. Áp dụng Mục 1 Chương III Nghị định số 57/2026/NĐ-CP."
    )
    document = DocumentInfo(
        id="ldn_2020", title="Luật", number="59/2020/QH14", doc_type="Law"
    )
    parsed = parse_text(text, document)
    registry = StructuralRegistry.from_parsed_document(parsed, "L59_2020")
    references = StructuralReferenceResolver(registry, text).resolve_article(
        parsed.articles[0]
    )

    _update_reference_checkpoints(
        tmp_path / "references.jsonl",
        references,
        selected_article_ids={"ldn_2020_art1"},
    )

    row = json.loads((tmp_path / "references.jsonl").read_text(encoding="utf-8"))
    assert row["resolution"]["status"] == "UNRESOLVED"
    assert row["reference"]["target_candidate"] == {
        "target_type": "Section",
        "document_number": "57/2026/NĐ-CP",
        "part_number": None,
        "chapter_number": "III",
        "section_number": "1",
        "subsection_number": None,
        "article_number": None,
        "clause_number": None,
        "point_label": None,
    }


def test_structural_type_inference_checks_section_before_chapter() -> None:
    assert _structural_type_from_id("ldn_2020_ch3_sec1_subsec1") == "Subsection"
    assert _structural_type_from_id("ldn_2020_ch3_sec1") == "Section"
    assert _structural_type_from_id("ldn_2020_ch3") == "Chapter"
    assert _structural_type_from_id("ldn_2020_part1") == "Part"
