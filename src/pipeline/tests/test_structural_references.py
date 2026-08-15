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

    grouping_payload = validate_graph_payload(
        {
            "nodes": [
                {
                    "type": "Document",
                    "id": "nd34_2016",
                    "number": "34/2016/NĐ-CP",
                    "doc_type": "Decree",
                    "normative": True,
                    "legal_status": "ACTIVE",
                    "effective_from": "2016-07-01",
                    "issuer_name": "Chính phủ",
                },
                {
                    "type": "Part",
                    "id": "nd34_2016_part2",
                    "number": "II",
                    "title": "Phần hai",
                },
                {
                    "type": "Chapter",
                    "id": "nd34_2016_ch5",
                    "number": "V",
                    "title": "Chương năm",
                },
                {
                    "type": "Section",
                    "id": "nd34_2016_ch5_sec3",
                    "number": "3",
                    "title": "Mục ba",
                },
                {
                    "type": "Subsection",
                    "id": "nd34_2016_ch5_sec3_subsec1",
                    "number": "1",
                    "title": "Tiểu mục một",
                },
                {
                    "type": "Article",
                    "id": "nd34_2016_art77",
                    "number": "77",
                    "content_raw": "Điều 77",
                    "effective_from": "2016-07-01",
                    "legal_status": "ACTIVE",
                },
            ],
            "relations": [
                {"head_id": head, "type": "CONTAINS", "tail_id": tail, "properties": {}}
                for head, tail in (
                    ("nd34_2016", "nd34_2016_part2"),
                    ("nd34_2016_part2", "nd34_2016_ch5"),
                    ("nd34_2016_ch5", "nd34_2016_ch5_sec3"),
                    ("nd34_2016_ch5_sec3", "nd34_2016_ch5_sec3_subsec1"),
                    ("nd34_2016_ch5_sec3_subsec1", "nd34_2016_art77"),
                )
            ],
        }
    )
    appendix_payload = validate_graph_payload(
        {
            "nodes": [
                {
                    "type": "Document",
                    "id": "tt20_2015",
                    "number": "20/2015/TT-BKHĐT",
                    "doc_type": "Circular",
                    "normative": True,
                    "legal_status": "ACTIVE",
                    "effective_from": "2016-01-01",
                    "issuer_name": "Bộ Kế hoạch và Đầu tư",
                },
                {
                    "type": "Appendix",
                    "id": "tt20_2015_appvii_2",
                    "scope": "vii_2",
                    "number": "VII-2",
                    "heading": "PHỤ LỤC VII-2",
                    "content_raw": "Danh mục mã",
                    "appendix_kind": "LIST",
                    "effective_from": "2016-01-01",
                    "legal_status": "ACTIVE",
                },
            ],
            "relations": [
                {
                    "head_id": "tt20_2015",
                    "type": "CONTAINS",
                    "tail_id": "tt20_2015_appvii_2",
                    "properties": {},
                }
            ],
        }
    )

    return build_corpus_registry(
        {
            "L59": payload("ldn_2020", "59/2020/QH14", "1", "1", "a"),
            "L68": payload("ldn_2014", "68/2014/QH13", "35", "1", "m"),
            "ND34": grouping_payload,
            "TT20": appendix_payload,
        },
        {
            "L59": "source",
            "L68": "target",
            "ND34": "grouping target",
            "TT20": "appendix target",
        },
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


def test_provider_owned_span_is_not_resolved_again_by_generic_rules() -> None:
    text = "Điều 1. Dẫn chiếu\n1. Thực hiện theo [Điều 2].\nĐiều 2. Quy định\n"
    parsed = parse_text(text, _document())
    registry = StructuralRegistry.from_parsed_document(parsed, "L59_2020")
    start = text.index("[Điều 2]")

    references = StructuralReferenceResolver(
        registry,
        text,
        excluded_source_spans=((start, start + len("[Điều 2]")),),
    ).resolve_article(parsed.articles[0])

    assert references == []


def test_resolver_uses_part_scoped_article_key_for_clause_segments() -> None:
    text = (
        "Phần thứ nhất\nQUY ĐỊNH\n"
        "Điều 1. Nội dung\n1. Nội dung phần một.\n"
        "Phần thứ hai\nQUY ĐỊNH KHÁC\n"
        "Điều 1. Nội dung khác\n1. Thực hiện theo Điều 1.\n"
    )
    parsed = parse_text(text, _document())
    registry = StructuralRegistry.from_parsed_document(parsed, "L59_2020")

    references = StructuralReferenceResolver(registry, text).resolve_article(
        parsed.articles[1]
    )

    assert len(references) == 1
    assert references[0].target_unit_ids == ("ldn_2020_p2_art1",)


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


def test_resolves_coordinated_explicit_clauses_as_one_atomic_bundle() -> None:
    text = (
        "Điều 49. Quyền của thành viên\n"
        "1. Quyền thứ nhất.\n"
        "2. Quyền thứ hai.\n"
        "3. Quyền thứ ba.\n"
        "Điều 57. Triệu tập họp\n"
        "1. Thành viên quy định tại khoản 2 và khoản 3 Điều 49 của Luật này."
    )
    parsed = parse_text(text, _document())
    registry = StructuralRegistry.from_parsed_document(parsed, "L59_2020")

    references = StructuralReferenceResolver(registry, text).resolve_article(
        parsed.articles[1]
    )

    assert len(references) == 1
    reference = references[0]
    assert reference.status == "RESOLVED"
    assert reference.target_unit_ids == (
        "ldn_2020_art49_cl2",
        "ldn_2020_art49_cl3",
    )
    assert reference.mention.raw_text == "khoản 2 và khoản 3 Điều 49"


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
        "appendix_scope": None,
        "appendix_number": None,
        "part_number": None,
        "chapter_number": "III",
        "section_number": "1",
        "subsection_number": None,
        "article_number": None,
        "clause_number": None,
        "point_label": None,
    }
    assert chapter.target_candidate.model_dump() == {
        "target_type": "Chapter",
        "document_number": "57/2026/NĐ-CP",
        "appendix_scope": None,
        "appendix_number": None,
        "part_number": None,
        "chapter_number": "V",
        "section_number": None,
        "subsection_number": None,
        "article_number": None,
        "clause_number": None,
        "point_label": None,
    }


def test_resolver_resolves_local_appendix_reference_to_canonical_node() -> None:
    text = """Điều 1. Biểu mẫu
1. Hồ sơ lập theo Phụ lục I kèm theo văn bản này.
PHỤ LỤC I: MẪU HỒ SƠ
Nội dung biểu mẫu
"""
    parsed = parse_text(text, _document())
    registry = StructuralRegistry.from_parsed_document(parsed, "L59_2020")

    references = StructuralReferenceResolver(registry, text).resolve_article(
        parsed.articles[0]
    )

    appendix = next(
        item
        for item in references
        if item.target_candidate and item.target_candidate.target_type == "Appendix"
    )
    assert appendix.status == "RESOLVED"
    assert appendix.target_unit_ids == ("ldn_2020_appi",)
    assert appendix.target_candidate.appendix_scope == "i"


def test_resolver_preserves_external_appendix_candidate_without_registry() -> None:
    text = """Điều 1. Biểu mẫu
1. Áp dụng Phụ lục VII-2 ban hành kèm theo Thông tư số 20/2015/TT-BKHĐT.
"""
    parsed = parse_text(text, _document())
    registry = StructuralRegistry.from_parsed_document(parsed, "L59_2020")

    references = StructuralReferenceResolver(registry, text).resolve_article(
        parsed.articles[0]
    )

    assert len(references) == 1
    reference = references[0]
    assert reference.status == "UNRESOLVED"
    assert reference.reference_scope == "EXTERNAL"
    assert reference.reason_code == "target_document_not_in_snapshot"
    assert reference.target_candidate.target_type == "Appendix"
    assert reference.target_candidate.appendix_scope == "vii_2"
    assert reference.target_candidate.document_number == "20/2015/TT-BKHĐT"


def test_resolver_links_external_appendix_from_corpus_registry() -> None:
    text = """Điều 1. Biểu mẫu
1. Áp dụng Phụ lục VII-2 ban hành kèm theo Thông tư số 20/2015/TT-BKHĐT.
"""
    parsed = parse_text(text, _document())
    registry = StructuralRegistry.from_parsed_document(parsed, "L59_2020")
    registry_build = _registry_build()

    references = StructuralReferenceResolver(
        registry,
        text,
        corpus_registry=registry_build.registry,
        registry_receipt=registry_build.receipt,
    ).resolve_article(parsed.articles[0])

    assert len(references) == 1
    reference = references[0]
    assert reference.status == "RESOLVED"
    assert reference.reference_scope == "EXTERNAL"
    assert reference.target_unit_ids == ("tt20_2015_appvii_2",)
    assert reference.registry_evidence.target_type == "Appendix"


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


def test_part_and_subsection_references_resolve_against_exact_ancestors() -> None:
    text = """Phần I. QUY ĐỊNH CHUNG
Chương I
PHẠM VI
Mục 1. NGUYÊN TẮC
Tiểu mục 1. YÊU CẦU
Điều 1. Nội dung
1. Áp dụng Phần này, Phần I của Luật này và Tiểu mục 1 Mục 1 Chương I.
"""
    parsed = parse_text(text, _document())
    registry = StructuralRegistry.from_parsed_document(parsed, "L59_2020")

    references = StructuralReferenceResolver(registry, text).resolve_article(
        parsed.articles[0]
    )

    assert [item.target_unit_ids for item in references] == [
        ("ldn_2020_part1",),
        ("ldn_2020_part1",),
        ("ldn_2020_ch1_sec1_subsec1",),
    ]
    assert all(item.status == "RESOLVED" for item in references)


def test_external_part_and_subsection_do_not_fall_back_to_local_document() -> None:
    text = """Điều 1. Nội dung
1. Áp dụng Phần II Nghị định 78/2025/NĐ-CP và Tiểu mục 1 Mục 3 Chương VI Nghị định 34/2016/NĐ-CP.
"""
    parsed = parse_text(text, _document())
    registry = StructuralRegistry.from_parsed_document(parsed, "L59_2020")

    references = StructuralReferenceResolver(registry, text).resolve_article(
        parsed.articles[0]
    )

    assert len(references) == 2
    assert [item.target_candidate.target_type for item in references] == [
        "Part",
        "Subsection",
    ]
    assert all(item.status == "UNRESOLVED" for item in references)
    assert all(item.reference_scope == "EXTERNAL" for item in references)
    assert references[1].target_candidate.subsection_number == "1"


def test_external_part_and_subsection_resolve_from_registry_v2() -> None:
    text = """Điều 1. Nội dung
1. Áp dụng Phần II Nghị định 34/2016/NĐ-CP và Tiểu mục 1 Mục 3 Chương V Nghị định 34/2016/NĐ-CP.
"""
    parsed = parse_text(text, _document())
    registry = StructuralRegistry.from_parsed_document(parsed, "L59_2020")
    build = _registry_build()

    references = StructuralReferenceResolver(
        registry,
        text,
        corpus_registry=build.registry,
        registry_receipt=build.receipt,
    ).resolve_article(parsed.articles[0])

    assert [item.target_unit_ids for item in references] == [
        ("nd34_2016_part2",),
        ("nd34_2016_ch5_sec3_subsec1",),
    ]
    assert all(item.status == "RESOLVED" for item in references)
    assert all(item.reference_scope == "EXTERNAL" for item in references)
