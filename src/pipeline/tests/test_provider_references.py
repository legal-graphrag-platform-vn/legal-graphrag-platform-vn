from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.pipeline.extraction.provider_references import (
    ProviderReferenceMentionV1,
    ProviderReferenceSidecarError,
    ensure_luatvietnam_reference_sidecar,
    load_provider_references,
)
from src.pipeline.extraction.provider_identity_index import (
    _smallest_structural_endpoint,
    build_luatvietnam_identity_indexes,
)
from src.pipeline.extraction.structural_context import StructuralRegistry
from src.pipeline.extraction.provider_relation_candidates import (
    ProviderRelationCandidateV1,
    build_provider_relation_candidates,
    provider_owned_source_spans,
)
from src.pipeline.parser.hierarchy_parser import parse_text
from src.pipeline.parser.models import DocumentInfo


HTML = """
<h1>Nghị định số 117/2024/NĐ-CP</h1>
<table><tr><th>Số hiệu:</th><td>117/2024/NĐ-CP</td></tr></table>
<div class="the-document-body">
  <p>Điều 1. Sửa đổi, bổ sung</p>
  <div id="demuc2732412"><p>a) Sửa đổi, bổ sung
    <span class="popupRelate noi-dung-tham-chieu"
          data-href="/van-ban/get/noi-dung-tham-chieu.html?docItemId=1399134&amp;docId=186730&amp;docItemRelateId=158258">điểm a khoản 2</span>
    như sau:</p></div>
</div>
"""


def _raw_dir(tmp_path: Path) -> Path:
    raw_dir = tmp_path / "LTV_366692"
    raw_dir.mkdir()
    (raw_dir / "source.html").write_text(HTML, encoding="utf-8")
    (raw_dir / "metadata.json").write_text(
        json.dumps(
            {
                "external_id": "366692",
                "source_provider": "luatvietnam.vn",
                "source_url": "https://luatvietnam.vn/doanh-nghiep/nghi-dinh-117-2024-nd-cp-366692-d1.html",
            }
        ),
        encoding="utf-8",
    )
    return raw_dir


def test_ensure_sidecar_backfills_existing_luatvietnam_raw_bundle(
    tmp_path: Path,
) -> None:
    raw_dir = _raw_dir(tmp_path)
    from experiments.luatvietnam_crawler.parser import parse_document

    expected = parse_document(
        HTML,
        "https://luatvietnam.vn/doanh-nghiep/nghi-dinh-117-2024-nd-cp-366692-d1.html",
    )
    (raw_dir / "source.txt").write_text(expected.source_text + "\n", encoding="utf-8")

    references = ensure_luatvietnam_reference_sidecar(raw_dir)

    assert len(references) == 1
    assert references[0].provider_source_document_id == "366692"
    assert references[0].provider_target_document_id == "186730"
    assert (raw_dir / "references.jsonl").is_file()
    assert load_provider_references(raw_dir, expected.source_text) == references


def test_ensure_sidecar_fails_when_html_serialization_differs_from_source(
    tmp_path: Path,
) -> None:
    raw_dir = _raw_dir(tmp_path)
    (raw_dir / "source.txt").write_text("Điều 1. Dữ liệu khác\n", encoding="utf-8")

    with pytest.raises(
        ProviderReferenceSidecarError, match="does not match canonical source"
    ):
        ensure_luatvietnam_reference_sidecar(raw_dir)


def test_provider_item_can_resolve_to_section_endpoint() -> None:
    source = "Mục 1. Quy định chung\nĐiều 1. Nội dung\n"
    parsed = parse_text(
        source,
        DocumentInfo(
            id="l_test",
            title="Luật thử nghiệm",
            number="1/2020/QH14",
            doc_type="Law",
        ),
    )
    registry = StructuralRegistry.from_parsed_document(parsed, "LTV_1")

    endpoint = _smallest_structural_endpoint(
        parsed,
        registry,
        source.index("Mục 1"),
        source.index("Mục 1") + len("Mục 1. Quy định chung"),
    )

    assert endpoint == ("l_test_sec1", "Section")


def test_provider_item_can_resolve_to_chapter_heading() -> None:
    source = "Chương II\nQUY ĐỊNH CHUNG\nĐiều 1. Nội dung\n"
    parsed = parse_text(
        source,
        DocumentInfo(
            id="l_test",
            title="Luật thử nghiệm",
            number="1/2020/QH14",
            doc_type="Law",
        ),
    )
    registry = StructuralRegistry.from_parsed_document(parsed, "LTV_1")
    heading_end = source.index("Điều 1")

    endpoint = _smallest_structural_endpoint(
        parsed,
        registry,
        0,
        heading_end,
        source_text=source,
    )

    assert endpoint == ("l_test_ch2", "Chapter")


def test_provider_owned_spans_reject_stale_candidate_even_when_unresolved() -> None:
    source = "Điều 1. Theo [Điều 2]."
    start = source.index("[Điều 2]")
    mention = ProviderReferenceMentionV1(
        contract_version="provider-reference-mention-v1",
        provider="luatvietnam",
        provider_source_document_id="100",
        provider_target_document_id="200",
        provider_link_type="REFERENCE",
        citation_text="Điều 2",
        source_char_start=start + 1,
        source_char_end=start + len("[Điều 2]"),
    )
    candidate = ProviderRelationCandidateV1(
        candidate_id="stale-provider-candidate",
        provider_relation_id=None,
        relation_candidate="REFERS_TO",
        source_ownership="HOST",
        host_source_id=None,
        canonical_source_id=None,
        canonical_source_type=None,
        status="UNRESOLVED",
        reason_code="target_document_not_in_corpus",
        evidence=source,
        reference=mention,
    )

    with pytest.raises(ValueError, match="source span drift"):
        provider_owned_source_spans((candidate,), source)


def test_change_content_candidate_resolves_local_source_and_defers_missing_target() -> (
    None
):
    source = (
        "Điều 1. Sửa đổi, bổ sung\n"
        "1. Sửa đổi Điều 2 như sau:\n"
        "a) Sửa đổi, bổ sung [điểm a khoản 2] như sau:\n"
        "“a) Nội dung mới.”"
    )
    marker_start = source.index("[điểm a khoản 2]")
    parsed = parse_text(
        source,
        DocumentInfo(
            id="nd_117_2024",
            title="Nghị định 117",
            number="117/2024/NĐ-CP",
            doc_type="Decree",
            issuer_name="Chính phủ",
        ),
    )
    reference = ProviderReferenceMentionV1(
        contract_version="provider-reference-mention-v1",
        provider="luatvietnam",
        provider_source_document_id="366692",
        provider_source_item_id="2732412",
        provider_target_document_id="186730",
        provider_target_item_ids=("1399134",),
        provider_relation_id="158258",
        provider_link_type="CHANGE_CONTENT",
        citation_text="điểm a khoản 2",
        source_char_start=marker_start,
        source_char_end=marker_start + len("[điểm a khoản 2]"),
        provider_href="/reference",
    )

    candidate = build_provider_relation_candidates(parsed, source, (reference,))[0]

    assert candidate.relation_candidate == "AMENDS"
    assert candidate.source_ownership == "HOST"
    assert candidate.canonical_source_id == "nd_117_2024_art1_cl1_pa"
    assert candidate.canonical_target_id is None
    assert candidate.status == "UNRESOLVED"
    assert candidate.reason_code == "target_document_not_in_corpus"


def test_insert_after_marker_is_positional_anchor_not_amendment_edge() -> None:
    source = (
        "Điều 1. Sửa đổi, bổ sung\n"
        "1. Bổ sung khoản 3 vào sau [khoản 2] như sau:\n"
        "“3. Nội dung mới.”"
    )
    marker_start = source.index("[khoản 2]")
    parsed = parse_text(
        source,
        DocumentInfo(
            id="nd_117_2024",
            title="Nghị định 117",
            number="117/2024/NĐ-CP",
            doc_type="Decree",
            issuer_name="Chính phủ",
        ),
    )
    reference = ProviderReferenceMentionV1(
        contract_version="provider-reference-mention-v1",
        provider="luatvietnam",
        provider_source_document_id="366692",
        provider_source_item_id="2732413",
        provider_target_document_id="186730",
        provider_target_item_ids=("1399133",),
        provider_relation_id="158259",
        provider_link_type="CHANGE_CONTENT",
        citation_text="khoản 2",
        source_char_start=marker_start,
        source_char_end=marker_start + len("[khoản 2]"),
        provider_href="/reference",
    )

    candidate = build_provider_relation_candidates(parsed, source, (reference,))[0]

    assert candidate.relation_candidate == "POSITIONAL_ANCHOR"
    assert candidate.status == "NOT_APPLICABLE"
    assert candidate.reason_code == "positional_anchor_no_graph_edge"


def test_reference_without_item_id_resolves_to_existing_document() -> None:
    source = "Điều 1. Dẫn chiếu\n1. Thực hiện theo [Nghị định số 82/2020/NĐ-CP]."
    marker_start = source.index("[Nghị định")
    parsed = parse_text(
        source,
        DocumentInfo(
            id="nd_117_2024",
            title="Nghị định 117",
            number="117/2024/NĐ-CP",
            doc_type="Decree",
        ),
    )
    reference = ProviderReferenceMentionV1(
        contract_version="provider-reference-mention-v1",
        provider="luatvietnam",
        provider_source_document_id="366692",
        provider_target_document_id="186730",
        provider_link_type="REFERENCE",
        citation_text="Nghị định số 82/2020/NĐ-CP",
        source_char_start=marker_start,
        source_char_end=marker_start + len("[Nghị định số 82/2020/NĐ-CP]"),
    )

    candidate = build_provider_relation_candidates(
        parsed,
        source,
        (reference,),
        provider_document_index={("luatvietnam", "186730"): "nd_82_2020"},
        provider_document_number_index={("luatvietnam", "186730"): "82/2020/NĐ-CP"},
    )[0]

    assert candidate.status == "RESOLVED"
    assert candidate.canonical_target_ids == ("nd_82_2020",)
    assert candidate.canonical_target_types == ("Document",)


def test_provider_items_mapping_to_same_unit_are_canonicalized_once() -> None:
    source = "Điều 1. Dẫn chiếu\n1. Thực hiện theo [điểm a và điểm b]."
    marker_start = source.index("[điểm a")
    parsed = parse_text(
        source,
        DocumentInfo(
            id="source_doc",
            title="Văn bản nguồn",
            number="1/2024/NĐ-CP",
            doc_type="Decree",
        ),
    )
    reference = ProviderReferenceMentionV1(
        contract_version="provider-reference-mention-v1",
        provider="luatvietnam",
        provider_source_document_id="100",
        provider_target_document_id="200",
        provider_target_item_ids=("11", "12"),
        provider_link_type="REFERENCE",
        citation_text="điểm a và điểm b",
        source_char_start=marker_start,
        source_char_end=marker_start + len("[điểm a và điểm b]"),
    )

    candidate = build_provider_relation_candidates(
        parsed,
        source,
        (reference,),
        provider_document_index={("luatvietnam", "200"): "target_doc"},
        provider_unit_index={
            ("luatvietnam", "200", "11"): ("target_doc_art1_cl1", "Clause"),
            ("luatvietnam", "200", "12"): ("target_doc_art1_cl1", "Clause"),
        },
    )[0]

    assert candidate.status == "RESOLVED"
    assert candidate.canonical_target_ids == ("target_doc_art1_cl1",)
    assert candidate.canonical_target_types == ("Clause",)
    assert candidate.reference.provider_target_item_ids == ("11", "12")


def test_explicit_document_number_conflict_fails_closed() -> None:
    source = (
        "Điều 1. Dẫn chiếu\n"
        "1. Thực hiện theo [Khoản 11 Điều 9 Nghị định số 187/2013/NĐ-CP]."
    )
    marker_start = source.index("[Khoản 11")
    parsed = parse_text(
        source,
        DocumentInfo(
            id="nd_17_2020",
            title="Nghị định 17",
            number="17/2020/NĐ-CP",
            doc_type="Decree",
        ),
    )
    reference = ProviderReferenceMentionV1(
        contract_version="provider-reference-mention-v1",
        provider="luatvietnam",
        provider_source_document_id="180465",
        provider_target_document_id="106761",
        provider_target_item_ids=("92427",),
        provider_link_type="REFERENCE",
        citation_text="Khoản 11 Điều 9 Nghị định số 187/2013/NĐ-CP",
        source_char_start=marker_start,
        source_char_end=marker_start
        + len("[Khoản 11 Điều 9 Nghị định số 187/2013/NĐ-CP]"),
    )

    candidate = build_provider_relation_candidates(
        parsed,
        source,
        (reference,),
        provider_document_index={("luatvietnam", "106761"): "nd_77_2016"},
        provider_document_number_index={("luatvietnam", "106761"): "77/2016/NĐ-CP"},
        provider_unit_index={
            ("luatvietnam", "106761", "92427"): (
                "nd_77_2016_art1",
                "Article",
            )
        },
    )[0]

    assert candidate.status == "UNRESOLVED"
    assert candidate.reason_code == "provider_text_target_conflict"


def test_reference_inside_replacement_text_uses_amended_target_as_source() -> None:
    source = (
        "Điều 1. Sửa đổi\n"
        "1. Sửa đổi [điểm a khoản 2] như sau:\n"
        "“a) Thực hiện theo [Điều 3 Nghị định này].”"
    )
    outer_start = source.index("[điểm a khoản 2]")
    inner_start = source.index("[Điều 3")
    parsed = parse_text(
        source,
        DocumentInfo(
            id="nd_117_2024",
            title="Nghị định 117",
            number="117/2024/NĐ-CP",
            doc_type="Decree",
        ),
    )
    common = {
        "contract_version": "provider-reference-mention-v1",
        "provider": "luatvietnam",
        "provider_source_document_id": "366692",
    }
    outer = ProviderReferenceMentionV1(
        **common,
        provider_source_item_id="2732412",
        provider_target_document_id="186730",
        provider_target_item_ids=("1399134",),
        provider_relation_id="158258",
        provider_link_type="CHANGE_CONTENT",
        citation_text="điểm a khoản 2",
        source_char_start=outer_start,
        source_char_end=outer_start + len("[điểm a khoản 2]"),
    )
    inner = ProviderReferenceMentionV1(
        **common,
        provider_source_item_id="2732412",
        provider_target_document_id="186730",
        provider_target_item_ids=("1399200",),
        provider_relation_id="158300",
        provider_link_type="REFERENCE",
        citation_text="Điều 3 Nghị định này",
        source_char_start=inner_start,
        source_char_end=inner_start + len("[Điều 3 Nghị định này]"),
    )
    unit_index = {
        ("luatvietnam", "186730", "1399134"): (
            "nd_82_2020_art2_cl2_pa",
            "Point",
        ),
        ("luatvietnam", "186730", "1399200"): ("nd_82_2020_art3", "Article"),
    }

    candidate = build_provider_relation_candidates(
        parsed,
        source,
        (outer, inner),
        provider_document_index={("luatvietnam", "186730"): "nd_82_2020"},
        provider_unit_index=unit_index,
    )[1]

    assert candidate.relation_candidate == "REFERS_TO"
    assert candidate.source_ownership == "PROJECTED"
    assert candidate.canonical_source_id == "nd_82_2020_art2_cl2_pa"
    assert candidate.canonical_target_id == "nd_82_2020_art3"
    assert candidate.projection_basis_candidate_id is not None
    assert candidate.status == "RESOLVED"


def test_reference_inside_added_unit_does_not_inherit_positional_anchor() -> None:
    source = (
        "Điều 1. Bổ sung\n"
        "1. Bổ sung Điều 4a vào sau [Điều 4] như sau:\n"
        "“Điều 4a. Thực hiện theo [Điều 6 Nghị định này].”"
    )
    outer_start = source.index("[Điều 4]")
    inner_start = source.index("[Điều 6")
    parsed = parse_text(
        source,
        DocumentInfo(
            id="amending_doc",
            title="Văn bản sửa đổi",
            number="1/2024/NĐ-CP",
            doc_type="Decree",
        ),
    )
    common = {
        "contract_version": "provider-reference-mention-v1",
        "provider": "luatvietnam",
        "provider_source_document_id": "100",
    }
    outer = ProviderReferenceMentionV1(
        **common,
        provider_target_document_id="200",
        provider_target_item_ids=("4",),
        provider_link_type="CHANGE_CONTENT",
        citation_text="Điều 4",
        source_char_start=outer_start,
        source_char_end=outer_start + len("[Điều 4]"),
    )
    inner = ProviderReferenceMentionV1(
        **common,
        provider_target_document_id="200",
        provider_target_item_ids=("6",),
        provider_link_type="REFERENCE",
        citation_text="Điều 6 Nghị định này",
        source_char_start=inner_start,
        source_char_end=inner_start + len("[Điều 6 Nghị định này]"),
    )

    candidate = build_provider_relation_candidates(
        parsed,
        source,
        (outer, inner),
        provider_document_index={("luatvietnam", "200"): "target_doc"},
        provider_unit_index={
            ("luatvietnam", "200", "4"): ("target_doc_art4", "Article"),
            ("luatvietnam", "200", "6"): ("target_doc_art6", "Article"),
        },
    )[1]

    assert candidate.status == "UNRESOLVED"
    assert candidate.canonical_source_id is None
    assert candidate.reason_code == "projected_added_source_not_in_corpus"
    assert candidate.projection_basis_candidate_id is not None


def test_provider_item_resolves_only_through_existing_target_hierarchy(
    tmp_path: Path,
) -> None:
    raw_root = tmp_path / "raw"
    processed_root = tmp_path / "processed"
    target_raw = raw_root / "LTV_186730"
    target_processed = processed_root / "LTV_186730"
    target_raw.mkdir(parents=True)
    target_processed.mkdir(parents=True)
    target_html = """
    <div class="the-document-body">
      <p>Điều 2. Quy định</p>
      <p>2. Đối tượng</p>
      <div id="demuc1399134"><p>a) Nội dung cũ.</p></div>
    </div>
    """
    from experiments.luatvietnam_crawler.parser import parse_provider_item_spans

    target_source = "Điều 2. Quy định\n2. Đối tượng\na) Nội dung cũ."
    assert parse_provider_item_spans(target_html, target_source, ("1399134",))
    (target_raw / "source.html").write_text(target_html, encoding="utf-8")
    (target_raw / "source.txt").write_text(target_source + "\n", encoding="utf-8")
    (target_raw / "metadata.json").write_text(
        json.dumps(
            {
                "external_id": "186730",
                "candidate_graph_id": "nd_82_2020",
            }
        ),
        encoding="utf-8",
    )
    target_parsed = parse_text(
        target_source,
        DocumentInfo(
            id="nd_82_2020",
            title="Nghị định 82",
            number="82/2020/NĐ-CP",
            doc_type="Decree",
        ),
    )
    (target_processed / "hierarchy.json").write_text(
        target_parsed.model_dump_json(), encoding="utf-8"
    )

    current_source = "Điều 1. Sửa đổi\n1. Sửa đổi [điểm a khoản 2] như sau:"
    marker_start = current_source.index("[điểm a khoản 2]")
    current_parsed = parse_text(
        current_source,
        DocumentInfo(
            id="nd_117_2024",
            title="Nghị định 117",
            number="117/2024/NĐ-CP",
            doc_type="Decree",
        ),
    )
    reference = ProviderReferenceMentionV1(
        contract_version="provider-reference-mention-v1",
        provider="luatvietnam",
        provider_source_document_id="366692",
        provider_source_item_id="2732412",
        provider_target_document_id="186730",
        provider_target_item_ids=("1399134",),
        provider_relation_id="158258",
        provider_link_type="CHANGE_CONTENT",
        citation_text="điểm a khoản 2",
        source_char_start=marker_start,
        source_char_end=marker_start + len("[điểm a khoản 2]"),
    )

    documents, numbers, units, failures = build_luatvietnam_identity_indexes(
        raw_root, processed_root, current_parsed, (reference,)
    )

    assert documents[("luatvietnam", "186730")] == "nd_82_2020"
    assert numbers[("luatvietnam", "186730")] == "82/2020/NĐ-CP"
    assert units[("luatvietnam", "186730", "1399134")] == (
        "nd_82_2020_art2_cl2_pa",
        "Point",
    )
    assert failures == {}

    (target_processed / "hierarchy.json").unlink()
    _, _, units, failures = build_luatvietnam_identity_indexes(
        raw_root, processed_root, current_parsed, (reference,)
    )
    assert units == {}
    assert failures[("luatvietnam", "186730", "1399134")] == (
        "target_hierarchy_not_available"
    )
