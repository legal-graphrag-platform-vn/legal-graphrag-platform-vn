from __future__ import annotations

from src.shared.ontology.payload_consistency_validator import deterministic_relation_id, validate_payload_consistency


def test_payload_consistency_detects_dangling_relation() -> None:
    report = validate_payload_consistency(
        {
            "nodes": [{"type": "Document", "id": "ldn_2020"}],
            "relations": [{"head_id": "ldn_2020", "type": "CONTAINS", "tail_id": "missing", "properties": {}}],
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
            "relations": [{"head_id": "ldn_2020", "type": "CONTAINS", "tail_id": "ldn_2020_art17", "properties": {}}],
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
