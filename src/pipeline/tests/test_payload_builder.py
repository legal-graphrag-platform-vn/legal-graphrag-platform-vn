from __future__ import annotations

from datetime import date

import pytest

from src.pipeline.parser.models import Article, Clause, DocumentInfo, ParsedDocument, Point
from src.pipeline.persistence.payload_builder import PayloadBuildError, build_graph_payload


def _parsed() -> ParsedDocument:
    return ParsedDocument(
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
        articles=[
            Article(
                number=17,
                title="Quyền thành lập",
                chapter="II",
                chapter_title="Thành lập doanh nghiệp",
                content_raw="Điều 17 content",
                clauses=[Clause(number=1, content="Khoản 1", points=[Point(label="a", content="Điểm a")])],
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
    defines = next(relation for relation in payload["relations"] if relation["type"] == "DEFINES")
    assert defines["head_id"] == "ldn_2020_art17"
    assert defines["tail_id"] == "von_dieu_le"
    assert defines["id"]
    assert defines["properties"]["relation_id"]
    assert defines["id"] == defines["properties"]["relation_id"]


def test_build_graph_payload_fails_for_missing_entity_index_entry() -> None:
    with pytest.raises(PayloadBuildError, match="missing entity"):
        build_graph_payload(
            _parsed(),
            [{"decision": "accepted", "relation": {"head": "ldn_2020_art17", "relation": "DEFINES", "tail": "missing"}}],
            {},
            raw_doc_code="LDN2020",
        )


def test_point_d_and_dd_do_not_collide() -> None:
    parsed = _parsed()
    parsed.articles[0].clauses[0].points = [
        Point(label="d", content="Điểm d"),
        Point(label="đ", content="Điểm đ"),
    ]

    payload = build_graph_payload(parsed, [], {}, raw_doc_code="L59_2020")
    point_ids = {node["id"] for node in payload["nodes"] if node["type"] == "Point"}

    assert point_ids == {"ldn_2020_art17_cl1_pd", "ldn_2020_art17_cl1_pdd"}


def test_build_graph_payload_rejects_raw_structural_alias() -> None:
    with pytest.raises(PayloadBuildError, match="missing entity"):
        build_graph_payload(
            _parsed(),
            [{"decision": "accepted", "relation": {"head": "dieu_17", "relation": "DEFINES", "tail": "von_dieu_le"}}],
            {"von_dieu_le": {"id": "von_dieu_le", "type": "LegalConcept", "name": "Vốn điều lệ"}},
            raw_doc_code="L59_2020",
        )


def test_requires_relations_preserve_distinct_source_articles() -> None:
    entity_index = {
        "cong_ty": {"id": "cong_ty", "type": "LegalSubject", "name": "Công ty"},
        "so_dang_ky": {"id": "so_dang_ky", "type": "LegalConcept", "name": "Sổ đăng ký"},
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
    payload = build_graph_payload(_parsed(), records, entity_index, raw_doc_code="L59_2020")
    requires = [relation for relation in payload["relations"] if relation["type"] == "REQUIRES"]
    assert len(requires) == 2
    assert len({relation["id"] for relation in requires}) == 2
