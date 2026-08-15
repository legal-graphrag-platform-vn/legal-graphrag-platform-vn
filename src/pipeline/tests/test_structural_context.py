from __future__ import annotations

from datetime import date

import json

import pytest
from pydantic import ValidationError

from src.pipeline.extraction.structural_context import (
    DocumentRegistry,
    StructuralRegistry,
)
from src.pipeline.parser.models import (
    Article,
    Clause,
    DocumentInfo,
    ParsedDocument,
    Part,
    Point,
    Section,
    Subsection,
)


def _parsed() -> ParsedDocument:
    return ParsedDocument(
        document=DocumentInfo(
            id="ldn_2020",
            title="Luật Doanh nghiệp",
            number="59/2020/QH14",
            doc_type="Law",
            effective_from=date(2021, 1, 1),
            issuer_name="Quốc hội",
        ),
        articles=[
            Article(
                number=5,
                content_raw="Điều 5",
                clauses=[
                    Clause(
                        number=1,
                        content="Khoản 1",
                        points=[
                            Point(label="d", content="d"),
                            Point(label="đ", content="đ"),
                        ],
                    )
                ],
            ),
            Article(
                number=53,
                content_raw="Điều 53",
                clauses=[Clause(number=2, content="Khoản 2")],
            ),
        ],
    )


def test_registry_builds_canonical_context_and_preserves_d_dd() -> None:
    parsed = _parsed()
    registry = StructuralRegistry.from_parsed_document(parsed, "L59_2020")
    context = registry.context_for_article(parsed.articles[0])

    assert context.article_id == "ldn_2020_art5"
    assert context.clause_ids["1"] == "ldn_2020_art5_cl1"
    assert context.point_ids[("1", "d")] == "ldn_2020_art5_cl1_pd"
    assert context.point_ids[("1", "đ")] == "ldn_2020_art5_cl1_pdd"


def test_registry_resolves_legal_labels_not_ambiguous_raw_aliases() -> None:
    registry = StructuralRegistry.from_parsed_document(_parsed(), "L59_2020")

    clause = registry.resolve(
        "khoan_1_1", current_article=5, entity_type="Clause", entity_label="Khoản 1"
    )
    cross_article = registry.resolve(
        "bad_alias",
        current_article=5,
        entity_type="Clause",
        entity_label="Khoản 2 Điều 53",
    )
    ambiguous = registry.resolve("khoan_x_2", current_article=5)

    assert clause.canonical_id == "ldn_2020_art5_cl1"
    assert cross_article.canonical_id == "ldn_2020_art53_cl2"
    assert ambiguous.status == "rejected"


def test_registry_resolves_current_document_reference() -> None:
    registry = StructuralRegistry.from_parsed_document(_parsed(), "L59_2020")
    result = registry.resolve(
        "luat_nay", current_article=5, entity_type="Document", entity_label="Luật này"
    )
    assert result.canonical_id == "ldn_2020"


def test_registry_indexes_section_under_exact_chapter_parent() -> None:
    parsed = _parsed()
    parsed.sections = [
        Section(number="1", title="Công ty trách nhiệm hữu hạn", chapter="III")
    ]
    parsed.articles[0].chapter = "III"
    parsed.articles[0].section = "1"

    registry = StructuralRegistry.from_parsed_document(parsed, "L59_2020")

    assert registry.chapters["III"] == "ldn_2020_ch3"
    assert registry.sections[("III", "1")] == "ldn_2020_ch3_sec1"
    assert registry.section_for_article_id("ldn_2020_art5") == "ldn_2020_ch3_sec1"
    resolved = registry.resolve(
        "muc_1_chuong_3",
        current_article="5",
        entity_type="Section",
        entity_label="Mục 1 Chương III",
    )
    assert resolved.canonical_id == "ldn_2020_ch3_sec1"


def test_registry_indexes_duplicate_local_section() -> None:
    parsed = _parsed()
    parsed.sections = [
        Section(number="1", title="Tên một", chapter="III"),
        Section(number="1", title="Tên hai", chapter="III"),
    ]
    parsed.articles[0].chapter = "III"
    parsed.articles[0].section = "1"
    registry = StructuralRegistry(parsed, "L59_2020")
    assert ("III", "1") in registry.sections


def test_registry_indexes_part_and_subsection_ancestors() -> None:
    parsed = _parsed()
    parsed.parts = [Part(number="I", title="Quy định chung")]
    parsed.sections = [Section(number="1", title="Phạm vi", chapter="I", part="I")]
    parsed.subsections = [
        Subsection(
            number="1a",
            title="Nguyên tắc",
            chapter="I",
            section="1",
            part="I",
        )
    ]
    parsed.articles[0].part = "I"
    parsed.articles[0].chapter = "I"
    parsed.articles[0].section = "1"
    parsed.articles[0].subsection = "1a"

    registry = StructuralRegistry.from_parsed_document(parsed, "L59_2020")

    assert registry.parts["1"] == "ldn_2020_part1"
    assert registry.subsections[("I", "1", "1a")] == ("ldn_2020_ch1_sec1_subsec1a")
    assert registry.part_for_article_id("ldn_2020_art5") == "ldn_2020_part1"
    assert registry.subsection_for_article_id("ldn_2020_art5") == (
        "ldn_2020_ch1_sec1_subsec1a"
    )
    assert (
        registry.resolve(
            "part_current",
            current_article="5",
            entity_type="Part",
            entity_label="Phần này",
        ).canonical_id
        == "ldn_2020_part1"
    )
    assert (
        registry.resolve(
            "subsection",
            current_article="5",
            entity_type="Subsection",
            entity_label="Tiểu mục 1a Mục 1 Chương I",
        ).canonical_id
        == "ldn_2020_ch1_sec1_subsec1a"
    )


def test_document_registry_resolves_explicit_curated_number(tmp_path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "raw_doc_code": "ND01_2021",
                        "graph_id": "nd_01_2021",
                        "number": "01/2021/NĐ-CP",
                        "doc_type": "Decree",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    registry = DocumentRegistry.from_manifest(manifest)
    assert registry.resolve("nghi_dinh_01", "Nghị định 01/2021/NĐ-CP") == (
        "nd_01_2021",
        "Decree",
    )
    assert registry.resolve("nghi_dinh", "Nghị định") is None
