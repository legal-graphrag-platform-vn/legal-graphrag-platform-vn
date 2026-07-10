from __future__ import annotations

from src.pipeline.validation.record_consistency_validator import validate_record_relation


def test_record_consistency_rejects_temporal_self_loop() -> None:
    result = validate_record_relation(
        relation_type="AMENDS",
        head_id="dieu_1",
        tail_id="dieu_1",
        properties={"effective_from": "2021-01-01"},
        known_entity_ids={"dieu_1"},
        ontology_valid=True,
        head_type="Article",
        tail_type="Article",
    )

    assert result.valid is False
    assert result.hard_fail is True


def test_record_consistency_marks_external_reference_for_review() -> None:
    result = validate_record_relation(
        relation_type="REFERS_TO",
        head_id="dieu_1",
        tail_id="external_doc",
        properties={"citation_text": "theo văn bản khác", "citation_type": "DIRECT"},
        known_entity_ids={"dieu_1"},
        ontology_valid=True,
        head_type="Article",
        tail_type="Document",
    )

    assert result.valid is False
    assert result.review_reason == "missing_external_document_registry"
