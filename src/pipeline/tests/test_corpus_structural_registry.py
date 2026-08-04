from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.pipeline.extraction.corpus_structural_registry import (
    CorpusStructuralRegistry,
    RegistryDocument,
    RegistryError,
    RegistryUnit,
    build_corpus_registry,
    load_registry_build,
    publish_registry_build,
)
from src.shared.ontology.validators import validate_graph_payload


def _payload(document_id: str, number: str, *, with_section: bool = True):
    nodes = [
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
        {"type": "Chapter", "id": f"{document_id}_ch3", "number": "III", "title": "Ba"},
        {
            "type": "Article",
            "id": f"{document_id}_art8",
            "number": "8",
            "content_raw": "Nội dung",
            "effective_from": "2021-01-01",
            "legal_status": "ACTIVE",
        },
        {
            "type": "Clause",
            "id": f"{document_id}_art8_cl3",
            "number": "3",
            "content_raw": "Khoản",
            "effective_from": "2021-01-01",
            "legal_status": "ACTIVE",
        },
        {
            "type": "Point",
            "id": f"{document_id}_art8_cl3_pdd",
            "label": "đ",
            "content_raw": "Điểm",
        },
    ]
    relations = [
        {
            "head_id": f"{document_id}_art8",
            "type": "CONTAINS",
            "tail_id": f"{document_id}_art8_cl3",
            "properties": {},
        },
        {
            "head_id": f"{document_id}_art8_cl3",
            "type": "CONTAINS",
            "tail_id": f"{document_id}_art8_cl3_pdd",
            "properties": {},
        },
    ]
    if with_section:
        nodes.append(
            {
                "type": "Section",
                "id": f"{document_id}_ch3_sec1",
                "number": "1",
                "title": "Một",
            }
        )
        relations.extend(
            [
                {
                    "head_id": document_id,
                    "type": "CONTAINS",
                    "tail_id": f"{document_id}_ch3",
                    "properties": {},
                },
                {
                    "head_id": f"{document_id}_ch3",
                    "type": "CONTAINS",
                    "tail_id": f"{document_id}_ch3_sec1",
                    "properties": {},
                },
                {
                    "head_id": f"{document_id}_ch3_sec1",
                    "type": "CONTAINS",
                    "tail_id": f"{document_id}_art8",
                    "properties": {},
                },
            ]
        )
    else:
        relations.extend(
            [
                {
                    "head_id": document_id,
                    "type": "CONTAINS",
                    "tail_id": f"{document_id}_ch3",
                    "properties": {},
                },
                {
                    "head_id": f"{document_id}_ch3",
                    "type": "CONTAINS",
                    "tail_id": f"{document_id}_art8",
                    "properties": {},
                },
            ]
        )
    return validate_graph_payload({"nodes": nodes, "relations": relations})


def _build(*, build_id: str = "registry-build-1", source: str = "Nội dung"):
    return build_corpus_registry(
        {"L59": _payload("ldn_2020", "59/2020/QH14")},
        {"L59": source},
        build_id=build_id,
        created_at=datetime(2026, 7, 31, tzinfo=timezone.utc),
    )


def _part_subsection_payload():
    document_id = "nd34_2016"
    nodes = [
        {
            "type": "Document",
            "id": document_id,
            "number": "34/2016/NĐ-CP",
            "doc_type": "Decree",
            "normative": True,
            "legal_status": "ACTIVE",
            "effective_from": "2016-07-01",
            "issuer_name": "Chính phủ",
        },
        {"type": "Part", "id": f"{document_id}_part2", "number": "II", "title": "Hai"},
        {"type": "Chapter", "id": f"{document_id}_ch5", "number": "V", "title": "Năm"},
        {
            "type": "Section",
            "id": f"{document_id}_ch5_sec3",
            "number": "3",
            "title": "Ba",
        },
        {
            "type": "Subsection",
            "id": f"{document_id}_ch5_sec3_subsec1",
            "number": "1",
            "title": "Một",
        },
        {
            "type": "Article",
            "id": f"{document_id}_art77",
            "number": "77",
            "content_raw": "Điều 77",
            "effective_from": "2016-07-01",
            "legal_status": "ACTIVE",
        },
    ]
    ids = [node["id"] for node in nodes]
    relations = [
        {
            "head_id": head,
            "type": "CONTAINS",
            "tail_id": tail,
            "properties": {},
        }
        for head, tail in zip(ids, ids[1:])
    ]
    return validate_graph_payload({"nodes": nodes, "relations": relations})


def test_registry_separates_document_endpoints_from_descendant_units() -> None:
    build = _build()

    assert build.registry.documents == (
        RegistryDocument(
            document_id="ldn_2020",
            number="59/2020/QH14",
            normalized_number="59/2020/QH14",
            doc_type="Law",
        ),
    )
    assert all(isinstance(item, RegistryUnit) for item in build.registry.units)
    assert all(item.unit_type != "Document" for item in build.registry.units)
    assert build.registry.endpoint_candidates("ldn_2020") == build.registry.documents


def test_registry_resolves_exact_point_and_preserves_d_vs_dd() -> None:
    registry = _build().registry

    target = registry.unit_candidates(
        document_id="ldn_2020",
        unit_type="Point",
        article_number="8",
        clause_number="3",
        point_label="đ",
    )
    other = registry.unit_candidates(
        document_id="ldn_2020",
        unit_type="Point",
        article_number="8",
        clause_number="3",
        point_label="d",
    )

    assert [item.unit_id for item in target] == ["ldn_2020_art8_cl3_pdd"]
    assert other == ()


def test_snapshot_hash_ignores_build_id_but_provenance_tracks_source() -> None:
    first = _build(build_id="build-a", source="A")
    second = _build(build_id="build-b", source="B")

    assert first.registry.snapshot_hash == second.registry.snapshot_hash
    assert first.receipt.provenance_hash != second.receipt.provenance_hash


def test_publication_reuses_content_and_keeps_build_receipts_immutable(
    tmp_path,
) -> None:
    first = _build(build_id="build-a")
    second = _build(build_id="build-b")

    publish_registry_build(first, tmp_path)
    publish_registry_build(second, tmp_path)
    loaded = load_registry_build(tmp_path, "build-b")

    assert loaded.registry.snapshot_hash == first.registry.snapshot_hash
    assert loaded.receipt.build_id == "build-b"
    assert len(tuple((tmp_path / "content").iterdir())) == 1


def test_publication_rejects_unsafe_build_id(tmp_path) -> None:
    with pytest.raises(RegistryError, match="Unsafe registry build ID"):
        build_corpus_registry(
            {"L59": _payload("ldn_2020", "59/2020/QH14")},
            {"L59": "source"},
            build_id="../escape",
        )


def test_registry_rejects_multiple_canonical_parents() -> None:
    payload = _payload("ldn_2020", "59/2020/QH14")
    raw = {
        "nodes": [
            {"type": node.node_type, **node.properties} for node in payload.nodes
        ],
        "relations": [
            {
                "head_id": relation.head_id,
                "type": relation.relation_type,
                "tail_id": relation.tail_id,
                "properties": relation.properties,
            }
            for relation in payload.relations
        ]
        + [
            {
                "head_id": "ldn_2020_ch3",
                "type": "CONTAINS",
                "tail_id": "ldn_2020_art8",
                "properties": {},
            }
        ],
    }

    with pytest.raises(RegistryError, match="exactly one canonical parent"):
        build_corpus_registry(
            {"L59": validate_graph_payload(raw)},
            {"L59": "source"},
            build_id="build-a",
        )


def test_loaded_registry_rejects_tampered_content(tmp_path) -> None:
    build = _build()
    publish_registry_build(build, tmp_path)
    content_dir = next((tmp_path / "content").iterdir())
    (content_dir / "units.jsonl").write_text("", encoding="utf-8")

    with pytest.raises(RegistryError, match="snapshot hash mismatch"):
        load_registry_build(tmp_path, build.receipt.build_id)


def test_registry_document_number_lookup_is_exact() -> None:
    registry: CorpusStructuralRegistry = _build().registry

    assert registry.document_candidates(" 59/2020/QH14 ")[0].document_id == "ldn_2020"
    assert registry.document_candidates("Nghị định 59/2020/QH14") == ()


def test_registry_v2_indexes_part_subsection_and_complete_ancestry() -> None:
    build = build_corpus_registry(
        {"ND34": _part_subsection_payload()},
        {"ND34": "canonical source"},
        build_id="registry-v2-test",
    )

    assert build.registry.manifest.contract_version == ("corpus-structural-registry-v2")
    part = build.registry.unit_candidates(
        document_id="nd34_2016", unit_type="Part", part_number="thứ hai"
    )
    subsection = build.registry.unit_candidates(
        document_id="nd34_2016",
        unit_type="Subsection",
        chapter_number="V",
        section_number="3",
        subsection_number="1",
    )

    assert [item.unit_id for item in part] == ["nd34_2016_part2"]
    assert subsection[0].ancestor_ids == (
        "nd34_2016",
        "nd34_2016_part2",
        "nd34_2016_ch5",
        "nd34_2016_ch5_sec3",
    )
