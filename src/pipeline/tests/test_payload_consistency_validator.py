from __future__ import annotations

from src.shared.ontology.payload_consistency_validator import (
    deterministic_relation_id,
    normalize_citation_text,
    relation_identity_discriminator,
    validate_payload_consistency,
)


def _contains(head_id: str, tail_id: str) -> dict[str, object]:
    return {
        "head_id": head_id,
        "type": "CONTAINS",
        "tail_id": tail_id,
        "properties": {
            "relation_id": deterministic_relation_id(head_id, "CONTAINS", tail_id)
        },
    }


def test_payload_consistency_detects_dangling_relation() -> None:
    report = validate_payload_consistency(
        {
            "nodes": [{"type": "Document", "id": "ldn_2020"}],
            "relations": [
                {
                    "head_id": "ldn_2020",
                    "type": "CONTAINS",
                    "tail_id": "missing",
                    "properties": {},
                }
            ],
        }
    )

    assert report.valid is False
    assert any("Dangling relation tail_id" in error for error in report.errors)


def test_payload_consistency_requires_relation_id() -> None:
    report = validate_payload_consistency(
        {
            "nodes": [
                {"type": "Document", "id": "ldn_2020"},
                {"type": "Article", "id": "ldn_2020_art17"},
            ],
            "relations": [
                {
                    "head_id": "ldn_2020",
                    "type": "CONTAINS",
                    "tail_id": "ldn_2020_art17",
                    "properties": {},
                }
            ],
        }
    )

    assert report.valid is False
    assert any("relation_id" in error for error in report.errors)


def test_payload_consistency_accepts_deterministic_relation_id() -> None:
    relation_id = deterministic_relation_id("ldn_2020", "CONTAINS", "ldn_2020_art17")
    report = validate_payload_consistency(
        {
            "nodes": [
                {"type": "Document", "id": "ldn_2020"},
                {"type": "Article", "id": "ldn_2020_art17"},
            ],
            "relations": [
                {
                    "head_id": "ldn_2020",
                    "type": "CONTAINS",
                    "tail_id": "ldn_2020_art17",
                    "properties": {"relation_id": relation_id},
                }
            ],
        }
    )

    assert report.valid is True


def test_refers_to_identity_uses_normalized_citation_not_mutable_provenance() -> None:
    first = {
        "citation_type": "DIRECT",
        "citation_text": " Theo  Điều 17\nLuật này ",
        "confidence": 0.4,
        "created_at": "2026-07-12T00:00:00Z",
    }
    second = {
        "citation_type": "DIRECT",
        "citation_text": "Theo Điều 17 Luật này",
        "confidence": 0.99,
        "created_at": "2026-07-13T00:00:00Z",
    }

    assert normalize_citation_text(first["citation_text"]) == "Theo Điều 17 Luật này"
    assert relation_identity_discriminator(
        "REFERS_TO", first
    ) == relation_identity_discriminator("REFERS_TO", second)


def test_refers_to_identity_distinguishes_different_citations() -> None:
    first = {"citation_type": "DIRECT", "citation_text": "Điều 17"}
    second = {"citation_type": "DIRECT", "citation_text": "Khoản 1 Điều 17"}

    assert relation_identity_discriminator(
        "REFERS_TO", first
    ) != relation_identity_discriminator("REFERS_TO", second)


def test_payload_consistency_rejects_incomplete_reference_bundle() -> None:
    properties = {
        "citation_type": "RANGE",
        "citation_text": "các điểm a và b khoản này",
        "reference_bundle_id": "bundle-ab",
        "reference_target_count": 2,
    }
    discriminator = relation_identity_discriminator("REFERS_TO", properties)
    properties["relation_id"] = deterministic_relation_id(
        "doc_art1_cl1_pc", "REFERS_TO", "doc_art1_cl1_pa", discriminator
    )

    report = validate_payload_consistency(
        {
            "nodes": [
                {"type": "Point", "id": "doc_art1_cl1_pc"},
                {"type": "Point", "id": "doc_art1_cl1_pa"},
            ],
            "relations": [
                {
                    "head_id": "doc_art1_cl1_pc",
                    "type": "REFERS_TO",
                    "tail_id": "doc_art1_cl1_pa",
                    "properties": properties,
                }
            ],
        }
    )

    assert report.valid is False
    assert any("Incomplete reference bundle" in error for error in report.errors)


def test_payload_consistency_accepts_chapter_preamble_before_sections() -> None:
    report = validate_payload_consistency(
        {
            "nodes": [
                {"type": "Document", "id": "doc"},
                {"type": "Chapter", "id": "doc_ch23"},
                {"type": "Section", "id": "doc_ch23_sec1"},
                {"type": "Article", "id": "doc_art99", "number": "99"},
                {"type": "Article", "id": "doc_art100", "number": "100"},
            ],
            "relations": [
                _contains("doc", "doc_ch23"),
                _contains("doc_ch23", "doc_art99"),
                _contains("doc_ch23", "doc_ch23_sec1"),
                _contains("doc_ch23_sec1", "doc_art100"),
            ],
        }
    )

    assert report.valid is True


def test_payload_consistency_rejects_direct_article_after_section_articles() -> None:
    report = validate_payload_consistency(
        {
            "nodes": [
                {"type": "Document", "id": "doc"},
                {"type": "Chapter", "id": "doc_ch23"},
                {"type": "Section", "id": "doc_ch23_sec1"},
                {"type": "Article", "id": "doc_art353", "number": "353"},
                {"type": "Article", "id": "doc_art354", "number": "354"},
            ],
            "relations": [
                _contains("doc", "doc_ch23"),
                _contains("doc_ch23", "doc_ch23_sec1"),
                _contains("doc_ch23_sec1", "doc_art353"),
                _contains("doc_ch23", "doc_art354"),
            ],
        }
    )

    assert report.valid is False
    assert any(
        "direct Article 354 must precede first Section Article 353" in error
        for error in report.errors
    )
