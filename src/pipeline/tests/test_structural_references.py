from src.pipeline.extraction.corpus_structural_registry import (
    build_corpus_registry,
)
from src.pipeline.extraction.structural_context import StructuralRegistry
from src.pipeline.extraction.structural_references import StructuralReferenceResolver
from src.pipeline.parser.hierarchy_parser import canonicalize_source_text, parse_text
from src.pipeline.parser.models import DocumentInfo
from src.shared.ontology.validators import validate_graph_payload


def _document() -> DocumentInfo:
    return DocumentInfo(
        id="ldn_2020", title="Luật", number="59/2020/QH14", doc_type="Law"
    )


def _registry_build():
    def payload(document_id: str, number: str, article: str, clause: str, point: str):
        return validate_graph_payload(
            {
                "nodes": [
                    {
                        "type": "Document",
                        "id": document_id,
                        "number": number,
                        "doc_type": "Law",
                        "normative": True,
                        "legal_status": "ACTIVE",
                        "effective_from": "2021-01-01",
                        "issuer_name": "Quốc hội",
                    },
                    {
                        "type": "Article",
                        "id": f"{document_id}_art{article}",
                        "number": article,
                        "content_raw": "Điều",
                        "effective_from": "2021-01-01",
                        "legal_status": "ACTIVE",
                    },
                    {
                        "type": "Clause",
                        "id": f"{document_id}_art{article}_cl{clause}",
                        "number": clause,
                        "content_raw": "Khoản",
                        "effective_from": "2021-01-01",
                        "legal_status": "ACTIVE",
                    },
                    {
                        "type": "Point",
                        "id": f"{document_id}_art{article}_cl{clause}_p{point}",
                        "label": point,
                        "content_raw": "Điểm",
                    },
                ],
                "relations": [
                    {
                        "head_id": document_id,
                        "type": "CONTAINS",
                        "tail_id": f"{document_id}_art{article}",
                        "properties": {},
                    },
                    {
                        "head_id": f"{document_id}_art{article}",
                        "type": "CONTAINS",
                        "tail_id": f"{document_id}_art{article}_cl{clause}",
                        "properties": {},
                    },
                    {
                        "head_id": f"{document_id}_art{article}_cl{clause}",
                        "type": "CONTAINS",
                        "tail_id": f"{document_id}_art{article}_cl{clause}_p{point}",
                        "properties": {},
                    },
                ],
            }
        )

    return build_corpus_registry(
        {
            "L59": payload("ldn_2020", "59/2020/QH14", "1", "1", "a"),
            "L68": payload("ldn_2014", "68/2014/QH13", "35", "1", "m"),
        },
        {"L59": "source", "L68": "target"},
        build_id="test-registry",
    )


def test_resolves_multi_target_reference_atomically_and_preserves_d_dd() -> None:
    text = """Điều 1. Trách nhiệm
1. Khoản
a) Nghĩa vụ a;
b) Nghĩa vụ b;
d) Nghĩa vụ d;
đ) Nghĩa vụ đ;
c) Phải thực hiện các điểm a, b, d và đ khoản này.
"""
    parsed = parse_text(text, _document())
    registry = StructuralRegistry.from_parsed_document(parsed, "L59_2020")

    references = StructuralReferenceResolver(registry, text).resolve_article(
        parsed.articles[0]
    )

    assert len(references) == 1
    reference = references[0]
    assert reference.status == "RESOLVED"
    assert reference.target_unit_ids == (
        "ldn_2020_art1_cl1_pa",
        "ldn_2020_art1_cl1_pb",
        "ldn_2020_art1_cl1_pd",
        "ldn_2020_art1_cl1_pdd",
    )
    canonical = canonicalize_source_text(text)
    mention = reference.mention
    assert (
        canonical[mention.source_char_start : mention.source_char_end]
        == mention.raw_text
    )


def test_missing_one_target_rejects_the_whole_reference() -> None:
    text = """Điều 1. Trách nhiệm
1. Khoản
a) Nghĩa vụ a;
c) Theo các điểm a và b khoản này.
"""
    parsed = parse_text(text, _document())
    registry = StructuralRegistry.from_parsed_document(parsed, "L59_2020")

    reference = StructuralReferenceResolver(registry, text).resolve_article(
        parsed.articles[0]
    )[0]

    assert reference.status == "UNRESOLVED"
    assert reference.target_unit_ids == ()


def test_current_clause_self_reference_creates_no_edge() -> None:
    text = "Điều 1. Trách nhiệm\n1. Thực hiện theo khoản này."
    parsed = parse_text(text, _document())
    registry = StructuralRegistry.from_parsed_document(parsed, "L59_2020")

    reference = StructuralReferenceResolver(registry, text).resolve_article(
        parsed.articles[0]
    )[0]

    assert reference.status == "RESOLVED"
    assert reference.reference_scope == "LOCAL"
    assert reference.is_self_reference is True


def test_explicit_external_reference_never_falls_back_to_current_document() -> None:
    text = (
        "Điều 1. Chuyển tiếp\n1. Khoản\n"
        "a) Theo điểm m khoản 1 Điều 35 của Luật số 68/2014/QH13."
    )
    parsed = parse_text(text, _document())
    registry = StructuralRegistry.from_parsed_document(parsed, "L59_2020")
    build = _registry_build()

    reference = StructuralReferenceResolver(
        registry,
        text,
        corpus_registry=build.registry,
        registry_receipt=build.receipt,
    ).resolve_article(parsed.articles[0])[0]

    assert reference.status == "RESOLVED"
    assert reference.resolution_method == "ENTITY_LINKING"
    assert reference.target_unit_ids == ("ldn_2014_art35_cl1_pm",)
    assert reference.reference_scope == "EXTERNAL"
    assert reference.registry_evidence.snapshot_hash == build.registry.snapshot_hash


def test_unregistered_external_reference_is_unresolved_not_local() -> None:
    text = (
        "Điều 1. Chuyển tiếp\n1. Khoản\n"
        "a) Theo điểm m khoản 1 Điều 35 của Luật số 83/2015/QH13."
    )
    parsed = parse_text(text, _document())
    registry = StructuralRegistry.from_parsed_document(parsed, "L59_2020")

    reference = StructuralReferenceResolver(registry, text).resolve_article(
        parsed.articles[0]
    )[0]

    assert reference.status == "UNRESOLVED"
    assert reference.reference_scope == "EXTERNAL"
    assert reference.resolution_method == "ENTITY_LINKING"
    assert reference.target_unit_ids == ()


def test_article_89_resolves_point_chapter_and_section_targets() -> None:
    text = """Chương III
CÔNG TY TRÁCH NHIỆM HỮU HẠN
Mục 1. Công ty trách nhiệm hữu hạn hai thành viên trở lên
Điều 46. Công ty trách nhiệm hữu hạn hai thành viên trở lên
1. Nội dung.
Chương IV
DOANH NGHIỆP NHÀ NƯỚC
Điều 88. Áp dụng quy định đối với doanh nghiệp nhà nước
1. Doanh nghiệp nhà nước bao gồm:
a) Doanh nghiệp do Nhà nước nắm giữ 100% vốn điều lệ;
b) Doanh nghiệp do Nhà nước nắm giữ trên 50% vốn điều lệ.
Điều 89. Áp dụng quy định đối với doanh nghiệp nhà nước
1. Doanh nghiệp do Nhà nước nắm giữ 100% vốn điều lệ theo quy định tại điểm a khoản 1 Điều 88 của Luật này được tổ chức quản lý theo quy định tại Chương này và các quy định khác có liên quan của Luật này; trường hợp có sự khác nhau thì áp dụng quy định tại Chương này.
2. Doanh nghiệp do Nhà nước nắm giữ trên 50% vốn điều lệ theo quy định tại điểm b khoản 1 Điều 88 của Luật này được tổ chức quản lý theo các quy định tại Mục 1 Chương III hoặc công ty cổ phần theo các quy định tại Chương V của Luật này.
Chương V
CÔNG TY CỔ PHẦN
Điều 111. Công ty cổ phần
1. Nội dung.
"""
    parsed = parse_text(text, _document())
    registry = StructuralRegistry.from_parsed_document(parsed, "L59_2020")
    article89 = next(article for article in parsed.articles if article.number == "89")

    references = StructuralReferenceResolver(registry, text).resolve_article(article89)

    resolved_targets = [
        reference.target_unit_ids[0]
        for reference in references
        if reference.status == "RESOLVED"
    ]
    assert "ldn_2020_art88_cl1_pa" in resolved_targets
    assert "ldn_2020_art88_cl1_pb" in resolved_targets
    assert "ldn_2020_ch4" in resolved_targets
    assert "ldn_2020_ch3_sec1" in resolved_targets
    assert "ldn_2020_ch5" in resolved_targets
    assert not any(
        "các quy định khác có liên quan" in reference.mention.raw_text.lower()
        for reference in references
    )


def test_external_chapter_and_section_are_checkpointed_without_local_fallback() -> None:
    text = """Chương III
QUY ĐỊNH
Mục 1. Nội dung
Điều 1. Chuyển tiếp
1. Áp dụng Mục 1 Chương III Nghị định số 57/2026/NĐ-CP và Chương V của Nghị định 57/2026/NĐ-CP.
"""
    parsed = parse_text(text, _document())
    registry = StructuralRegistry.from_parsed_document(parsed, "L59_2020")

    references = StructuralReferenceResolver(registry, text).resolve_article(
        parsed.articles[0]
    )

    assert len(references) == 2
    section = next(
        item for item in references if item.target_candidate.target_type == "Section"
    )
    chapter = next(
        item for item in references if item.target_candidate.target_type == "Chapter"
    )
    assert section.status == chapter.status == "UNRESOLVED"
    assert (
        section.reason_code == chapter.reason_code == "target_document_not_in_snapshot"
    )
    assert section.target_unit_ids == chapter.target_unit_ids == ()
    assert section.target_candidate.model_dump() == {
        "target_type": "Section",
        "document_number": "57/2026/NĐ-CP",
        "chapter_number": "III",
        "section_number": "1",
        "article_number": None,
        "clause_number": None,
        "point_label": None,
    }
    assert chapter.target_candidate.model_dump() == {
        "target_type": "Chapter",
        "document_number": "57/2026/NĐ-CP",
        "chapter_number": "V",
        "section_number": None,
        "article_number": None,
        "clause_number": None,
        "point_label": None,
    }


def test_section_parent_mismatch_is_unresolved() -> None:
    text = """Chương II
CHƯƠNG HAI
Mục 1. Mục thật
Điều 1. Nội dung
1. Theo Mục 1 Chương III.
"""
    parsed = parse_text(text, _document())
    registry = StructuralRegistry.from_parsed_document(parsed, "L59_2020")

    reference = StructuralReferenceResolver(registry, text).resolve_article(
        parsed.articles[0]
    )[0]

    assert reference.status == "UNRESOLVED"
    assert reference.reason_code == "explicit_section_target_missing"
    assert reference.target_unit_ids == ()
