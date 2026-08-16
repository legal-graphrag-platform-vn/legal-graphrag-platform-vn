from __future__ import annotations

from datetime import date

import pytest

from src.pipeline.parser.hierarchy_parser import parse_text, parse_text_with_diagnostics
from src.pipeline.parser.models import (
    Article,
    Clause,
    DocumentInfo,
    ParsedDocument,
    Point,
    Section,
)
from src.pipeline.persistence.payload_builder import (
    PayloadBuildError,
    build_graph_payload,
)
from src.shared.ontology.payload_consistency_validator import (
    validate_payload_consistency_or_raise,
)


def _parsed() -> ParsedDocument:
    return ParsedDocument(
        document=DocumentInfo(
            id="ldn_2020",
            title="Luật Doanh nghiệp",
            number="59/2020/QH14",
            doc_type="Law",
            legal_status="ACTIVE",
            effective_from=date(2021, 1, 1),
            issuer_name="Quốc hội",
        ),
        articles=[
            Article(
                number=17,
                title="Quyền thành lập",
                chapter="II",
                chapter_title="Thành lập doanh nghiệp",
                content_raw="Điều 17 content",
                clauses=[
                    Clause(
                        number=1,
                        content="Khoản 1",
                        points=[Point(label="a", content="Điểm a")],
                    )
                ],
            )
        ],
    )


def test_build_graph_payload_uses_canonical_ids_and_relation_id() -> None:
    payload = build_graph_payload(
        _parsed(),
        [
            {
                "decision": "accepted",
                "relation": {
                    "head": "ldn_2020_art17",
                    "relation": "DEFINES",
                    "tail": "von_dieu_le",
                    "properties": {
                        "confidence": 0.91,
                        "llm_model": "gemini:gemini-2.5-flash",
                        "created_at": "2026-07-10T00:00:00Z",
                    },
                },
            }
        ],
        {
            "von_dieu_le": {
                "id": "von_dieu_le",
                "type": "LegalConcept",
                "label": "Vốn điều lệ",
                "name": "Vốn điều lệ",
            }
        },
        raw_doc_code="LDN2020",
    )

    assert payload["metadata"]["raw_doc_code"] == "LDN2020"
    assert payload["metadata"]["graph_id"] == "ldn_2020"
    node_ids = {node["id"] for node in payload["nodes"]}
    assert "ldn_2020_ch2" in node_ids
    assert "ldn_2020_art17" in node_ids
    assert "ldn_2020_art17_cl1" in node_ids
    assert "ldn_2020_art17_cl1_pa" in node_ids
    assert "von_dieu_le" in node_ids
    assert "quoc_hoi" in node_ids
    assert "issuer_quoc_hoi" not in node_ids
    defines = next(
        relation for relation in payload["relations"] if relation["type"] == "DEFINES"
    )
    assert defines["head_id"] == "ldn_2020_art17"
    assert defines["tail_id"] == "von_dieu_le"
    assert defines["id"]
    assert defines["properties"]["relation_id"]
    assert defines["id"] == defines["properties"]["relation_id"]


def test_parser_metadata_does_not_create_graph_nodes_or_relations() -> None:
    parsed, diagnostics = parse_text_with_diagnostics(
        "Điều 1. Phạm vi điều chỉnh", _parsed().document
    )

    payload = build_graph_payload(parsed, [], {}, raw_doc_code="L59_2020")

    assert parsed.parser_metadata == diagnostics
    assert [node["type"] for node in payload["nodes"]] == [
        "Document",
        "Issuer",
        "Article",
    ]
    assert [relation["type"] for relation in payload["relations"]] == [
        "ISSUED_BY",
        "CONTAINS",
    ]


def test_appendix_and_descendants_use_owner_scoped_canonical_ids() -> None:
    parsed = parse_text(
        "Điều 1. Chính văn\n"
        "PHỤ LỤC I\n"
        "Điều 1. Điều thuộc phụ lục\n"
        "1. Khoản thuộc phụ lục",
        _parsed().document,
    )

    payload = build_graph_payload(parsed, [], {}, raw_doc_code="L59_2020")
    node_types = {node["id"]: node["type"] for node in payload["nodes"]}

    assert node_types["ldn_2020_art1"] == "Article"
    assert node_types["ldn_2020_appi"] == "Appendix"
    assert node_types["ldn_2020_appi_art1"] == "Article"
    assert node_types["ldn_2020_appi_art1_cl1"] == "Clause"
    validate_payload_consistency_or_raise(payload)


def test_attached_instrument_and_descendants_use_owner_scoped_canonical_ids() -> None:
    parsed = parse_text(
        "Điều 1. Chính văn\n"
        "ĐIỀU LỆ VỀ TỔ CHỨC VÀ HOẠT ĐỘNG\n"
        "(Ban hành kèm theo Luật số 59/2020/QH14)\n"
        "Điều 1. Điều thuộc Điều lệ\n"
        "1. Khoản thuộc Điều lệ",
        _parsed().document,
    )

    payload = build_graph_payload(parsed, [], {}, raw_doc_code="L59_2020")
    node_types = {node["id"]: node["type"] for node in payload["nodes"]}

    assert node_types["ldn_2020_art1"] == "Article"
    assert node_types["ldn_2020_instcharter_1"] == "AttachedInstrument"
    assert node_types["ldn_2020_instcharter_1_art1"] == "Article"
    assert node_types["ldn_2020_instcharter_1_art1_cl1"] == "Clause"
    validate_payload_consistency_or_raise(payload)


def test_table_of_contents_remains_artifact_only() -> None:
    parsed = parse_text(
        "Điều 1. Một\nNội dung\nĐiều 2. Hai\nNội dung\n"
        "MỤC LỤC\nĐiều 1. Một 1\nĐiều 2. Hai 2",
        _parsed().document,
    )

    payload = build_graph_payload(parsed, [], {}, raw_doc_code="L59_2020")

    assert parsed.unparsed_sections[0].section_type == "TABLE_OF_CONTENTS"
    assert all(node["type"] != "TableOfContents" for node in payload["nodes"])


def test_build_graph_payload_fails_for_missing_entity_index_entry() -> None:
    with pytest.raises(PayloadBuildError, match="missing entity"):
        build_graph_payload(
            _parsed(),
            [
                {
                    "decision": "accepted",
                    "relation": {
                        "head": "ldn_2020_art17",
                        "relation": "DEFINES",
                        "tail": "missing",
                    },
                }
            ],
            {},
            raw_doc_code="LDN2020",
        )


def test_build_graph_payload_defers_provider_cross_document_relation() -> None:
    payload = build_graph_payload(
        _parsed(),
        [
            {
                "decision": "accepted",
                "materialization_route": "CORPUS_RELATION_RECONCILIATION",
                "relation": {
                    "head": "ldn_2020_art17_cl1_pa",
                    "relation": "AMENDS",
                    "tail": "external_doc_art2_cl2_pa",
                    "properties": {"effective_from": "2021-01-01"},
                },
            }
        ],
        {},
        raw_doc_code="LDN2020",
    )

    assert payload["metadata"]["deferred_relation_count"] == 1
    assert not any(relation["type"] == "AMENDS" for relation in payload["relations"])


def test_point_d_and_dd_do_not_collide() -> None:
    parsed = _parsed()
    parsed.articles[0].clauses[0].points = [
        Point(label="d", content="Điểm d"),
        Point(label="đ", content="Điểm đ"),
    ]

    payload = build_graph_payload(parsed, [], {}, raw_doc_code="L59_2020")
    point_ids = {node["id"] for node in payload["nodes"] if node["type"] == "Point"}

    assert point_ids == {"ldn_2020_art17_cl1_pd", "ldn_2020_art17_cl1_pdd"}


def test_build_graph_payload_nests_section_between_chapter_and_article() -> None:
    parsed = _parsed()
    parsed.sections = [Section(number="1", title="Thành lập", chapter="II")]
    parsed.articles[0].section = "1"

    payload = build_graph_payload(parsed, [], {}, raw_doc_code="L59_2020")

    section = next(node for node in payload["nodes"] if node["type"] == "Section")
    assert section == {
        "type": "Section",
        "id": "ldn_2020_ch2_sec1",
        "number": "1",
        "title": "Thành lập",
    }
    contains = {
        (relation["head_id"], relation["tail_id"])
        for relation in payload["relations"]
        if relation["type"] == "CONTAINS"
    }
    assert ("ldn_2020_ch2", "ldn_2020_ch2_sec1") in contains
    assert ("ldn_2020_ch2_sec1", "ldn_2020_art17") in contains
    assert ("ldn_2020_ch2", "ldn_2020_art17") not in contains


def test_old_payload_without_sections_keeps_direct_chapter_article_edge() -> None:
    payload = build_graph_payload(_parsed(), [], {}, raw_doc_code="L59_2020")
    contains = {
        (relation["head_id"], relation["tail_id"])
        for relation in payload["relations"]
        if relation["type"] == "CONTAINS"
    }

    assert ("ldn_2020_ch2", "ldn_2020_art17") in contains


def test_build_graph_payload_accepts_chapter_preamble_before_sections() -> None:
    parsed = parse_text(
        "Chương XXIII\nCÁC TỘI PHẠM VỀ CHỨC VỤ\n"
        "Điều 352. Khái niệm tội phạm về chức vụ\n"
        "Mục 1. Các tội phạm tham nhũng\n"
        "Điều 353. Tội tham ô tài sản",
        _parsed().document,
    )

    payload = build_graph_payload(parsed, [], {}, raw_doc_code="BLHS_2015")
    validate_payload_consistency_or_raise(payload)
    contains = {
        (relation["head_id"], relation["tail_id"])
        for relation in payload["relations"]
        if relation["type"] == "CONTAINS"
    }

    assert ("ldn_2020_ch23", "ldn_2020_art352") in contains
    assert ("ldn_2020_ch23", "ldn_2020_ch23_sec1") in contains
    assert ("ldn_2020_ch23_sec1", "ldn_2020_art353") in contains


def test_build_graph_payload_persists_part_and_subsection_chain() -> None:
    parsed = parse_text(
        "Phần I. Phần một\nChương II\nCHƯƠNG HAI\nMục 1. Mục một\n"
        "Tiểu mục 2. Tiểu mục hai\nĐiều 17. Quyền thành lập\n1. Khoản một",
        _parsed().document,
    )

    payload = build_graph_payload(parsed, [], {}, raw_doc_code="L59_2020")
    validate_payload_consistency_or_raise(payload)
    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["ldn_2020_part1"]["type"] == "Part"
    assert nodes["ldn_2020_ch2_sec1_subsec2"]["type"] == "Subsection"
    contains = {
        (relation["head_id"], relation["tail_id"])
        for relation in payload["relations"]
        if relation["type"] == "CONTAINS"
    }
    assert {
        ("ldn_2020", "ldn_2020_part1"),
        ("ldn_2020_part1", "ldn_2020_ch2"),
        ("ldn_2020_ch2", "ldn_2020_ch2_sec1"),
        ("ldn_2020_ch2_sec1", "ldn_2020_ch2_sec1_subsec2"),
        ("ldn_2020_ch2_sec1_subsec2", "ldn_2020_art17"),
    } <= contains


def test_build_graph_payload_keeps_part_chapter_article_path_without_fake_section() -> (
    None
):
    parsed = parse_text(
        "Phần I. Phần một\nChương II\nCHƯƠNG HAI\nĐiều 17. Quyền thành lập",
        _parsed().document,
    )

    payload = build_graph_payload(parsed, [], {}, raw_doc_code="L59_2020")
    validate_payload_consistency_or_raise(payload)
    assert not any(
        node["type"] in {"Section", "Subsection"} for node in payload["nodes"]
    )
    contains = {
        (relation["head_id"], relation["tail_id"])
        for relation in payload["relations"]
        if relation["type"] == "CONTAINS"
    }
    assert ("ldn_2020", "ldn_2020_part1") in contains
    assert ("ldn_2020_part1", "ldn_2020_ch2") in contains
    assert ("ldn_2020_ch2", "ldn_2020_art17") in contains


def test_build_graph_payload_rejects_raw_structural_alias() -> None:
    with pytest.raises(PayloadBuildError, match="missing entity"):
        build_graph_payload(
            _parsed(),
            [
                {
                    "decision": "accepted",
                    "relation": {
                        "head": "dieu_17",
                        "relation": "DEFINES",
                        "tail": "von_dieu_le",
                    },
                }
            ],
            {
                "von_dieu_le": {
                    "id": "von_dieu_le",
                    "type": "LegalConcept",
                    "name": "Vốn điều lệ",
                }
            },
            raw_doc_code="L59_2020",
        )


def test_requires_relations_preserve_distinct_source_articles() -> None:
    entity_index = {
        "cong_ty": {"id": "cong_ty", "type": "LegalSubject", "name": "Công ty"},
        "so_dang_ky": {
            "id": "so_dang_ky",
            "type": "LegalConcept",
            "name": "Sổ đăng ký",
        },
    }
    records = [
        {
            "decision": "accepted",
            "relation": {
                "head": "cong_ty",
                "relation": "REQUIRES",
                "tail": "so_dang_ky",
                "properties": {"source_article": source_article},
            },
        }
        for source_article in ("ldn_2020_art122", "ldn_2020_art124")
    ]
    payload = build_graph_payload(
        _parsed(), records, entity_index, raw_doc_code="L59_2020"
    )
    requires = [
        relation for relation in payload["relations"] if relation["type"] == "REQUIRES"
    ]
    assert len(requires) == 2
    assert len({relation["id"] for relation in requires}) == 2


def test_build_structural_payload_without_extraction(tmp_path) -> None:
    from src.pipeline.persistence.payload_builder import (
        build_payload_from_paths,
        build_structural_payload,
    )

    parsed = _parsed()
    payload = build_structural_payload(parsed, raw_doc_code="L59_2020")
    validate_payload_consistency_or_raise(payload)

    node_types = {node["type"] for node in payload["nodes"]}
    assert "Document" in node_types
    assert "Article" in node_types
    assert "LegalConcept" not in node_types
    assert "LegalSubject" not in node_types

    relation_types = {relation["type"] for relation in payload["relations"]}
    assert "CONTAINS" in relation_types
    assert "ISSUED_BY" in relation_types
    assert "DEFINES" not in relation_types

    # Also test build_payload_from_paths with mode="structural"
    doc_dir = tmp_path / "L59_2020"
    doc_dir.mkdir()
    (doc_dir / "hierarchy.json").write_text(parsed.model_dump_json(indent=2), encoding="utf-8")

    from_path_payload = build_payload_from_paths(doc_dir, mode="structural")
    assert len(from_path_payload["nodes"]) == len(payload["nodes"])
    assert len(from_path_payload["relations"]) == len(payload["relations"])

