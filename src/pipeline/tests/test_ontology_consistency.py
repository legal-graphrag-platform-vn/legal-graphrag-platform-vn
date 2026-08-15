"""Bắt buộc theo tasks/task-1.graph-construction-pipeline.md — invariant ontology.

Chạy: pytest tests/test_ontology_consistency.py
Tốc độ: <1ms, không cần DB hay LLM.
"""

from src.shared.ontology.contract import (
    APPENDIX_KINDS,
    ATTACHED_INSTRUMENT_KINDS,
    DOCUMENT_RELATION_EXTRACTION_METHODS,
    NODE_ENUMS,
    NODE_OPTIONAL_FIELDS,
    NODE_REQUIRED_FIELDS,
    ONTOLOGY_VERSION,
    REFERENCE_EXTRACTION_METHODS,
)
from src.shared.ontology.validators import CONSTRAINTS, RELATION_ENUM, validate_relation


SEMANTIC_PROPS = {
    "confidence": 0.8,
    "llm_model": "gemini:gemini-2.5-flash",
    "created_at": "2026-07-09T00:00:00+00:00",
}

REFERS_TO_PROPS = {
    **SEMANTIC_PROPS,
    "citation_text": "theo Điều 17",
    "citation_type": "DIRECT",
    "extraction_method": "LLM",
    "reference_bundle_id": "bundle-17",
    "reference_target_count": 1,
    "checkpoint_id": "checkpoint-17",
}


def test_all_relations_have_constraints() -> None:
    """Mọi relation trong enum phải có đúng 1 key trong CONSTRAINTS."""
    missing = RELATION_ENUM - set(CONSTRAINTS.keys())
    assert missing == set(), f"Relations thiếu constraint: {missing}"


def test_executable_contract_matches_frozen_ontology_version() -> None:
    assert ONTOLOGY_VERSION == "1.15.0"


def test_contract_separates_reference_and_document_relation_provenance() -> None:
    assert REFERENCE_EXTRACTION_METHODS == {"RULE", "ENTITY_LINKING", "LLM"}
    assert DOCUMENT_RELATION_EXTRACTION_METHODS == {"DIAGRAM"}


def test_contract_exposes_merged_node_metadata() -> None:
    assert set(NODE_OPTIONAL_FIELDS["Document"]) == {
        "title",
        "issued_date",
        "effective_to",
        "expiry_date",
        "sector",
        "field",
        "signer_title",
        "signer_name",
        "source_url",
        "updated_at",
    }
    assert {"title", "effective_to", "embedding", "updated_at"} <= set(
        NODE_OPTIONAL_FIELDS["Article"]
    )
    assert "updated_at" in NODE_OPTIONAL_FIELDS["Clause"]
    assert {"effective_from", "effective_to", "legal_status", "updated_at"} <= set(
        NODE_OPTIONAL_FIELDS["Point"]
    )
    assert NODE_ENUMS["Point"]["legal_status"] == {
        "ACTIVE",
        "AMENDED",
        "REPEALED",
    }
    assert NODE_ENUMS["Appendix"]["appendix_kind"] == APPENDIX_KINDS
    assert set(NODE_REQUIRED_FIELDS["Appendix"]) == {
        "id",
        "scope",
        "heading",
        "content_raw",
        "appendix_kind",
        "effective_from",
        "legal_status",
    }
    assert {"number", "title", "effective_to", "embedding", "updated_at"} == set(
        NODE_OPTIONAL_FIELDS["Appendix"]
    )
    assert NODE_ENUMS["AttachedInstrument"]["instrument_kind"] == (
        ATTACHED_INSTRUMENT_KINDS
    )
    assert set(NODE_REQUIRED_FIELDS["AttachedInstrument"]) == {
        "id",
        "scope",
        "heading",
        "adoption_text",
        "content_raw",
        "instrument_kind",
    }


def test_no_orphan_constraints() -> None:
    """Không có constraint nào cho relation không tồn tại trong enum."""
    orphans = set(CONSTRAINTS.keys()) - RELATION_ENUM
    assert orphans == set(), f"Constraints thừa (không có trong enum): {orphans}"


def test_grouping_titles_are_required_but_article_title_is_optional() -> None:
    for label in ("Part", "Chapter", "Section", "Subsection"):
        assert "title" in NODE_REQUIRED_FIELDS[label]
    assert "title" not in NODE_REQUIRED_FIELDS["Article"]


def test_refers_to_not_rejected() -> None:
    """REFERS_TO là relation phổ biến nhất — phải pass validator."""
    ok, err = validate_relation(
        "Article",
        "REFERS_TO",
        "Article",
        properties=REFERS_TO_PROPS,
    )
    assert ok, f"REFERS_TO bị reject: {err}"


def test_refers_to_rejects_document_diagram_provenance() -> None:
    properties = {**REFERS_TO_PROPS, "extraction_method": "DIAGRAM"}

    ok, err = validate_relation(
        "Article",
        "REFERS_TO",
        "Document",
        properties=properties,
    )

    assert not ok
    assert "REFERS_TO.extraction_method must be one of" in (err or "")


def test_entity_linking_refers_to_requires_ownership_specific_coordinates() -> None:
    base = {
        "citation_text": "Điều 35",
        "citation_type": "DIRECT",
        "extraction_method": "ENTITY_LINKING",
        "created_at": "2026-08-15T00:00:00+00:00",
        "reference_bundle_id": "provider-1",
        "reference_target_count": 1,
        "source_unit_id": "doc_art1",
        "linker_name": "corpus-structural-registry",
        "linker_version": "2.0.0",
    }
    host_ok, _ = validate_relation(
        "Article",
        "REFERS_TO",
        "Article",
        properties={**base, "source_char_start": 1, "source_char_end": 10},
    )
    projected_ok, _ = validate_relation(
        "Article",
        "REFERS_TO",
        "Article",
        properties={
            **base,
            "source_ownership": "PROJECTED",
            "host_evidence_document_id": "host_doc",
            "host_evidence_source_unit_id": "host_art1",
            "host_evidence_char_start": 1,
            "host_evidence_char_end": 10,
            "projection_basis_candidate_id": "provider-basis-1",
        },
    )
    projected_bad, error = validate_relation(
        "Article",
        "REFERS_TO",
        "Article",
        properties={**base, "source_ownership": "PROJECTED"},
    )

    assert host_ok
    assert projected_ok
    assert not projected_bad
    assert "host_evidence_document_id" in (error or "")


def test_projected_temporal_relation_requires_dual_provenance() -> None:
    ok, error = validate_relation(
        "Article",
        "AMENDS",
        "Article",
        properties={
            "effective_from": "2024-01-01",
            "source_ownership": "PROJECTED",
        },
    )

    assert not ok
    assert "projection_basis_candidate_id" in (error or "")


def test_contains_structural_chain_allows_chapter() -> None:
    ok, err = validate_relation("Document", "CONTAINS", "Chapter")
    assert ok, f"Document->Chapter bị reject: {err}"
    ok, err = validate_relation("Chapter", "CONTAINS", "Article")
    assert ok, f"Chapter->Article bị reject: {err}"


def test_contains_structural_chain_allows_section_and_refers_to_it() -> None:
    for head, tail in (("Chapter", "Section"), ("Section", "Article")):
        ok, err = validate_relation(head, "CONTAINS", tail)
        assert ok, f"{head}->{tail} bị reject: {err}"

    for target in ("Chapter", "Section"):
        ok, err = validate_relation(
            "Clause",
            "REFERS_TO",
            target,
            properties=REFERS_TO_PROPS,
        )
        assert ok, f"Clause REFERS_TO {target} bị reject: {err}"


def test_contains_and_refers_to_support_part_and_subsection() -> None:
    for head, tail in (
        ("Document", "Part"),
        ("Part", "Chapter"),
        ("Section", "Subsection"),
        ("Subsection", "Article"),
    ):
        ok, err = validate_relation(head, "CONTAINS", tail)
        assert ok, f"{head}->{tail} bị reject: {err}"

    for target in ("Part", "Subsection"):
        ok, err = validate_relation(
            "Clause", "REFERS_TO", target, properties=REFERS_TO_PROPS
        )
        assert ok, f"Clause REFERS_TO {target} bị reject: {err}"


def test_contains_allows_evidenced_direct_part_and_section_parents() -> None:
    for head, tail in (
        ("Document", "Section"),
        ("Part", "Section"),
        ("Part", "Article"),
    ):
        ok, err = validate_relation(head, "CONTAINS", tail)
        assert ok, f"{head}->{tail} bị reject: {err}"


def test_appendix_owns_supported_structural_roots_and_is_citable() -> None:
    for child in ("Part", "Chapter", "Section", "Article"):
        ok, err = validate_relation("Appendix", "CONTAINS", child)
        assert ok, f"Appendix->{child} bị reject: {err}"

    for head, tail in (
        ("Appendix", "Article"),
        ("Clause", "Appendix"),
    ):
        ok, err = validate_relation(head, "REFERS_TO", tail, properties=REFERS_TO_PROPS)
        assert ok, f"{head} REFERS_TO {tail} bị reject: {err}"


def test_attached_instrument_owns_supported_structural_roots() -> None:
    for child in ("Appendix", "Part", "Chapter", "Section", "Article"):
        ok, err = validate_relation("AttachedInstrument", "CONTAINS", child)
        assert ok, f"AttachedInstrument->{child} bị reject: {err}"

    ok, err = validate_relation("Document", "CONTAINS", "AttachedInstrument")
    assert ok, f"Document->AttachedInstrument bị reject: {err}"


def test_appendix_does_not_expand_temporal_relation_endpoints_without_evidence() -> (
    None
):
    for relation in ("AMENDS", "REPEALS", "REPLACES"):
        ok, _ = validate_relation(
            "Document",
            relation,
            "Appendix",
            properties={"effective_from": "2026-08-15"},
        )
        assert not ok


def test_contains_still_rejects_unsupported_structural_shortcuts() -> None:
    for head, tail in (
        ("Chapter", "Subsection"),
        ("Document", "Subsection"),
    ):
        ok, _ = validate_relation(head, "CONTAINS", tail)
        assert not ok


def test_requires_not_rejected() -> None:
    ok, err = validate_relation(
        "LegalSubject", "REQUIRES", "LegalConcept", properties=SEMANTIC_PROPS
    )
    assert ok, f"REQUIRES bị reject: {err}"


def test_regulates_rejects_issuer_without_semantic_extraction_contract() -> None:
    ok, err = validate_relation(
        "Article", "REGULATES", "Issuer", properties=SEMANTIC_PROPS
    )
    assert not ok
    assert err == "REGULATES does not allow tail type Issuer"


def test_requires_entity_to_entity_rejected() -> None:
    ok, err = validate_relation(
        "LegalSubject", "REQUIRES", "LegalSubject", properties=SEMANTIC_PROPS
    )
    assert not ok
    assert (
        "tail type" in (err or "")
        or "Invalid tail type" in (err or "")
        or "Invalid pair" in (err or "")
    )


def test_semantic_relation_missing_provenance_rejected() -> None:
    ok, err = validate_relation(
        "LegalSubject", "REQUIRES", "LegalConcept", properties={}
    )
    assert not ok
    assert "llm_model" in (err or "")


def test_extraction_labels_rejected_at_ontology_boundary() -> None:
    ok, err = validate_relation(
        "Entity", "REQUIRES", "Concept", properties=SEMANTIC_PROPS
    )
    assert not ok
    assert (
        "head type" in (err or "")
        or "Invalid head type" in (err or "")
        or "Invalid pair" in (err or "")
    )


def test_refers_to_invalid_citation_type_rejected() -> None:
    ok, err = validate_relation(
        "Article",
        "REFERS_TO",
        "Article",
        properties={**REFERS_TO_PROPS, "citation_type": "FOO"},
    )
    assert not ok
    assert "citation_type" in (err or "")


def test_replaces_document_only() -> None:
    """REPLACES chỉ hợp lệ ở cấp Document theo ontology canonical."""
    ok, err = validate_relation(
        "Article", "REPLACES", "Article", properties={"effective_from": "2021-01-01"}
    )
    assert not ok
    ok, err = validate_relation(
        "Document", "REPLACES", "Document", properties={"effective_from": "2021-01-01"}
    )
    assert ok, f"REPLACES Document-Document bị reject sai: {err}"


def test_repeals_supports_smallest_structural_unit() -> None:
    """Instruction unit and affected unit may both be a Point."""
    for head, tail in (
        ("Document", "Point"),
        ("Point", "Point"),
        ("Clause", "Article"),
    ):
        ok, err = validate_relation(
            head, "REPEALS", tail, properties={"effective_from": "2021-01-01"}
        )
        assert ok, f"REPEALS {head}-{tail} bị reject sai: {err}"


def test_amends_document_to_document_allowed() -> None:
    """AMENDS là active voice và cho phép cấp Document khi văn bản sửa đổi văn bản khác."""
    ok, err = validate_relation(
        "Document", "AMENDS", "Document", properties={"effective_from": "2021-01-01"}
    )
    assert ok, f"AMENDS Document-Document bị reject sai: {err}"


def test_amends_supports_point_to_point() -> None:
    ok, err = validate_relation(
        "Point", "AMENDS", "Point", properties={"effective_from": "2024-11-15"}
    )
    assert ok, f"AMENDS Point-Point bị reject sai: {err}"


def test_amends_missing_effective_from_rejected() -> None:
    """AMENDS bắt buộc required_properties=[effective_from]."""
    ok, err = validate_relation("Article", "AMENDS", "Clause", properties={})
    assert not ok
    assert "effective_from" in (err or "")


def test_guides_whitelist_rule() -> None:
    """GUIDES dùng whitelist doc_type thay cho level property trong Neo4j."""
    ok, err = validate_relation(
        "Document", "GUIDES", "Document", head_doc_type="Law", tail_doc_type="Decree"
    )
    assert ok, f"Law->Decree bị reject sai: {err}"
    ok, err = validate_relation(
        "Document", "GUIDES", "Document", head_doc_type="Circular", tail_doc_type="Law"
    )
    assert not ok, "Circular->Law không hợp lệ nhưng validator lại pass"


def test_unknown_relation_rejected() -> None:
    ok, err = validate_relation("Article", "GUIDED_BY", "Document")
    assert not ok
    assert "use canonical GUIDES" in (err or "")


def test_contains_no_self_loop() -> None:
    ok, err = validate_relation(
        "Document", "CONTAINS", "Article", head_id="dieu_1", tail_id="dieu_1"
    )
    assert not ok
